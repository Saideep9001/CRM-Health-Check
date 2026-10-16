"""Health check worker. Run one or more of these next to the API when JOB_MODE=external:

    python -m app.worker      (from the backend folder, with the virtual environment's Python)

Each process runs WORKER_THREADS checks at a time and can be started on any machine that
reaches the database. Stop with Ctrl+C; checks it was running are picked up again by
another worker once their heartbeat times out.
"""
import logging
import signal
import threading

from .config import get_settings
from .db import init_db
from .engine import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(name)s: %(message)s")
log = logging.getLogger("aquarient.worker")


def main() -> None:
    settings = get_settings()
    init_db()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threads = jobs.start_threads("worker", stop)
    log.info("Worker ready: %d thread(s), polling every %.0fs. Press Ctrl+C to stop.", len(threads), settings.worker_poll_seconds)
    while not stop.wait(1):
        pass
    for t in threads:
        t.join(timeout=10)
    log.info("Worker stopped.")


if __name__ == "__main__":
    main()
