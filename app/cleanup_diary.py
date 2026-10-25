"""
One-off maintenance: clean up wrongly-imported Letterboxd diary entries.

The exporter (before it was fixed) pushed movies that were not finished in Plex
and/or had no user rating, and repeated CSV uploads created duplicate diary
entries. This script logs in and deletes:

  1. Every diary entry with **no rating** (Letterboxd tags the row
     `-has-no-rating`; the owner's own diary shows an editable rating slider so
     the public `rated-N` class is absent).
  2. **Duplicate** entries — the same film logged on the same date more than
     once. One copy is kept (a rated copy is preferred); the rest are removed.

Usage (inside the container):
    python cleanup_diary.py            # dry-run: report what would be deleted
    python cleanup_diary.py --delete   # actually delete

Reliable delete recipe (verified): open a row's edit modal by clicking the
actions button *while waiting for the `/viewing/<id>/json/` response*; the
`#diary-entry-delete-button` enables ~0.5s after that JSON loads. Clicking it
raises a confirm() dialog which the page-level handler auto-accepts.
"""
import argparse
import logging
import sys
import time
from collections import defaultdict

from camoufox.sync_api import Camoufox
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from letterboxd import _handle_cookie_consent, _login, send_telegram_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cleanup_diary")

USERNAME = ""


def _goto(page, url: str, attempts: int = 4):
    """Navigate to *url*, retrying on transient timeouts."""
    last_exc = None
    for i in range(attempts):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return
        except PlaywrightTimeout as exc:
            last_exc = exc
            logger.warning(f"Timeout loading {url} (attempt {i + 1}/{attempts}); retrying")
            time.sleep(3)
    raise last_exc


def _resolve_username(page) -> str:
    """Return the logged-in member's profile slug (e.g. 'Lestar').

    The signed-in account menu contains a "Network" link of the form
    /<username>/following/ which unambiguously identifies the logged-in member
    (the header avatar is unreliable — it can point at a featured member).
    """
    slug = page.evaluate(
        r"""() => {
            const a = [...document.querySelectorAll('a[href]')]
              .map(x => x.getAttribute('href') || '')
              .find(h => /^\/[^\/]+\/following\/$/.test(h));
            return a ? a.split('/')[1] : '';
        }"""
    )
    if slug:
        return slug
    raise RuntimeError("Could not determine Letterboxd username after login")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def _collect_entries(page) -> list[dict]:
    """Walk the whole diary and return one dict per entry."""
    entries: list[dict] = []
    page_num = 1
    while True:
        _goto(page, f"https://letterboxd.com/{USERNAME}/films/diary/page/{page_num}/")
        _handle_cookie_consent(page)
        data = page.evaluate(
            """() => [...document.querySelectorAll('tr.diary-entry-row')].map(tr => {
                const idEl = tr.querySelector('[data-viewing-id]');
                const filmLink = tr.querySelector("a[href*='/film/']");
                const dayLink = tr.querySelector("td.col-daydate a") || tr.querySelector("a[href*='/diary/for/'], a[href*='/diary/films/for/']");
                return {
                    vid: idEl ? idEl.getAttribute('data-viewing-id') : null,
                    slug: filmLink ? (filmLink.getAttribute('href')||'').replace(/.*\\/film\\//,'').replace(/\\/.*/,'') : null,
                    title: filmLink ? filmLink.textContent.trim() : null,
                    day: dayLink ? dayLink.getAttribute('href') : null,
                    noRating: tr.className.includes('-has-no-rating'),
                };
            })"""
        )
        if not data:
            break
        entries.extend(data)
        logger.info(f"Scanned diary page {page_num} ({len(data)} entries)")
        if page.locator(".paginate-nextprev .next").count() == 0:
            break
        page_num += 1
    return entries


def _compute_targets(entries: list[dict]):
    """Return (targets, unrated_vids, dup_vids).

    targets = vids to delete = all unrated entries plus every duplicate copy
    beyond the one we keep. For a duplicate group (same film + same date) we
    keep a rated copy when one exists, otherwise the group is all-unrated and
    every copy is removed via the unrated set anyway.
    """
    unrated = {e["vid"] for e in entries if e["noRating"] and e["vid"]}

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in entries:
        if e["vid"] and e["slug"] and e["day"]:
            groups[(e["slug"], e["day"])].append(e)

    dup: set[str] = set()
    for items in groups.values():
        if len(items) <= 1:
            continue
        rated = [e for e in items if not e["noRating"]]
        keep = rated[0]["vid"] if rated else items[0]["vid"]
        for e in items:
            if e["vid"] != keep:
                dup.add(e["vid"])

    return (unrated | dup), unrated, dup


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def _row_viewing_id(row) -> str:
    try:
        el = row.locator("[data-viewing-id]").first
        if el.count() > 0:
            return el.get_attribute("data-viewing-id") or ""
    except Exception:
        pass
    return ""


def _row_title(row) -> str:
    try:
        el = row.locator("a[href*='/film/']").first
        if el.count() > 0:
            return (el.inner_text(timeout=1000) or "").strip()
    except Exception:
        pass
    return "<unknown>"


def _delete_row(page, row, title: str) -> bool:
    """Delete a single diary entry using the verified modal recipe."""
    logger.info(f"Deleting: {title}")
    # Open the edit modal; the delete button only enables after the viewing
    # JSON for this entry has loaded, so gate the click on that response.
    try:
        with page.expect_response(
            lambda r: "/viewing/" in r.url and "/json/" in r.url, timeout=20000
        ):
            row.locator(".col-actions button").first.click(timeout=10000)
    except Exception as exc:
        logger.error(f"Could not open modal for {title}: {exc}")
        return False

    try:
        page.wait_for_function(
            "() => { const b = document.querySelector('#diary-entry-delete-button');"
            " return b && !b.disabled; }",
            timeout=15000,
        )
    except PlaywrightTimeout:
        logger.error(f"Delete button did not enable for {title}")
        return False

    try:
        # Click triggers a confirm() dialog handled by the page dialog listener.
        page.locator("#diary-entry-delete-button").first.click(timeout=8000, no_wait_after=True)
    except Exception as exc:
        logger.error(f"Delete click failed for {title}: {exc}")
        return False

    time.sleep(2.5)  # let the delete settle before the page is reloaded
    return True


def _delete_targets(page, targets: set[str]) -> int:
    """Delete every diary entry whose viewing id is in *targets*.

    Deleting an entry shifts later entries forward one slot, so after each
    delete we re-fetch the same page; we only advance once a page holds no
    remaining targets. Entries that repeatedly fail are skipped so the loop
    cannot get stuck.
    """
    page.on("dialog", lambda d: d.accept())
    total = len(targets)
    remaining = set(targets)
    fail_counts: dict[str, int] = {}
    deleted = 0
    page_num = 1

    while remaining:
        _goto(page, f"https://letterboxd.com/{USERNAME}/films/diary/page/{page_num}/")
        _handle_cookie_consent(page)
        try:
            page.wait_for_selector("tr.diary-entry-row .col-actions button", timeout=10000)
        except PlaywrightTimeout:
            pass

        rows = page.locator("tr.diary-entry-row")
        count = rows.count()
        if count == 0:
            break

        target_row = None
        target_vid = ""
        target_title = ""
        for i in range(count):
            row = rows.nth(i)
            vid = _row_viewing_id(row)
            if vid and vid in remaining:
                target_row = row
                target_vid = vid
                target_title = _row_title(row)
                break

        if target_row is None:
            # Nothing to delete on this page; advance if a next page exists.
            if page.locator(".paginate-nextprev .next").count() == 0:
                break
            page_num += 1
            continue

        if _delete_row(page, target_row, target_title):
            deleted += 1
            remaining.discard(target_vid)
            logger.info(f"Progress: {deleted}/{total} deleted, {len(remaining)} left")
        else:
            fail_counts[target_vid] = fail_counts.get(target_vid, 0) + 1
            if fail_counts[target_vid] >= 3:
                logger.error(f"Skipping '{target_title}' after 3 failed attempts")
                remaining.discard(target_vid)
        # Re-fetch the same page (entries shifted after a delete).

    return deleted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="actually delete entries")
    args = parser.parse_args()

    global USERNAME
    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        _goto(page, "https://letterboxd.com/sign-in/")
        _handle_cookie_consent(page)
        if not _login(page):
            logger.error("Login failed")
            return 1
        time.sleep(2)
        _goto(page, "https://letterboxd.com/")
        _handle_cookie_consent(page)
        USERNAME = _resolve_username(page)
        logger.info(f"Logged in as '{USERNAME}'")

        entries = _collect_entries(page)
        targets, unrated, dup = _compute_targets(entries)
        logger.info(
            f"Diary: {len(entries)} entries | unrated: {len(unrated)} | "
            f"duplicate extras: {len(dup)} | total to delete: {len(targets)}"
        )

        if not args.delete:
            logger.info("Dry-run only. Re-run with --delete to remove them.")
            return 0

        if not targets:
            logger.info("Nothing to delete.")
            return 0

        deleted = _delete_targets(page, targets)
        msg = f"Letterboxd cleanup: deleted {deleted} entrie(s) (unrated + duplicates)"
        logger.info(msg)
        send_telegram_message(msg)
        return 0


if __name__ == "__main__":
    sys.exit(main())
