"""Letterboxd CSV upload logic, extracted from main.py."""
import csv
import logging
import os
import time
from io import StringIO

from camoufox.sync_api import Camoufox
from playwright.sync_api import TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

LETTERBOXD_USERNAME = os.getenv("LETTERBOXD_USERNAME")
LETTERBOXD_PASSWORD = os.getenv("LETTERBOXD_PASSWORD")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))


def send_telegram_message(message):
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
    except Exception as exc:
        logger.error(f"Telegram send failed: {exc}")


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _handle_cookie_consent(page):
    consent_selectors = [
        ".fc-cta-consent",
        'button:has-text("Consent")',
        'button:has-text("Accept")',
        'button:has-text("I agree")',
    ]
    for selector in consent_selectors:
        try:
            btn = page.locator(selector)
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_load_state("networkidle", timeout=5000)
                return True
        except PlaywrightTimeout:
            continue
        except Exception:
            continue
    # Try iframes
    for frame in page.frames:
        try:
            btn = frame.locator(".fc-cta-consent, button:has-text('Consent')")
            if btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(1)
                return True
        except Exception:
            continue
    return False


def _check_if_logged_in(page):
    try:
        if page.locator("#field-username").is_visible(timeout=1000):
            return False
        if page.locator(".nav-account").is_visible(timeout=1000):
            return True
    except Exception:
        pass
    return False


def _login(page):
    logger.info("Logging in to Letterboxd...")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    if _check_if_logged_in(page):
        logger.info("Already logged in")
        return True

    page.wait_for_selector("#field-username", timeout=10000)

    for selector in ("#field-username", 'input[name="username"]'):
        try:
            f = page.locator(selector).first
            if f.is_visible(timeout=2000):
                f.fill(LETTERBOXD_USERNAME)
                break
        except Exception:
            continue

    for selector in ("#field-password", 'input[type="password"]'):
        try:
            f = page.locator(selector).first
            if f.is_visible(timeout=2000):
                f.fill(LETTERBOXD_PASSWORD)
                break
        except Exception:
            continue

    for selector in ('button:has-text("Sign In")', 'button[type="submit"]'):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2000):
                btn.click()
                break
        except Exception:
            continue

    time.sleep(5)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    time.sleep(3)

    if _check_if_logged_in(page):
        logger.info("Login successful")
        return True
    logger.error("Login failed")
    return False


def _upload_file(page, csv_file):
    for selector in (
        "#upload-imdb-import",
        "#diary-import-file",
        'input[type="file"][name="file"]',
        'input[type="file"]',
        'input[accept=".csv"]',
    ):
        try:
            elem = page.locator(selector)
            if elem.count() > 0:
                elem.first.set_input_files(csv_file)
                logger.info(f"File set using selector: {selector}")
                return True
        except Exception:
            continue
    raise Exception("Could not find file input element")


def _wait_for_matching(page, timeout=120000):
    for selector in (
        'text=Matching complete',
        '#diary-importer-identifier:has-text("Matching complete")',
    ):
        try:
            if page.wait_for_selector(selector, timeout=timeout):
                return True
        except PlaywrightTimeout:
            continue
    raise Exception("Matching did not complete within timeout")


def _click_import(page):
    for selector in ('a:has-text("Import")', 'button:has-text("Import")'):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=3000):
                btn.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                return True
        except Exception:
            continue
    raise Exception("Could not find import button")


def _wait_for_import_complete(page, timeout=120000):
    for selector in (
        'text=Import complete',
        'text=imported',
        "#diary-importer-identifier p",
    ):
        try:
            result = page.wait_for_selector(selector, timeout=timeout)
            if result:
                return result.inner_text()
        except PlaywrightTimeout:
            continue
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_csv(csv_file: str, retry_count: int = 0) -> bool:
    """Upload *csv_file* to Letterboxd. Returns True on success."""
    try:
        with Camoufox(headless=True) as browser:
            page = browser.new_page()
            page.goto("https://letterboxd.com/import", wait_until="networkidle", timeout=30000)
            _handle_cookie_consent(page)
            _login(page)
            time.sleep(3)
            _handle_cookie_consent(page)

            if "/import" not in page.url:
                page.goto("https://letterboxd.com/import", wait_until="networkidle", timeout=30000)
                time.sleep(2)
                _handle_cookie_consent(page)

            _upload_file(page, csv_file)
            _wait_for_matching(page, timeout=120000)
            _click_import(page)
            result = _wait_for_import_complete(page, timeout=120000)

            msg = f"Letterboxd import: {result}" if result else "Letterboxd import completed"
            logger.info(msg)
            send_telegram_message(msg)
            return True

    except PlaywrightTimeout as exc:
        logger.error(f"Timeout: {exc}")
    except Exception as exc:
        logger.error(f"Upload error: {exc}")

    if retry_count < MAX_RETRIES:
        logger.info(f"Retrying ({retry_count + 2}/{MAX_RETRIES + 1})...")
        time.sleep(5)
        return upload_csv(csv_file, retry_count + 1)

    send_telegram_message(f"Letterboxd export failed after {MAX_RETRIES + 1} attempts")
    return False


def build_csv_rows(items: list[dict]) -> str:
    """Serialize a list of movie dicts to a Letterboxd CSV string."""
    buf = StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["imdbID", "tmdbID", "Title", "Year", "Rating10", "WatchedDate", "Rewatch"],
    )
    writer.writeheader()
    writer.writerows(items)
    return buf.getvalue()
