"""Job implementations: Plex scan, diary reconciliation (incl. first-run baseline) and Letterboxd sync."""
import logging
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

import db
import plex_source
from letterboxd import LetterboxdError, LetterboxdSession, build_csv_rows, send_telegram_message
from matching import DiaryIndex, csv_row, is_rewatch

logger = logging.getLogger("sync")

SLUG_RECHECK_DAYS = 7


def _days_before(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) - timedelta(days=days)).isoformat()


def sync_candidates(settings: dict) -> list[dict]:
    rows = db.query(
        f"{db.WATCH_SELECT} WHERE w.status='pending' OR (w.status='failed' AND w.attempts < ?) ORDER BY w.watched_date, w.id",
        (settings["max_attempts"],),
    )
    if settings["require_rating"]:
        rows = [r for r in rows if r["user_rating"] is not None]
    return rows


def open_watches() -> list[dict]:
    return db.query(f"{db.WATCH_SELECT} WHERE w.status IN ('pending','failed') ORDER BY w.watched_date, w.id")


def load_diary_index() -> DiaryIndex:
    return DiaryIndex(db.query("SELECT * FROM diary"))


def refresh_diary(session, watches: list[dict], full: bool) -> DiaryIndex:
    stop_before = None if full or not watches else _days_before(min(w["watched_date"] for w in watches), 3)
    entries, complete = session.read_diary(stop_before=stop_before)
    db.replace_diary(entries, full=full and complete)
    db.set_state("diary_read_at", db.now_iso())
    logger.info(f"Read {len(entries)} diary entries{' (complete)' if complete else ''}")
    return load_diary_index()


def ensure_slugs(session, watches: list[dict], index: DiaryIndex) -> None:
    """Fill w['lb_slug'] and w['slug_state'] ('found' | 'not_found' | 'error') for each watch.

    Lookup results are cached on the movie row; errors are not cached, so the
    lookup is retried next run.
    """
    resolved: dict[int, tuple[str | None, str]] = {}
    recheck_before = (datetime.now(timezone.utc) - timedelta(days=SLUG_RECHECK_DAYS)).isoformat()
    lookups = 0
    for w in watches:
        rk = w["rating_key"]
        if w.get("lb_slug"):
            w["slug_state"] = "found"
            continue
        if rk not in resolved:
            slug = index.slug_by_title(w["title"], w.get("year"))
            state = "found" if slug else "not_found"
            recently_checked = w.get("lb_slug_checked_at") and w["lb_slug_checked_at"] >= recheck_before
            if not slug and session is not None and not recently_checked:
                lookups += 1
                if lookups % 25 == 1:
                    logger.info(f"Looking up films on Letterboxd by TMDB/IMDb id ({lookups} so far)...")
                try:
                    slug = session.resolve_slug(w.get("tmdb_id"), w.get("imdb_id"))
                    state = "found" if slug else "not_found"
                    if not slug:
                        logger.warning(f"{w['title']} ({w.get('year')}) is not on Letterboxd")
                except LetterboxdError as exc:
                    state = "error"
                    logger.warning(f"Could not look up {w['title']} on Letterboxd: {exc}")
            elif not slug and session is None:
                state = "error"
            if state != "error":
                db.execute("UPDATE movies SET lb_slug=COALESCE(?, lb_slug), lb_slug_checked_at=? WHERE rating_key=?", (slug, db.now_iso(), rk))
            resolved[rk] = (slug, state)
        w["lb_slug"], w["slug_state"] = resolved[rk]


def match_against_diary(watches: list[dict], index: DiaryIndex, note: str) -> list[dict]:
    """Mark watches already in the diary as synced; return the rest."""
    remaining = []
    for w in watches:
        entry = index.find(w.get("lb_slug"), w["watched_date"])
        if entry:
            db.set_watch_status(w["id"], "synced", lb_viewing_id=entry["viewing_id"], synced_at=db.now_iso(), note=note, last_error=None)
            logger.info(f"In diary: {w['title']} on {entry['date']}")
        else:
            remaining.append(w)
    return remaining


def apply_baseline(remaining: list[dict], settings: dict) -> int:
    """First run: unmatched watches older than max_age_days are history we never synced; skip them."""
    max_age = settings["max_age_days"]
    cutoff = (date.today() - timedelta(days=max_age)).isoformat()
    skipped = 0
    for w in remaining:
        if w["watched_date"] < cutoff:
            db.set_watch_status(w["id"], "skipped", note=f"Not in Letterboxd diary at first run and older than {max_age} days")
            skipped += 1
    db.set_state("baseline_done", True)
    db.set_state("baseline_at", db.now_iso())
    logger.info(f"Baseline complete: {skipped} old unsynced watch(es) skipped; queue them from the UI if wanted")
    return skipped


def reconcile(session, settings: dict, baseline: bool = False) -> dict:
    """Read the whole diary and match every open watch against it."""
    watches = open_watches()
    index = refresh_diary(session, watches, full=True)
    ensure_slugs(session, watches, index)
    remaining = match_against_diary(watches, index, "Found in Letterboxd diary")
    stats = {"checked": len(watches), "matched": len(watches) - len(remaining), "diary_entries": len(index.by_slug)}
    if baseline:
        stats["baseline_skipped"] = apply_baseline(remaining, settings)
    return stats


def upload(session, watches: list[dict], index: DiaryIndex, run_id: int) -> dict:
    """Import watches (all must have a known lb_slug) and verify each one in the diary."""
    assert all(w.get("lb_slug") for w in watches), "upload() needs resolved slugs for verification"
    rows = []
    for w in watches:
        earlier = db.query_one(
            "SELECT 1 FROM watches WHERE rating_key=? AND watched_date<? LIMIT 1", (w["rating_key"], w["watched_date"])
        )
        rows.append(csv_row(w, is_rewatch(w, bool(earlier), index)))

    fd, path = tempfile.mkstemp(prefix="lb_", suffix=".csv")
    with os.fdopen(fd, "w", newline="") as fh:
        fh.write(build_csv_rows(rows))
    logger.info("Uploading CSV:\n" + build_csv_rows(rows).strip())
    try:
        result = session.upload_csv(path)
    except Exception as exc:
        for w in watches:
            db.set_watch_status(w["id"], "failed", attempts=w["attempts"] + 1, last_error=f"Upload failed: {exc}")
        raise
    finally:
        os.unlink(path)
    logger.info(f"Letterboxd: {result}")

    time.sleep(5)
    index = refresh_diary(session, watches, full=False)
    ok, failed = [], []
    for w in watches:
        entry = index.find(w.get("lb_slug"), w["watched_date"])
        if entry:
            db.set_watch_status(
                w["id"], "synced", synced_at=db.now_iso(), synced_run_id=run_id, attempts=w["attempts"] + 1,
                rating10=rows[watches.index(w)]["Rating10"] or None, last_error=None,
                lb_viewing_id=entry["viewing_id"], note="Imported",
            )
            ok.append(w)
        else:
            db.set_watch_status(w["id"], "failed", attempts=w["attempts"] + 1, last_error="Not found in Letterboxd diary after import")
            failed.append(w)
    return {"import_result": result, "uploaded": len(ok), "failed": len(failed), "titles": [w["title"] for w in ok], "failed_titles": [w["title"] for w in failed]}


def run_scan(settings: dict, run_id: int) -> dict:
    return plex_source.scan(settings)


def run_reconcile(settings: dict, run_id: int) -> dict:
    with LetterboxdSession() as session:
        return reconcile(session, settings, baseline=not db.get_state("baseline_done", False))


def run_sync(settings: dict, run_id: int) -> dict:
    summary = {"scan": plex_source.scan(settings)}
    baseline_needed = not db.get_state("baseline_done", False)
    candidates = sync_candidates(settings)
    waiting = db.status_counts()["needs_rating"] if settings["require_rating"] else 0
    if not candidates and not baseline_needed:
        logger.info(f"Nothing to sync ({waiting} watch(es) waiting for a rating)" if waiting else "Nothing to sync")
        return {**summary, "uploaded": 0, "waiting_rating": waiting}

    with LetterboxdSession() as session:
        if baseline_needed:
            logger.info("First run: reconciling Plex history with the full Letterboxd diary")
            summary["baseline"] = reconcile(session, settings, baseline=True)
            candidates = sync_candidates(settings)
            if not candidates:
                return {**summary, "uploaded": 0}

        index = refresh_diary(session, candidates, full=False)
        ensure_slugs(session, candidates, index)
        remaining = match_against_diary(candidates, index, "Already in Letterboxd diary")
        summary["already_in_diary"] = len(candidates) - len(remaining)
        uploadable = []
        for w in remaining:
            if w["slug_state"] == "found":
                uploadable.append(w)
            elif w["slug_state"] == "not_found":
                # Letterboxd's importer matches by the same ids, so uploading cannot succeed (or be verified).
                db.set_watch_status(w["id"], "failed", attempts=w["attempts"] + 1, last_error="Film not found on Letterboxd by TMDB/IMDb id")
            else:
                logger.warning(f"Holding {w['title']} until its Letterboxd lookup succeeds")
        summary["lookup_errors"] = sum(1 for w in remaining if w["slug_state"] == "error")
        batch = uploadable[: settings["batch_size"]]
        if not batch:
            logger.info("Nothing left to upload")
            return {**summary, "uploaded": 0}
        result = upload(session, batch, index, run_id)
        summary.update(result)

    if settings["telegram_enabled"] and (result["uploaded"] or result["failed"]):
        msg = f"Letterboxd: logged {result['uploaded']} film(s)"
        if result["titles"]:
            msg += ": " + ", ".join(result["titles"])
        if result["failed"]:
            msg += f"\n⚠️ {result['failed']} not confirmed: " + ", ".join(result["failed_titles"])
        send_telegram_message(msg)
    return summary


JOBS = {"scan": run_scan, "sync": run_sync, "reconcile": run_reconcile}
