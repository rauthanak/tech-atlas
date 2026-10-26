"""Where background jobs run (plan 10, rule 2: heavy work apart from the web app).

Every job (a collection, an assessment run, Classify, Points of View, Check
again, Find evidence, Organize, linking names) starts through start(). Its
own record (the run, the job) is written first, as before; start() then
either runs it here in a thread (JOBS_IN_WORKER off: development and tests),
or writes one line in `jobs` for the worker container to pick up and returns
(JOBS_IN_WORKER on: Docker). The worker (app/worker.py) runs the same
function with the same arguments. Status, progress, Stop and the "already
running" checks all read the jobs' own records in the database, so they work
the same whichever process runs them.

Start-up recovery (a job found running died with the process that ran it) and
the background upkeep (stored answers, the Briefing's days) belong to the
process that runs the jobs: the API without a worker, else the worker. So a
restart or a deploy of the API never touches a running job."""

import importlib
import logging
import threading
import uuid

from pymongo import ReturnDocument

from app.services.db.mongo import get_collection
from app.services.timezone import now_utc
from app.settings import get_settings

log = logging.getLogger(__name__)


def in_worker() -> bool:
    return get_settings().jobs_in_worker


def start(target, *args) -> None:
    """Run target(*args) in the background: in the worker when there is one, else in a thread here."""
    name = f"{target.__module__}:{target.__qualname__}"
    if in_worker():
        get_collection("jobs").insert_one({"_id": uuid.uuid4().hex[:12], "target": name, "args": list(args),
                                           "status": "queued", "queued_at": now_utc()})
    else:
        threading.Thread(target=target, args=args, name=f"{target.__qualname__}-{args[0] if args else ''}",
                         daemon=True).start()


def later(target, *args) -> None:
    """Run target(*args) after the request that asks for it, for work that is safe to run again (re-linking
    pages, re-ranking the Briefing): in the worker when there is one, queued again if a restart cuts it off;
    without one (a small database), here and now."""
    if not in_worker():
        target(*args)
        return
    get_collection("jobs").insert_one({"_id": uuid.uuid4().hex[:12], "target": f"{target.__module__}:{target.__qualname__}",
                                       "args": list(args), "again": True, "status": "queued", "queued_at": now_utc()})


def take(worker: str) -> dict | None:
    """The oldest queued job, now this worker's (no two workers take the same one)."""
    return get_collection("jobs").find_one_and_update(
        {"status": "queued"}, {"$set": {"status": "running", "worker": worker, "started_at": now_utc()}},
        sort=[("queued_at", 1)], return_document=ReturnDocument.AFTER)


def run(job: dict) -> None:
    """Run a taken job to its end; its own record says how it went, this line only that it ran."""
    module, name = job["target"].split(":")
    status, error = "done", None
    try:
        getattr(importlib.import_module(module), name)(*job["args"])
    except Exception as exc:  # the job records its own failure; this keeps the worker going
        log.exception("job %s (%s) failed", job["_id"], job["target"])
        status, error = "failed", str(exc)
    get_collection("jobs").update_one({"_id": job["_id"]}, {"$set": {"status": status, "error": error,
                                                                     "finished_at": now_utc()}})


def waiting() -> list:
    """What each queued job is for (its first argument, a run's id): work that hasn't started yet."""
    return [j["args"][0] for j in get_collection("jobs").find({"status": "queued"}, {"args": 1}) if j.get("args")]


def recover() -> None:
    """At the start of the process that runs jobs: anything recorded as running
    died with the process before it, so each says so (and why). A run still
    waiting in the queue hasn't started: it's left to start."""
    from agent.analyzer import engine as scoring_engine
    from agent.classifier import classify
    from agent.find_evidence import job as find_evidence
    from agent.resolver import resolver
    from app.services.runs import store
    from app.services.signals import recheck
    keep = waiting()
    store.reconcile_stale_runs(keep)
    scoring_engine.reconcile_stale_scoring_runs(keep)
    recheck.reconcile_stale()
    classify.reconcile_stale()
    find_evidence.reconcile_stale()
    resolver.reconcile_stale()
    again = get_collection("jobs").update_many({"status": "running", "again": True}, {"$set": {"status": "queued"}})
    if again.modified_count:
        log.warning("jobs: %d cut off by a restart, queued again", again.modified_count)
    left = get_collection("jobs").update_many(
        {"status": "running"}, {"$set": {"status": "failed", "error": "the worker restarted while it ran",
                                         "finished_at": now_utc()}})
    if left.modified_count:
        log.warning("jobs: %d interrupted by a restart", left.modified_count)


def upkeep() -> None:
    """The background upkeep: any missing indexes first, then each technology's stored answers and the
    Briefing's days, which read through them (on a big database, reading without them scans every page)."""
    from app.services import briefing_days, tech_status
    from app.services.db import bootstrap

    def begin() -> None:
        bootstrap.ensure_indexes()
        tech_status.start()
        briefing_days.start()
    threading.Thread(target=begin, name="upkeep", daemon=True).start()


def shutdown() -> None:
    """The process that runs jobs is stopping: the jobs running in it end with it, and say so."""
    from agent.analyzer import engine as scoring_engine
    from app.services import briefing_days, tech_status
    from app.services.runs import runner
    tech_status.stop()
    briefing_days.stop()
    keep = waiting()  # runs still in the queue start when the worker is back
    runner.shutdown(keep)
    scoring_engine.shutdown(keep)
