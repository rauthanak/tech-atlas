"""Plan 10, rule 2: with JOBS_IN_WORKER on, the API queues a job and returns;
the worker takes each job once and runs the same function with the same
arguments; a failed job is recorded and the worker goes on; at its start the
worker marks what was running as interrupted. Off, a job runs in a thread."""

import threading

from app.services import jobs
from app.settings import get_settings

RAN: list = []


def record(*args) -> None:
    RAN.append(args)


def explode(*args) -> None:
    raise ValueError("no luck")


def test_queued_in_worker_mode_taken_once_and_run(db, monkeypatch):
    RAN.clear()
    monkeypatch.setattr(get_settings(), "jobs_in_worker", True)
    jobs.start(record, "r1", {"pages": 3})
    job = db["jobs"].find_one()
    assert job["status"] == "queued" and job["target"] == "test_jobs:record" and RAN == []   # nothing ran in the API
    taken = jobs.take("w1")
    assert taken["_id"] == job["_id"] and jobs.take("w2") is None                           # one worker each
    jobs.run(taken)
    assert RAN == [("r1", {"pages": 3})] and db["jobs"].find_one()["status"] == "done"


def test_a_failed_job_is_recorded_and_a_restart_says_what_it_cut_off(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "jobs_in_worker", True)
    jobs.start(explode, "r2")
    jobs.run(jobs.take("w1"))
    failed = db["jobs"].find_one()
    assert failed["status"] == "failed" and failed["error"] == "no luck"
    db["jobs"].insert_one({"_id": "cut", "target": "test_jobs:record", "args": [], "status": "running"})
    db["runs"].insert_one({"_id": "c1", "status": "running"})
    db["resolves"].insert_one({"_id": "o1", "status": "running"})
    jobs.recover()
    assert db["jobs"].find_one({"_id": "cut"})["status"] == "failed"
    assert db["runs"].find_one({"_id": "c1"})["status"] == "terminated"
    assert db["resolves"].find_one({"_id": "o1"})["status"] == "failed"   # an Organize no longer blocks the next


def test_without_a_worker_it_runs_here(db, monkeypatch):
    RAN.clear()
    monkeypatch.setattr(get_settings(), "jobs_in_worker", False)
    jobs.start(record, "r3")
    for t in threading.enumerate():
        if t.name == "record-r3":
            t.join(5)
    assert RAN == [("r3",)] and db["jobs"].count_documents({}) == 0


def test_work_safe_to_run_again_is_queued_again_after_a_restart(db, monkeypatch):
    """jobs.later: re-linking pages after an edit, re-ranking the Briefing. Without a worker it runs at once."""
    RAN.clear()
    jobs.later(record, ["quic"])
    assert RAN == [(["quic"],)] and db["jobs"].count_documents({}) == 0
    monkeypatch.setattr(get_settings(), "jobs_in_worker", True)
    jobs.later(record, ["quic"])
    jobs.take("w1")                                            # the worker took it, then restarted
    jobs.start(record, "a collection")
    jobs.take("w1")
    jobs.recover()
    assert db["jobs"].find_one({"again": True})["status"] == "queued"        # done again by the next worker
    assert db["jobs"].find_one({"again": {"$exists": False}})["status"] == "failed"
