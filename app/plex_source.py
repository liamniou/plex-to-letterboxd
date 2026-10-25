"""Read watch activity from Plex into the database."""
import logging
from datetime import date, datetime, timedelta

from plexapi.server import PlexServer

import config
import db

logger = logging.getLogger(__name__)


def _ids(movie) -> tuple[str, str]:
    imdb_id = tmdb_id = ""
    try:
        for guid in movie.guids:
            if guid.id.startswith("imdb://"):
                imdb_id = guid.id.split("://", 1)[1]
            elif guid.id.startswith("tmdb://"):
                tmdb_id = guid.id.split("://", 1)[1]
    except Exception as exc:
        logger.warning(f"Could not read GUIDs for {movie.title}: {exc}")
    return imdb_id, tmdb_id


def connect(settings: dict) -> tuple[PlexServer, PlexServer, int | None]:
    """Return (admin server, user-scoped server, history account id)."""
    admin = PlexServer(config.PLEX_URL, config.PLEX_TOKEN, timeout=60)
    user = settings.get("plex_user") or ""
    if not user:
        return admin, admin, 1  # account 1 is the server owner
    scoped = admin.switchUser(user)
    account_id = next(
        (a.id for a in admin.systemAccounts() if a.name and a.name.lower() == user.lower()), None
    )
    return admin, scoped, account_id


def initial_status(watched_date: str, settings: dict, baseline_done: bool) -> tuple[str, str | None]:
    """Status for a newly discovered watch.

    Before the baseline has run, everything is held as pending and the diary
    reconciliation decides. Afterwards, stale discoveries (e.g. an old film
    marked watched in bulk) are skipped instead of flooding the diary.
    """
    if not baseline_done:
        return "pending", None
    max_age = settings["max_age_days"]
    if max_age and watched_date < (date.today() - timedelta(days=max_age)).isoformat():
        return "skipped", f"Older than {max_age} days when discovered"
    return "pending", None


def scan(settings: dict) -> dict:
    admin, scoped, account_id = connect(settings)
    section = scoped.library.section(settings["plex_library"])
    baseline_done = bool(db.get_state("baseline_done", False))

    logger.info(f"Reading Plex library '{section.title}'...")
    movies = {m.ratingKey: m for m in section.all()}
    logger.info(f"Library has {len(movies)} movies")

    # (rating_key, date) -> (watched_at, source)
    candidates: dict[tuple[int, str], tuple[str, str]] = {}
    stats = {"movies": len(movies), "watched": 0, "in_progress": 0, "no_ids": 0, "history": 0, "new_watches": 0, "new_skipped": 0}

    for m in movies.values():
        if not m.isWatched or not m.lastViewedAt:
            continue
        # A resuming film has not passed Plex's "played" threshold for this viewing.
        if getattr(m, "viewOffset", None):
            stats["in_progress"] += 1
            continue
        stats["watched"] += 1
        candidates[(m.ratingKey, m.lastViewedAt.date().isoformat())] = (m.lastViewedAt.isoformat(), "plex")

    if settings["history_days"] and account_id is not None:
        mindate = datetime.now() - timedelta(days=settings["history_days"])
        try:
            history = admin.history(librarySectionID=section.key, mindate=mindate, accountID=account_id, maxresults=5000)
        except Exception as exc:
            logger.warning(f"Could not read Plex play history: {exc}")
            history = []
        for h in history:
            rk = int(h.ratingKey) if h.ratingKey else None
            if rk in movies and h.viewedAt:
                stats["history"] += 1
                candidates.setdefault((rk, h.viewedAt.date().isoformat()), (h.viewedAt.isoformat(), "history"))

    seen_movies: set[int] = set()
    for (rk, watched_date), (watched_at, source) in sorted(candidates.items(), key=lambda kv: kv[0][1]):
        m = movies[rk]
        if rk not in seen_movies:
            imdb_id, tmdb_id = _ids(m)
            if not imdb_id and not tmdb_id:
                stats["no_ids"] += 1
                logger.warning(f"Skipping {m.title} - no IMDb/TMDB id, Letterboxd cannot match it")
                continue
            db.upsert_movie({
                "rating_key": rk,
                "title": m.title,
                "year": m.year,
                "imdb_id": imdb_id or None,
                "tmdb_id": tmdb_id or None,
                "thumb": m.thumb,
                "user_rating": m.userRating,
                "view_count": m.viewCount or 0,
                "last_viewed_at": m.lastViewedAt.isoformat() if m.lastViewedAt else None,
            })
            seen_movies.add(rk)
        status, note = initial_status(watched_date, settings, baseline_done)
        if db.insert_watch(rk, watched_date, watched_at, source, status, note):
            stats["new_watches"] += 1
            if status == "skipped":
                stats["new_skipped"] += 1
            logger.info(f"New watch: {m.title} ({m.year}) on {watched_date} [{source}] -> {status}")

    logger.info(
        f"Plex scan done: {stats['watched']} watched, {stats['in_progress']} in progress, "
        f"{stats['new_watches']} new watch(es)"
    )
    return stats


_machine_id: str | None = None


def machine_id() -> str | None:
    """Plex server machineIdentifier (needed for app.plex.tv deep links); cached once found."""
    global _machine_id
    if _machine_id is None:
        import requests

        try:
            resp = requests.get(f"{config.PLEX_URL.rstrip('/')}/identity", headers={"Accept": "application/json"}, timeout=5)
            resp.raise_for_status()
            _machine_id = resp.json()["MediaContainer"]["machineIdentifier"]
        except Exception as exc:
            logger.warning(f"Could not read Plex machine identifier: {exc}")
    return _machine_id


def fetch_thumb(thumb: str) -> tuple[bytes, str]:
    import requests

    resp = requests.get(
        f"{config.PLEX_URL.rstrip('/')}/photo/:/transcode",
        params={"url": thumb, "width": 300, "height": 450, "minSize": 1, "X-Plex-Token": config.PLEX_TOKEN},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")
