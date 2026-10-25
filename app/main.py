"""CLI: run a job once without the web server, e.g. `python main.py sync`.

Uses the same database as the service, so state stays consistent. Do not run
while the service is executing a job (both would drive the same account).
"""
import argparse
import logging
import sys

import db
from sync import JOBS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", default="sync", choices=sorted(JOBS))
    parser.add_argument("--force", action="store_true", help="run even if another run is marked as running")
    args = parser.parse_args()
    db.connect()
    busy = db.query_one("SELECT id, kind FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1")
    if busy and not args.force:
        logging.error(f"Run #{busy['id']} ({busy['kind']}) is in progress; refusing to start (use --force to override)")
        return 2
    run_id = db.create_run(args.job, "cli")
    try:
        summary = JOBS[args.job](db.get_settings(), run_id)
    except Exception as exc:
        logging.exception(f"{args.job} failed")
        db.finish_run(run_id, "failed", error=str(exc))
        return 1
    db.finish_run(run_id, "success", summary)
    logging.info(f"Summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
