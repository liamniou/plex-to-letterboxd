"""Single-worker job queue plus the interval scheduler.

Jobs run one at a time (they share one Letterboxd account and a heavy browser).
Each job runs in its own process so a hung browser or network call can
be killed after JOB_TIMEOUT_MINUTES without taking the service down, and every
run is recorded in the database together with its log lines.
"""
import logging
import multiprocessing
import os
import queue
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

import config
import db
from letterboxd import send_telegram_message
from sync import JOBS

logger = logging.getLogger("jobs")


class _RunLogHandler(logging.Handler):
    """Copies every log record of a job process into run_logs."""

    def __init__(self, run_id: int):
        super().__init__(level=logging.INFO)
        self.run_id = run_id

    def emit(self, record):
        try:
            db.add_log(self.run_id, record.levelname, record.getMessage())
        except Exception:
            pass


def _child(kind: str, run_id: int) -> None:
    """Entry point of a job process."""
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.connect()
    logging.getLogger().addHandler(_RunLogHandler(run_id))
    log = logging.getLogger("jobs")
    log.info(f"Starting {kind}")
    try:
        summary = JOBS[kind](db.get_settings(), run_id)
    except Exception as exc:
        log.exception(f"{kind} failed: {exc}")
        db.finish_run(run_id, "failed", error=str(exc))
        if db.get_settings()["telegram_enabled"] and kind != "scan":
            send_telegram_message(f"plex-to-letterboxd {kind} failed: {exc}")
        return
    log.info(f"Finished {kind}")
    db.finish_run(run_id, "success", summary)


def _process_tree(root: int) -> list[int]:
    """root plus all descendants (the browser runs in its own process group, so killpg is not enough)."""
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    tree, stack = [], [root]
    while stack:
        pid = stack.pop()
        tree.append(pid)
        stack.extend(children.get(pid, []))
    return tree


def _kill_tree(root: int) -> None:
    for pid in reversed(_process_tree(root)):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class Runner:
    def __init__(self):
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._queued: list[dict] = []
        self._lock = threading.Lock()
        self.current: dict | None = None
        self._ctx = multiprocessing.get_context("spawn")
        self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)

    def start(self):
        self._thread.start()

    def enqueue(self, kind: str, trigger: str) -> bool:
        if kind not in JOBS:
            raise ValueError(f"Unknown job {kind}")
        with self._lock:
            if any(q["kind"] == kind for q in self._queued):
                return False
            self._queued.append({"kind": kind, "trigger": trigger, "queued_at": db.now_iso()})
        self._queue.put((kind, trigger))
        return True

    def status(self) -> dict:
        with self._lock:
            return {"current": self.current, "queued": list(self._queued)}

    def _loop(self):
        while True:
            kind, trigger = self._queue.get()
            with self._lock:
                self._queued = [q for q in self._queued if q["kind"] != kind]
            run_id = db.create_run(kind, trigger)
            self.current = {"kind": kind, "trigger": trigger, "run_id": run_id, "started_at": db.now_iso()}
            logger.info(f"Run #{run_id}: {kind} (trigger: {trigger})")
            try:
                self._execute(kind, run_id)
            except Exception as exc:
                logger.exception(f"Run #{run_id} could not be executed")
                db.finish_run(run_id, "failed", error=f"Runner error: {exc}")
            finally:
                self.current = None
                db.prune_runs()

    def _execute(self, kind: str, run_id: int) -> None:
        proc = self._ctx.Process(target=_child, args=(kind, run_id), name=f"job-{kind}-{run_id}", daemon=False)
        proc.start()
        proc.join(config.JOB_TIMEOUT_MINUTES * 60)
        if proc.is_alive():
            logger.error(f"Run #{run_id} exceeded {config.JOB_TIMEOUT_MINUTES} min; killing it")
            _kill_tree(proc.pid)
            proc.join(10)
            db.add_log(run_id, "ERROR", f"Killed after exceeding the {config.JOB_TIMEOUT_MINUTES} minute timeout")
            db.finish_run(run_id, "failed", error=f"Timed out after {config.JOB_TIMEOUT_MINUTES} min")
            return
        run = db.get_run(run_id)
        if run and run["status"] == "running":
            # The process died without recording a result (crash/OOM).
            db.finish_run(run_id, "failed", error=f"Job process exited unexpectedly (code {proc.exitcode})")



class Scheduler:
    """Enqueues a sync every `sync_interval_minutes` while auto_sync is on."""

    def __init__(self, runner: Runner, tick: int = 20):
        self.runner = runner
        self.tick = tick
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)

    def start(self):
        self._thread.start()

    @staticmethod
    def next_run_at() -> str | None:
        settings = db.get_settings()
        if not settings["auto_sync"] or not settings["sync_interval_minutes"]:
            return None
        return db.get_state("next_sync_at")

    def _loop(self):
        while True:
            try:
                settings = db.get_settings()
                interval = settings["sync_interval_minutes"]
                if settings["auto_sync"] and interval:
                    now = datetime.now(timezone.utc)
                    nxt = db.get_state("next_sync_at")
                    if nxt is None or now >= datetime.fromisoformat(nxt):
                        self.runner.enqueue("sync", "schedule" if nxt else "startup")
                        db.set_state("next_sync_at", (now + timedelta(minutes=interval)).isoformat(timespec="seconds"))
            except Exception as exc:
                logger.error(f"Scheduler error: {exc}")
            time.sleep(self.tick)


def reschedule() -> None:
    """Recompute the next run after the interval changed."""
    settings = db.get_settings()
    last = db.query_one("SELECT started_at FROM runs WHERE kind='sync' ORDER BY id DESC LIMIT 1")
    base = datetime.fromisoformat(last["started_at"]) if last else datetime.now(timezone.utc)
    nxt = max(base + timedelta(minutes=settings["sync_interval_minutes"]), datetime.now(timezone.utc) + timedelta(minutes=1))
    db.set_state("next_sync_at", nxt.isoformat(timespec="seconds"))
