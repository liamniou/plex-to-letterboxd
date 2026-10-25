"""Pure matching helpers between Plex watches and Letterboxd diary entries (no I/O, unit-tested)."""
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

DATE_TOLERANCE_DAYS = 1  # older imports used UTC dates; Plex reports local time


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    t = t.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", t)


def split_name(name: str) -> tuple[str, int | None]:
    """'Bad Apples (2025)' -> ('Bad Apples', 2025)."""
    m = re.match(r"^(.*)\s+\((\d{4})\)\s*$", name or "")
    return (m.group(1), int(m.group(2))) if m else (name or "", None)


class DiaryIndex:
    def __init__(self, entries: list[dict]):
        self.by_slug: dict[str, list[dict]] = defaultdict(list)
        self.by_title: dict[str, set[tuple[str, int | None]]] = defaultdict(set)
        for e in entries:
            self.by_slug[e["slug"]].append(e)
            title, year = split_name(e.get("name") or "")
            if title:
                self.by_title[normalize_title(title)].add((e["slug"], year))

    def slug_by_title(self, title: str, year: int | None) -> str | None:
        """Unambiguous slug for a title whose diary year is within ±1 of the Plex year."""
        found = {slug for slug, y in self.by_title.get(normalize_title(title), ()) if year is None or y is None or abs(y - year) <= 1}
        return found.pop() if len(found) == 1 else None

    def find(self, slug: str | None, watched_date: str) -> dict | None:
        if not slug:
            return None
        target = date.fromisoformat(watched_date)
        best = None
        for e in self.by_slug.get(slug, ()):
            delta = abs((date.fromisoformat(e["date"]) - target).days)
            if delta <= DATE_TOLERANCE_DAYS and (best is None or delta < best[0]):
                best = (delta, e)
        return best[1] if best else None

    def has_earlier(self, slug: str | None, watched_date: str) -> bool:
        if not slug:
            return False
        cutoff = (date.fromisoformat(watched_date) - timedelta(days=DATE_TOLERANCE_DAYS)).isoformat()
        return any(e["date"] < cutoff for e in self.by_slug.get(slug, ()))


def rating10(user_rating) -> int | str:
    if user_rating is None:
        return ""
    r = int(round(float(user_rating)))
    return r if 1 <= r <= 10 else ""


def is_rewatch(watch: dict, earlier_watch_exists: bool, diary: DiaryIndex) -> bool:
    if earlier_watch_exists or diary.has_earlier(watch.get("lb_slug"), watch["watched_date"]):
        return True
    # Plays before Plex history/our memory began only show up in the view count.
    last = (watch.get("last_viewed_at") or "")[:10]
    return (watch.get("view_count") or 0) > 1 and last == watch["watched_date"]


def csv_row(watch: dict, rewatch: bool) -> dict:
    return {
        "imdbID": watch.get("imdb_id") or "",
        "tmdbID": watch.get("tmdb_id") or "",
        "Title": watch["title"],
        "Year": watch.get("year") or "",
        "Rating10": rating10(watch.get("user_rating")),
        "WatchedDate": watch["watched_date"],
        "Rewatch": "true" if rewatch else "false",
    }
