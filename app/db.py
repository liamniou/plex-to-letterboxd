"""SQLite persistence: the service's memory of movies, watches, runs and the Letterboxd diary."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    rating_key      INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    year            INTEGER,
    imdb_id         TEXT,
    tmdb_id         TEXT,
    thumb           TEXT,
    user_rating     REAL,
    view_count      INTEGER DEFAULT 0,
    last_viewed_at  TEXT,
    lb_slug         TEXT,
    lb_slug_checked_at TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS watches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rating_key      INTEGER NOT NULL REFERENCES movies(rating_key),
    watched_date    TEXT NOT NULL,
    watched_at      TEXT,
    source          TEXT NOT NULL DEFAULT 'plex',
    status          TEXT NOT NULL DEFAULT 'pending',
    rewatch         INTEGER NOT NULL DEFAULT 0,
    rating10        INTEGER,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    note            TEXT,
    synced_at       TEXT,
    synced_run_id   INTEGER,
    lb_viewing_id   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (rating_key, watched_date)
);
CREATE INDEX IF NOT EXISTS idx_watches_status ON watches(status);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    summary     TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS run_logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  INTEGER NOT NULL,
    ts      TEXT NOT NULL,
    level   TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_logs_run ON run_logs(run_id, id);

CREATE TABLE IF NOT EXISTS diary (
    viewing_id  TEXT PRIMARY KEY,
    slug        TEXT NOT NULL,
    name        TEXT,
    date        TEXT NOT NULL,
    rating10    INTEGER,
    rewatch     INTEGER NOT NULL DEFAULT 0,
    seen_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diary_slug ON diary(slug, date);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

WATCH_STATUSES = ("pending", "synced", "failed", "skipped")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | None = None, recover: bool = False) -> sqlite3.Connection:
    """Open (or reopen) the shared connection. Pass ':memory:' in tests.

    recover=True (service startup only) fails runs left 'running' by a previous process.
    """
    global _conn
    path = path or config.DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA busy_timeout=15000")  # jobs write from a child process
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(SCHEMA)
        if recover:
            _conn.execute(
                "UPDATE runs SET status='failed', error='Interrupted by restart', finished_at=? WHERE status='running'",
                (now_iso(),),
            )
    return _conn


def conn() -> sqlite3.Connection:
    if _conn is None:
        connect()
    return _conn


def query(sql: str, params=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def query_one(sql: str, params=()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=()) -> int:
    """Run a write statement; returns lastrowid."""
    with _lock:
        return conn().execute(sql, params).lastrowid


class transaction:
    def __enter__(self):
        _lock.acquire()
        conn().execute("BEGIN IMMEDIATE")
        return conn()

    def __exit__(self, exc_type, *_):
        try:
            conn().execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            _lock.release()


# ---------------------------------------------------------------------------
# Settings / state
# ---------------------------------------------------------------------------

def get_settings() -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in query("SELECT key, value FROM settings")}
    return {k: stored.get(k, default) for k, (_, default) in config.SETTINGS_SCHEMA.items()}


def update_settings(values: dict) -> dict:
    for key, raw in values.items():
        if key not in config.SETTINGS_SCHEMA:
            raise ValueError(f"Unknown setting: {key}")
        typ, _ = config.SETTINGS_SCHEMA[key]
        if typ is bool:
            val = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
        elif typ is int:
            val = int(raw)
            if val < 0:
                raise ValueError(f"{key} must be >= 0")
        else:
            val = str(raw).strip()
        execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(val)),
        )
    return get_settings()


def get_state(key: str, default=None):
    row = query_one("SELECT value FROM state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_state(key: str, value) -> None:
    execute(
        "INSERT INTO state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


# ---------------------------------------------------------------------------
# Runs & logs
# ---------------------------------------------------------------------------

def create_run(kind: str, trigger: str) -> int:
    return execute(
        "INSERT INTO runs(kind, trigger, status, started_at) VALUES(?, ?, 'running', ?)",
        (kind, trigger, now_iso()),
    )


def finish_run(run_id: int, status: str, summary: dict | None = None, error: str | None = None) -> None:
    execute(
        "UPDATE runs SET status=?, finished_at=?, summary=?, error=? WHERE id=?",
        (status, now_iso(), json.dumps(summary or {}), error, run_id),
    )


def add_log(run_id: int, level: str, message: str) -> None:
    execute(
        "INSERT INTO run_logs(run_id, ts, level, message) VALUES(?, ?, ?, ?)",
        (run_id, now_iso(), level, message),
    )


def _decode_run(r: dict) -> dict:
    r["summary"] = json.loads(r["summary"]) if r.get("summary") else {}
    return r


def list_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    return [_decode_run(r) for r in query("SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))]


def get_run(run_id: int) -> dict | None:
    r = query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    return _decode_run(r) if r else None


def get_run_logs(run_id: int, after_id: int = 0) -> list[dict]:
    return query("SELECT id, ts, level, message FROM run_logs WHERE run_id=? AND id>? ORDER BY id", (run_id, after_id))


def prune_runs(keep: int = 500) -> None:
    with _lock:
        conn().execute("DELETE FROM run_logs WHERE run_id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT ?)", (keep,))
        conn().execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT ?)", (keep,))


# ---------------------------------------------------------------------------
# Movies & watches
# ---------------------------------------------------------------------------

def upsert_movie(m: dict) -> None:
    execute(
        """INSERT INTO movies(rating_key, title, year, imdb_id, tmdb_id, thumb, user_rating, view_count, last_viewed_at, updated_at)
           VALUES(:rating_key, :title, :year, :imdb_id, :tmdb_id, :thumb, :user_rating, :view_count, :last_viewed_at, :updated_at)
           ON CONFLICT(rating_key) DO UPDATE SET
             title=excluded.title, year=excluded.year, imdb_id=excluded.imdb_id, tmdb_id=excluded.tmdb_id,
             thumb=excluded.thumb, user_rating=excluded.user_rating, view_count=excluded.view_count,
             last_viewed_at=excluded.last_viewed_at, updated_at=excluded.updated_at""",
        {**m, "updated_at": now_iso()},
    )


def insert_watch(rating_key: int, watched_date: str, watched_at: str | None, source: str, status: str = "pending", note: str | None = None) -> bool:
    """Insert a watch if (movie, date) is new. Returns True when inserted."""
    ts = now_iso()
    with _lock:
        cur = conn().execute(
            """INSERT OR IGNORE INTO watches(rating_key, watched_date, watched_at, source, status, note, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (rating_key, watched_date, watched_at, source, status, note, ts, ts),
        )
        return cur.rowcount > 0


WATCH_SELECT = """
SELECT w.*, m.title, m.year, m.imdb_id, m.tmdb_id, m.user_rating, m.view_count, m.last_viewed_at,
       m.lb_slug, m.lb_slug_checked_at, (m.thumb IS NOT NULL) AS has_poster
FROM watches w JOIN movies m ON m.rating_key = w.rating_key
"""


def list_watches(status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0,
                 needs_rating: bool | None = None) -> tuple[list[dict], int]:
    where, params = [], []
    if status:
        where.append("w.status = ?")
        params.append(status)
    if q:
        where.append("(m.title LIKE ? OR m.imdb_id = ? OR m.tmdb_id = ?)")
        params += [f"%{q}%", q, q]
    if needs_rating is not None:
        where.append("m.user_rating IS NULL" if needs_rating else "m.user_rating IS NOT NULL")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = query_one(f"SELECT COUNT(*) AS n FROM watches w JOIN movies m ON m.rating_key = w.rating_key{clause}", params)["n"]
    rows = query(f"{WATCH_SELECT}{clause} ORDER BY w.watched_date DESC, w.id DESC LIMIT ? OFFSET ?", params + [limit, offset])
    return rows, total


def get_watch(watch_id: int) -> dict | None:
    return query_one(f"{WATCH_SELECT} WHERE w.id = ?", (watch_id,))


def set_watch_status(watch_id: int, status: str, **fields) -> None:
    if status not in WATCH_STATUSES:
        raise ValueError(f"Invalid status {status}")
    cols = {"status": status, "updated_at": now_iso(), **fields}
    sets = ", ".join(f"{k}=?" for k in cols)
    execute(f"UPDATE watches SET {sets} WHERE id=?", (*cols.values(), watch_id))


def status_counts() -> dict:
    counts = {s: 0 for s in WATCH_STATUSES}
    for r in query("SELECT status, COUNT(*) AS n FROM watches GROUP BY status"):
        counts[r["status"]] = r["n"]
    counts["needs_rating"] = query_one(
        "SELECT COUNT(*) AS n FROM watches w JOIN movies m ON m.rating_key=w.rating_key "
        "WHERE w.status IN ('pending','failed') AND m.user_rating IS NULL"
    )["n"]
    counts["movies"] = query_one("SELECT COUNT(*) AS n FROM movies")["n"]
    counts["diary"] = query_one("SELECT COUNT(*) AS n FROM diary")["n"]
    return counts


def replace_diary(entries: list[dict], full: bool) -> None:
    """Store scraped diary entries. A full scan replaces the cache (deleted entries disappear)."""
    ts = now_iso()
    with transaction() as c:
        if full:
            c.execute("DELETE FROM diary")
        c.executemany(
            """INSERT INTO diary(viewing_id, slug, name, date, rating10, rewatch, seen_at)
               VALUES(:viewing_id, :slug, :name, :date, :rating10, :rewatch, :seen_at)
               ON CONFLICT(viewing_id) DO UPDATE SET slug=excluded.slug, name=excluded.name, date=excluded.date,
                 rating10=excluded.rating10, rewatch=excluded.rewatch, seen_at=excluded.seen_at""",
            [{**e, "seen_at": ts} for e in entries],
        )
