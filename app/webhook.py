"""
Tautulli webhook receiver.

Tautulli → Notification Agent → Script/Webhook → POST /tautulli-hook

Configure Tautulli to call this server on "Watched" events. The webhook
pushes a structured item onto the Redis queue; the worker picks it up and
drives the Letterboxd import.

Expected Tautulli POST body (JSON, "Data" fields filled from parameters):
  {
    "event":           "watched",
    "media_type":      "movie",
    "title":           "{title}",
    "year":            "{year}",
    "imdb_id":         "{imdb_id}",
    "tmdb_id":         "{themoviedb_id}",
    "rating":          "{rating}",     // user rating, may be empty
    "watched_date":    "{date}"        // YYYY-MM-DD from Tautulli
  }

Only "movie" events for the configured Plex user are enqueued.
"""
import json
import logging
import os

import redis
from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = os.getenv("QUEUE_KEY", "letterboxd:queue")
PLEX_USER = os.getenv("PLEX_USER", "").strip()   # filter by Plex username if set

app = FastAPI(title="plex-to-letterboxd webhook")
rdb = redis.from_url(REDIS_URL, decode_responses=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tautulli-hook")
async def tautulli_hook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info(f"Received hook: {payload}")

    # Only process movie watch events
    if payload.get("media_type") != "movie":
        return {"enqueued": False, "reason": "not a movie"}

    if payload.get("event") not in ("watched", ""):
        return {"enqueued": False, "reason": "not a watched event"}

    # If a user filter is configured, check it
    hook_user = (payload.get("plex_user") or payload.get("user") or "").strip()
    if PLEX_USER and hook_user and hook_user != PLEX_USER:
        logger.info(f"Ignoring event for user '{hook_user}' (expected '{PLEX_USER}')")
        return {"enqueued": False, "reason": "wrong user"}

    item = {
        "Title":        payload.get("title", ""),
        "Year":         str(payload.get("year", "")),
        "imdbID":       (payload.get("imdb_id") or "").strip(),
        "tmdbID":       str(payload.get("tmdb_id") or "").strip(),
        "Rating10":     str(payload.get("rating") or "").strip(),
        "WatchedDate":  (payload.get("watched_date") or "").strip(),
        "Rewatch":      str(payload.get("rewatch", "false")).lower(),
    }

    if not item["imdbID"] and not item["tmdbID"]:
        logger.warning(f"No IMDB/TMDB id for '{item['Title']}', skipping")
        return {"enqueued": False, "reason": "no identifier"}

    if not item["Rating10"]:
        logger.info(f"No rating for '{item['Title']}', skipping")
        return {"enqueued": False, "reason": "no rating"}

    rdb.rpush(QUEUE_KEY, json.dumps(item))
    logger.info(f"Enqueued: {item['Title']} ({item['Year']})")
    return {"enqueued": True, "item": item}
