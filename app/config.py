"""Static configuration from the environment.

Secrets and connection details come from env vars only. Tunable behaviour
(schedule, filters, ...) lives in the `settings` table and is editable in the
web UI; the env values below are only the initial defaults for those.
"""
import os

DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "plex-to-letterboxd.db")

PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")
# Browser-facing Plex address used for links in the UI (defaults to PLEX_URL)
PLEX_PUBLIC_URL = (os.getenv("PLEX_PUBLIC_URL") or PLEX_URL).rstrip("/")

LETTERBOXD_USERNAME = os.getenv("LETTERBOXD_USERNAME", "")
LETTERBOXD_PASSWORD = os.getenv("LETTERBOXD_PASSWORD", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "7477"))
STATIC_DIR = os.getenv("STATIC_DIR", os.path.join(os.path.dirname(__file__), "static"))
VERSION = os.getenv("APP_VERSION", "dev")
JOB_TIMEOUT_MINUTES = float(os.getenv("JOB_TIMEOUT_MINUTES", "60"))

# name -> (type, default). Types: int, bool, str.
SETTINGS_SCHEMA: dict[str, tuple[type, object]] = {
    "auto_sync": (bool, os.getenv("AUTO_SYNC", "true").lower() in ("1", "true", "yes")),
    "sync_interval_minutes": (int, int(os.getenv("SYNC_INTERVAL_MINUTES", "360"))),
    "plex_library": (str, os.getenv("PLEX_LIBRARY", "Films")),
    "plex_user": (str, os.getenv("PLEX_USER", "").strip()),
    "require_rating": (bool, True),
    "history_days": (int, 30),
    "max_age_days": (int, int(os.getenv("MAX_AGE_DAYS", "30"))),
    "max_attempts": (int, int(os.getenv("MAX_RETRIES", "3"))),
    "batch_size": (int, 50),
    "telegram_enabled": (bool, True),
}
