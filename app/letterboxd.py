"""Letterboxd browser automation (Camoufox/Playwright): login, diary scraping, slug lookup and CSV import.

Letterboxd has no public API, so everything goes through a real browser.
"""
import csv
import logging
import re
import time
from io import StringIO

import requests
from camoufox.sync_api import Camoufox
from playwright.sync_api import TimeoutError as PlaywrightTimeout

import config

logger = logging.getLogger(__name__)

BASE = "https://letterboxd.com"
class LetterboxdError(RuntimeError):
    """Letterboxd returned something unexpected (error page, challenge, logged out...)."""


CSV_FIELDS = ["imdbID", "tmdbID", "Title", "Year", "Rating10", "WatchedDate", "Rewatch"]

LETTERBOXD_USERNAME = config.LETTERBOXD_USERNAME
LETTERBOXD_PASSWORD = config.LETTERBOXD_PASSWORD


def send_telegram_message(message: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
    except Exception as exc:
        logger.error(f"Telegram send failed: {exc}")


def build_csv_rows(items: list[dict]) -> str:
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(items)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Page helpers (also used by cleanup_diary.py)
# ---------------------------------------------------------------------------

def _settle(page, attempts: int = 20) -> None:
    """Wait until the page has a DOM body (navigation may still be in flight after clicks)."""
    for _ in range(attempts):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            if page.evaluate("() => !!document.body"):
                return
        except Exception:
            pass
        time.sleep(0.5)


def _goto(page, url: str, attempts: int = 4):
    last_exc = None
    for i in range(attempts):
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            _settle(page)
            return response
        except PlaywrightTimeout as exc:
            last_exc = exc
            logger.warning(f"Timeout loading {url} (attempt {i + 1}/{attempts}); retrying")
            time.sleep(3)
    raise last_exc


def _handle_cookie_consent(page) -> bool:
    for selector in (".fc-cta-consent", 'button:has-text("Consent")', 'button:has-text("Accept")', 'button:has-text("I agree")'):
        try:
            btn = page.locator(selector)
            if btn.is_visible(timeout=1500):
                btn.click()
                time.sleep(1)
                return True
        except Exception:
            continue
    for frame in page.frames:
        try:
            btn = frame.locator(".fc-cta-consent, button:has-text('Consent')")
            if btn.is_visible(timeout=500):
                btn.click()
                time.sleep(1)
                return True
        except Exception:
            continue
    return False


def _check_if_logged_in(page) -> bool:
    try:
        return "logged-in" in (page.evaluate("() => document.body ? document.body.className : ''") or "")
    except Exception:
        return False


def _login(page) -> bool:
    if not LETTERBOXD_USERNAME or not LETTERBOXD_PASSWORD:
        raise RuntimeError("LETTERBOXD_USERNAME / LETTERBOXD_PASSWORD are not set")
    if "/sign-in" not in page.url:
        _goto(page, f"{BASE}/sign-in/")
    _handle_cookie_consent(page)
    if _check_if_logged_in(page):
        return True
    logger.info("Logging in to Letterboxd...")
    page.wait_for_selector("#field-username", timeout=20000)
    page.fill("#field-username", LETTERBOXD_USERNAME)
    page.fill("#field-password", LETTERBOXD_PASSWORD)
    page.locator("form button[type=submit], form input[type=submit]").first.click()
    try:
        page.wait_for_url(lambda u: "/sign-in" not in u, timeout=30000)
    except PlaywrightTimeout:
        pass
    _settle(page)
    if _check_if_logged_in(page):
        logger.info("Login successful")
        return True
    err = page.evaluate("() => (document.querySelector('.form-error, .errormessage, .error')||{}).textContent || ''").strip()
    logger.error(f"Login failed{': ' + err if err else ''}")
    return False


def _resolve_username(page) -> str:
    """Profile slug of the signed-in member (from the /<user>/following/ menu link)."""
    slug = page.evaluate(
        r"""() => {
            const a = [...document.querySelectorAll('a[href]')]
              .map(x => x.getAttribute('href') || '')
              .find(h => /^\/[^\/]+\/following\/$/.test(h));
            return a ? a.split('/')[1] : '';
        }"""
    )
    if not slug:
        raise RuntimeError("Could not determine Letterboxd username after login")
    return slug


_DIARY_JS = r"""() => [...document.querySelectorAll('tr.diary-entry-row')].map(tr => {
    const item = tr.querySelector('[data-item-slug]');
    const link = tr.querySelector("a[href*='/film/']");
    // The month cell also links to /for/YYYY/MM/, so read the day cell explicitly.
    const day = tr.querySelector("td.col-daydate a") || tr.querySelector("a.daydate");
    const m = day ? (day.getAttribute('href') || '').match(/for\/(\d{4})\/(\d{2})\/(\d{2})/) : null;
    const input = tr.querySelector('input.rateit-field');
    const rated = (tr.querySelector('[class*="rated-"]') || {}).className || '';
    const rm = rated.match(/rated-(\d+)/);
    const rewatch = tr.querySelector('td.col-rewatch');
    const vidEl = tr.hasAttribute('data-viewing-id') ? tr : tr.querySelector('[data-viewing-id]');
    return {
        viewing_id: vidEl ? vidEl.getAttribute('data-viewing-id') : null,
        slug: item ? item.getAttribute('data-item-slug') : (link ? (link.getAttribute('href') || '').replace(/.*\/film\//, '').replace(/\/.*/, '') : null),
        name: item ? item.getAttribute('data-item-name') : (link ? link.textContent.trim() : null),
        date: m ? `${m[1]}-${m[2]}-${m[3]}` : null,
        rating10: input && input.value ? (parseInt(input.value, 10) || null) : (rm ? parseInt(rm[1], 10) : null),
        rewatch: rewatch ? (rewatch.className.includes('icon-status-off') ? 0 : 1) : 0,
    };
})"""


class LetterboxdSession:
    """A logged-in browser session. Use as a context manager."""

    def __init__(self):
        self._cm = None
        self.page = None
        self.username = ""

    def __enter__(self):
        self._cm = Camoufox(headless=True)
        browser = self._cm.__enter__()
        try:
            self.page = browser.new_page()
            if not _login(self.page):
                # One more try: the first attempt sometimes races a consent overlay.
                time.sleep(3)
                if not _login(self.page):
                    raise RuntimeError("Letterboxd login failed")
            self.username = _resolve_username(self.page)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        logger.info(f"Signed in to Letterboxd as {self.username}")
        return self

    def __exit__(self, *exc):
        if self._cm:
            self._cm.__exit__(*exc)
            self._cm = None
        return False

    def read_diary(self, stop_before: str | None = None, max_pages: int = 1000) -> tuple[list[dict], bool]:
        """Scrape diary pages newest-first.

        Stops once a page's oldest entry is older than *stop_before* (YYYY-MM-DD).
        Returns (entries, complete) where complete means the whole diary was read.
        """
        entries: list[dict] = []
        for page_num in range(1, max_pages + 1):
            url = f"{BASE}/{self.username}/films/diary/page/{page_num}/"
            response = _goto(self.page, url)
            status = response.status if response else None
            # Anything but a real, signed-in diary page must abort: treating it as
            # "end of diary" would hide logged entries and cause duplicate uploads.
            if not status or status >= 400 or not _check_if_logged_in(self.page) or self.page.locator("#diary-table").count() == 0:
                raise LetterboxdError(f"Unexpected diary page {url} (HTTP {status}, title {self.page.title()!r})")
            raw = self.page.evaluate(_DIARY_JS)
            rows = [r for r in raw if r.get("viewing_id") and r.get("slug") and r.get("date")]
            if len(rows) != len(raw):
                raise LetterboxdError(f"Could not parse {len(raw) - len(rows)} of {len(raw)} rows on diary page {page_num}")
            entries.extend(rows)
            logger.info(f"Diary page {page_num}: {len(rows)} entries")
            if not rows or self.page.locator(".paginate-nextprev a.next").count() == 0:
                return entries, True
            if stop_before and min(r["date"] for r in rows) < stop_before:
                return entries, False
        return entries, False

    def resolve_slug(self, tmdb_id: str | None, imdb_id: str | None) -> str | None:
        """Map a TMDB/IMDb id to a Letterboxd film slug via Letterboxd's redirect endpoints.

        Returns None only when Letterboxd positively reports the ids as unknown
        (it stays on the /tmdb/ or /imdb/ page). Raises LetterboxdError otherwise.
        """
        for kind, ident in (("tmdb", tmdb_id), ("imdb", imdb_id)):
            if not ident:
                continue
            url = f"{BASE}/{kind}/{ident}/"
            try:
                response = _goto(self.page, url)
            except Exception as exc:
                raise LetterboxdError(f"Lookup {url} failed: {exc}") from exc
            m = re.search(r"letterboxd\.com/film/([^/]+)/", self.page.url)
            if m:
                return m.group(1)
            status = response.status if response else None
            if status in (200, 404) and f"/{kind}/" in self.page.url and _check_if_logged_in(self.page):
                continue  # unknown to Letterboxd; try the other id
            raise LetterboxdError(f"Unexpected lookup result for {url} (HTTP {status}, now at {self.page.url})")
        return None

    def upload_csv(self, csv_path: str) -> str:
        page = self.page
        _goto(page, f"{BASE}/import/")
        _handle_cookie_consent(page)
        for selector in ("#upload-imdb-import", "#diary-import-file", 'input[type="file"][name="file"]', 'input[type="file"]'):
            elem = page.locator(selector)
            if elem.count() > 0:
                elem.first.set_input_files(csv_path)
                break
        else:
            raise RuntimeError("Could not find the import file input")

        page.wait_for_selector("text=Matching complete", timeout=120000)
        for selector in ('a:has-text("Import")', 'button:has-text("Import")'):
            btn = page.locator(selector).first
            try:
                if btn.is_visible(timeout=3000):
                    btn.click()
                    break
            except Exception:
                continue
        else:
            raise RuntimeError("Could not find the Import button")

        for selector in ("text=Import complete", "text=imported", "#diary-importer-identifier p"):
            try:
                el = page.wait_for_selector(selector, timeout=120000)
                if el:
                    return el.inner_text().strip()
            except PlaywrightTimeout:
                continue
        return "Import submitted"
