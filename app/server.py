"""HTTP API + static web UI."""
import faulthandler
import logging
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import jobs
import plex_source

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("server")
# `docker kill -s USR1 <container>` dumps all thread stacks to the log.
faulthandler.register(signal.SIGUSR1, all_threads=True)

runner = jobs.Runner()
scheduler = jobs.Scheduler(runner)
POSTER_DIR = os.path.join(config.DATA_DIR, "posters")


@asynccontextmanager
async def lifespan(_app):
    db.connect(recover=True)
    os.makedirs(POSTER_DIR, exist_ok=True)
    runner.start()
    scheduler.start()
    logger.info(f"plex-to-letterboxd {config.VERSION} listening on {config.HOST}:{config.PORT}")
    yield


app = FastAPI(title="plex-to-letterboxd", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/status")
def status():
    last_sync = db.query_one("SELECT * FROM runs WHERE kind='sync' ORDER BY id DESC LIMIT 1")
    settings = db.get_settings()
    return {
        "version": config.VERSION,
        "runner": runner.status(),
        "next_sync_at": jobs.Scheduler.next_run_at(),
        "baseline_done": bool(db.get_state("baseline_done", False)),
        "baseline_at": db.get_state("baseline_at"),
        "diary_read_at": db.get_state("diary_read_at"),
        "counts": db.status_counts(),
        "last_sync": db._decode_run(last_sync) if last_sync else None,
        "recent_synced": db.query(f"{db.WATCH_SELECT} WHERE w.status='synced' ORDER BY w.synced_at DESC, w.id DESC LIMIT 12"),
        "config": {
            "plex_url": config.PLEX_PUBLIC_URL,
            "plex_machine_id": plex_source.machine_id(),
            "plex_library": settings["plex_library"],
            "plex_configured": bool(config.PLEX_TOKEN),
            "letterboxd_configured": bool(config.LETTERBOXD_USERNAME and config.LETTERBOXD_PASSWORD),
            "telegram_configured": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
        },
    }


@app.get("/api/watches")
def watches(status: str | None = None, q: str | None = None, needs_rating: bool | None = None, page: int = 1, page_size: int = 50):
    page_size = max(1, min(page_size, 200))
    items, total = db.list_watches(status or None, q or None, page_size, (max(page, 1) - 1) * page_size, needs_rating)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


class WatchAction(BaseModel):
    ids: list[int]
    action: str


ACTIONS = {
    "queue": ("pending", {"attempts": 0, "last_error": None, "note": "Queued manually", "manual_skip": 0}),
    # e.g. someone else watched it; the next play of the film is picked up again
    "skip": ("skipped", {"note": "Skipped manually", "manual_skip": 1}),
    "mark_synced": ("synced", {"note": "Marked as synced manually", "last_error": None, "manual_skip": 0}),
}


@app.post("/api/watches/action")
def watch_action(body: WatchAction):
    if body.action not in ACTIONS:
        raise HTTPException(400, f"Unknown action {body.action}")
    status_, fields = ACTIONS[body.action]
    extra = {"synced_at": db.now_iso()} if status_ == "synced" else {}
    updated = 0
    for wid in body.ids:
        if db.get_watch(wid):
            db.set_watch_status(wid, status_, **fields, **extra)
            updated += 1
    return {"updated": updated}


@app.post("/api/jobs/{kind}")
def start_job(kind: str):
    if kind not in ("scan", "sync", "reconcile"):
        raise HTTPException(404, "Unknown job")
    return {"enqueued": runner.enqueue(kind, "manual"), "runner": runner.status()}


@app.get("/api/runs")
def runs(limit: int = 50, offset: int = 0, kind: str | None = None):
    if kind:
        rows = db.query("SELECT * FROM runs WHERE kind=? ORDER BY id DESC LIMIT ? OFFSET ?", (kind, limit, offset))
        return {"items": [db._decode_run(r) for r in rows]}
    return {"items": db.list_runs(limit, offset)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int, after_id: int = 0):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {"run": run, "logs": db.get_run_logs(run_id, after_id)}


@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.put("/api/settings")
def put_settings(values: dict):
    before = db.get_settings()
    try:
        after = db.update_settings(values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    if after["sync_interval_minutes"] != before["sync_interval_minutes"] or (after["auto_sync"] and not before["auto_sync"]):
        jobs.reschedule()
    return after


@app.get("/api/poster/{rating_key}")
def poster(rating_key: int):
    path = os.path.join(POSTER_DIR, f"{rating_key}.jpg")
    if not os.path.exists(path):
        movie = db.query_one("SELECT thumb FROM movies WHERE rating_key=?", (rating_key,))
        if not movie or not movie["thumb"]:
            raise HTTPException(404)
        try:
            data, _ = plex_source.fetch_thumb(movie["thumb"])
        except Exception:
            raise HTTPException(502, "Could not fetch poster from Plex")
        with open(path, "wb") as fh:
            fh.write(data)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


@app.post("/api/webhook/tautulli")
@app.post("/tautulli-hook")
async def tautulli_hook(request: Request):
    """Tautulli 'Watched' notification -> sync soon. Body is optional JSON with media_type."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if payload.get("media_type") not in (None, "", "movie"):
        return {"enqueued": False, "reason": "not a movie"}
    return {"enqueued": runner.enqueue("sync", "webhook")}


# --- SPA -------------------------------------------------------------------
if os.path.isdir(os.path.join(config.STATIC_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(config.STATIC_DIR, "assets")), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    candidate = os.path.join(config.STATIC_DIR, path)
    if path and os.path.isfile(candidate) and os.path.realpath(candidate).startswith(os.path.realpath(config.STATIC_DIR)):
        return FileResponse(candidate)
    index = os.path.join(config.STATIC_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return Response("Web UI not built", status_code=404)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
