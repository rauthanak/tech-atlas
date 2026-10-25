"""The worker: runs the background jobs the API queues (services/jobs), apart
from the web app, so a big collection never slows a screen and a deploy of
the API never stops a job.

    python -m app.worker        (the `worker` container, with JOBS_IN_WORKER=true)

Each job runs in its own thread, as it did inside the API, so a collection,
its Classify and an assessment run can go on side by side; the jobs' own
"already running" checks decide what may overlap. Stopping the worker (a
deploy of it) ends the jobs it runs, and each says so."""

import logging
import signal
import socket
import threading
import time

from app.services import jobs
from app.services.db import bootstrap, upgrade_pages
from app.services.db.mongo import ping

log = logging.getLogger("app.worker")
POLL_S = 1.0  # how often it looks for a new job
_stop = threading.Event()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ping()                         # the database is up (the worker restarts until it is)
    bootstrap.ensure_database()    # its collections (upkeep builds missing indexes); the seeding data is the API's to load, never the worker's
    while upgrade_pages.pending():  # the API upgrades older page records once, at its start: wait for it
        log.info("waiting for the API to upgrade the page records")
        time.sleep(60)
    jobs.recover()
    jobs.upkeep()
    name = f"{socket.gethostname()}:{time.time():.0f}"
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    log.info("worker %s ready", name)
    while not _stop.is_set():
        job = jobs.take(name)
        if job is None:
            _stop.wait(POLL_S)
            continue
        log.info("job %s: %s", job["_id"], job["target"])
        threading.Thread(target=jobs.run, args=(job,), name=f"job-{job['_id']}", daemon=True).start()
    jobs.shutdown()
    log.info("worker %s stopped", name)


if __name__ == "__main__":
    main()
