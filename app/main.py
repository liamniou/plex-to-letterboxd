"""
One-shot manual export: reads Plex history → builds CSV → uploads to Letterboxd.
Run with: docker compose run --rm plex-to-letterboxd
"""
import logging
import os
import sys

from letterboxd import send_telegram_message, upload_csv
from plex_stats import main as generate_csv

PLEX_URL     = os.getenv("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN   = os.getenv("PLEX_TOKEN")
PLEX_USER    = os.getenv("PLEX_USER", "").strip()
PLEX_LIBRARY = os.getenv("PLEX_LIBRARY", "Films")
CSV_LIMIT    = int(os.getenv("CSV_LIMIT", 20))
CSV_FILE     = os.getenv("CSV_FILE", "/csv/file.csv")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting Plex to Letterboxd export...")

    csv_generated = generate_csv(PLEX_URL, PLEX_TOKEN, PLEX_USER, PLEX_LIBRARY, CSV_LIMIT, CSV_FILE)
    if not csv_generated:
        logger.error("Failed to generate CSV from Plex")
        send_telegram_message("Failed to generate CSV from Plex")
        return 1

    logger.info(f"CSV generated successfully at {CSV_FILE}")

    csv_path = CSV_FILE if os.path.isabs(CSV_FILE) else os.path.join(os.path.dirname(__file__), CSV_FILE)
    success = upload_csv(csv_path)

    if success:
        logger.info("Export completed successfully!")
        return 0
    else:
        logger.error("Export failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
