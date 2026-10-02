"""
Redis queue worker.

Polls the Redis list for new items pushed by the webhook. When items are
present it batches them into a single CSV upload to Letterboxd.

Flow:
  1. BLPOP on the queue (blocks until an item arrives — immediate response).
  2. After the first item arrives, drain any further items that have
     accumulated (up to BATCH_SIZE) without blocking.
  3. Build a CSV from the batch, write it to disk, then call upload_csv().
  4. On success the CSV is removed. On failure the items are re-queued
     (prepended so order is preserved) and the worker sleeps RETRY_DELAY
     seconds before the next attempt.
"""
import json
import logging
import os
import tempfile
import time

import redis

from letterboxd import build_csv_rows, upload_csv, send_telegram_message

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

REDIS_URL   = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY   = os.getenv("QUEUE_KEY", "letterboxd:queue")
BATCH_SIZE  = int(os.getenv("BATCH_SIZE", 50))   # max items per upload pass
BLPOP_TIMEOUT = int(os.getenv("BLPOP_TIMEOUT", 30))  # seconds to wait for item
RETRY_DELAY = int(os.getenv("RETRY_DELAY", 60))  # seconds between retries on failure

rdb = redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_keepalive=True,
    health_check_interval=30,
)


def drain(first_raw: str) -> list[dict]:
    """Return a batch starting with *first_raw* plus whatever else is queued."""
    items = [json.loads(first_raw)]
    for _ in range(BATCH_SIZE - 1):
        raw = rdb.lpop(QUEUE_KEY)
        if raw is None:
            break
        items.append(json.loads(raw))
    return items


def process(items: list[dict]) -> bool:
    csv_text = build_csv_rows(items)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", prefix="lb_", delete=False
    ) as fh:
        fh.write(csv_text)
        tmp_path = fh.name

    logger.info(f"Processing {len(items)} item(s) from queue → {tmp_path}")
    ok = upload_csv(tmp_path)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    return ok


def re_enqueue(items: list[dict]):
    """Push items back to the front of the queue in original order."""
    for item in reversed(items):
        rdb.lpush(QUEUE_KEY, json.dumps(item))
    logger.info(f"Re-enqueued {len(items)} item(s) for retry")


def run():
    logger.info(f"Worker started. Watching queue '{QUEUE_KEY}' on {REDIS_URL}")
    while True:
        try:
            result = rdb.blpop(QUEUE_KEY, timeout=BLPOP_TIMEOUT)
        except redis.exceptions.ConnectionError as e:
            logger.warning("Redis connection lost (%s). Reconnecting in 5 s…", e)
            time.sleep(5)
            continue
        if result is None:
            continue  # timeout — loop back

        _, first_raw = result
        items = drain(first_raw)
        logger.info(f"Dequeued {len(items)} item(s): {[i['Title'] for i in items]}")

        ok = process(items)
        if not ok:
            logger.error("Upload failed — re-enqueueing and sleeping")
            re_enqueue(items)
            time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    run()
