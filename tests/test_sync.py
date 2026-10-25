import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import db  # noqa: E402
import matching  # noqa: E402
import plex_source  # noqa: E402
import sync  # noqa: E402

TODAY = date.today()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def test_diary_find_tolerates_one_day():
    idx = matching.DiaryIndex([{"slug": "the-matrix", "name": "The Matrix (1999)", "date": "2026-10-10", "viewing_id": "1"}])
    assert idx.find("the-matrix", "2026-10-11")["viewing_id"] == "1"
    assert idx.find("the-matrix", "2026-10-12") is None
    assert idx.find(None, "2026-10-10") is None


def test_slug_by_title_year_tolerance_and_ambiguity():
    idx = matching.DiaryIndex([
        {"slug": "bad-apples-2025", "name": "Bad Apples (2025)", "date": "2026-10-24", "viewing_id": "1"},
        {"slug": "dune", "name": "Dune (1984)", "date": "2020-01-01", "viewing_id": "2"},
        {"slug": "dune-2021", "name": "Dune (2021)", "date": "2021-01-01", "viewing_id": "3"},
    ])
    assert idx.slug_by_title("Bad Apples", 2026) == "bad-apples-2025"
    assert idx.slug_by_title("Dune", 2021) == "dune-2021"
    assert idx.slug_by_title("Dune", None) is None  # ambiguous
    assert idx.slug_by_title("Amélie", 2001) is None


def test_rating_and_rewatch():
    assert matching.rating10(7.0) == 7
    assert matching.rating10(None) == ""
    assert matching.rating10(0) == ""
    idx = matching.DiaryIndex([{"slug": "x", "name": "X (2000)", "date": "2020-01-01", "viewing_id": "1"}])
    w = {"lb_slug": "x", "watched_date": "2026-01-01", "view_count": 1, "last_viewed_at": "2026-01-01T10:00:00"}
    assert matching.is_rewatch(w, False, idx)
    w2 = {"lb_slug": "y", "watched_date": "2026-01-01", "view_count": 2, "last_viewed_at": "2026-01-01T10:00:00"}
    assert matching.is_rewatch(w2, False, idx)
    w3 = {**w2, "view_count": 1}
    assert not matching.is_rewatch(w3, False, idx)


# ---------------------------------------------------------------------------
# sync flow with a fake Letterboxd session
# ---------------------------------------------------------------------------

class FakeSession:
    def __init__(self, diary, slugs, import_adds=True):
        self.diary = diary
        self.slugs = slugs
        self.import_adds = import_adds
        self.uploads = []

    def read_diary(self, stop_before=None, max_pages=1000):
        return sorted(self.diary, key=lambda e: e["date"], reverse=True), True

    def resolve_slug(self, tmdb_id, imdb_id):
        return self.slugs.get(tmdb_id)

    def upload_csv(self, path):
        import csv
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        self.uploads.append(rows)
        if self.import_adds:
            for r in rows:
                slug = self.slugs.get(r["tmdbID"])
                self.diary.append({"viewing_id": f"v{len(self.diary)}", "slug": slug, "name": r["Title"], "date": r["WatchedDate"], "rating10": r["Rating10"], "rewatch": 0})
        return "Import complete"


@pytest.fixture
def mem_db():
    db.connect(":memory:")
    yield
    db.connect(":memory:")


def add(rk, title, watched, rating=8.0, tmdb=None, status="pending"):
    db.upsert_movie({"rating_key": rk, "title": title, "year": 2020, "imdb_id": None, "tmdb_id": tmdb or str(rk),
                     "thumb": None, "user_rating": rating, "view_count": 1, "last_viewed_at": watched + "T20:00:00"})
    db.insert_watch(rk, watched, watched + "T20:00:00", "plex", status)


def statuses():
    return {r["title"]: r["status"] for r in db.query(f"{db.WATCH_SELECT}")}


def test_baseline_then_upload_and_verify(mem_db):
    settings = db.get_settings()
    add(1, "Old Logged", d(400))
    add(2, "Old Missing", d(300))
    add(3, "Recent Logged", d(2))
    add(4, "Recent New", d(1))
    add(5, "Unrated New", d(1), rating=None)
    session = FakeSession(
        diary=[
            {"viewing_id": "a", "slug": "old-logged", "name": "Old Logged (2020)", "date": d(401), "rating10": 8, "rewatch": 0},
            {"viewing_id": "b", "slug": "recent-logged", "name": "Recent Logged (2020)", "date": d(2), "rating10": 8, "rewatch": 0},
        ],
        slugs={"1": "old-logged", "2": "old-missing", "3": "recent-logged", "4": "recent-new", "5": "unrated-new"},
    )

    stats = sync.reconcile(session, settings, baseline=True)
    assert stats["matched"] == 2
    assert db.get_state("baseline_done") is True
    assert statuses() == {"Old Logged": "synced", "Old Missing": "skipped", "Recent Logged": "synced",
                          "Recent New": "pending", "Unrated New": "pending"}

    candidates = sync.sync_candidates(settings)
    assert [c["title"] for c in candidates] == ["Recent New"]  # unrated waits for a rating
    index = sync.refresh_diary(session, candidates, full=False)
    sync.ensure_slugs(session, candidates, index)
    result = sync.upload(session, sync.match_against_diary(candidates, index, "x"), index, run_id=1)
    assert result["uploaded"] == 1 and result["failed"] == 0
    assert session.uploads[0][0]["Rating10"] == "8" and session.uploads[0][0]["Rewatch"] == "false"
    assert statuses()["Recent New"] == "synced"

    # A second pass has nothing left to upload: memory prevents duplicates.
    assert sync.sync_candidates(settings) == []


def test_upload_not_confirmed_marks_failed_and_retries_are_capped(mem_db):
    db.set_state("baseline_done", True)
    settings = db.get_settings()
    add(1, "Ghost", d(1))
    session = FakeSession(diary=[], slugs={"1": "ghost"}, import_adds=False)
    for attempt in range(settings["max_attempts"]):
        cands = sync.sync_candidates(settings)
        assert len(cands) == 1
        index = sync.refresh_diary(session, cands, full=False)
        sync.ensure_slugs(session, cands, index)
        sync.upload(session, cands, index, run_id=attempt + 1)
    w = db.query(f"{db.WATCH_SELECT}")[0]
    assert w["status"] == "failed" and w["attempts"] == settings["max_attempts"]
    assert sync.sync_candidates(settings) == []


def test_initial_status_after_baseline(mem_db):
    settings = db.get_settings()
    assert plex_source.initial_status(d(400), settings, baseline_done=False) == ("pending", None)
    assert plex_source.initial_status(d(1), settings, baseline_done=True) == ("pending", None)
    assert plex_source.initial_status(d(400), settings, baseline_done=True)[0] == "skipped"


def test_settings_validation(mem_db):
    assert db.update_settings({"sync_interval_minutes": "90", "auto_sync": "false"})["sync_interval_minutes"] == 90
    assert db.get_settings()["auto_sync"] is False
    with pytest.raises(ValueError):
        db.update_settings({"nope": 1})


class ErrorSession(FakeSession):
    """Lookups fail transiently for ids listed in `errors`."""

    def __init__(self, *a, errors=(), **kw):
        super().__init__(*a, **kw)
        self.errors = set(errors)

    def resolve_slug(self, tmdb_id, imdb_id):
        from letterboxd import LetterboxdError
        if tmdb_id in self.errors:
            raise LetterboxdError("challenge page")
        return super().resolve_slug(tmdb_id, imdb_id)


def run_sync_with(session, monkeypatch):
    class _Ctx:
        def __enter__(self):
            return session

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(sync, "LetterboxdSession", _Ctx)
    monkeypatch.setattr(sync.plex_source, "scan", lambda settings: {})
    return sync.run_sync(db.get_settings(), run_id=1)


def test_lookup_error_holds_watch_and_not_found_fails_without_upload(mem_db, monkeypatch):
    db.set_state("baseline_done", True)
    add(1, "Flaky", d(1))
    add(2, "Unknown", d(1))
    add(3, "Good", d(1))
    session = ErrorSession(diary=[], slugs={"3": "good"}, errors={"1"})
    summary = run_sync_with(session, monkeypatch)
    assert [r["Title"] for r in session.uploads[0]] == ["Good"]
    assert summary["lookup_errors"] == 1
    st = statuses()
    assert st == {"Flaky": "pending", "Unknown": "failed", "Good": "synced"}
    # The failed lookup was not cached, so it is retried next time.
    assert db.query_one("SELECT lb_slug_checked_at FROM movies WHERE rating_key=1")["lb_slug_checked_at"] is None


def test_diary_read_error_aborts_without_touching_cache(mem_db, monkeypatch):
    from letterboxd import LetterboxdError
    db.replace_diary([{"viewing_id": "a", "slug": "x", "name": "X (2020)", "date": d(5), "rating10": 8, "rewatch": 0}], full=True)
    add(1, "X", d(5))

    class Broken(FakeSession):
        def read_diary(self, stop_before=None, max_pages=1000):
            raise LetterboxdError("blocked")

    with pytest.raises(LetterboxdError):
        sync.reconcile(Broken(diary=[], slugs={}), db.get_settings(), baseline=True)
    assert db.status_counts()["diary"] == 1
    assert db.get_state("baseline_done") is None
    assert statuses() == {"X": "pending"}
