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


def test_a_restart_leaves_work_that_has_not_started_alone(db, monkeypatch):
    """A run still waiting in the queue at a restart starts afterwards; one that was running was cut off."""
    from agent.analyzer import agent
    from app.services.runs import runner
    monkeypatch.setattr(get_settings(), "jobs_in_worker", True)
    db["scoring_runs"].insert_many([{"_id": "s1", "status": "running"}, {"_id": "s2", "status": "running"}])
    db["runs"].insert_one({"_id": "c1", "status": "running"})
    jobs.start(agent.run_scoring, "s1")
    jobs.start(runner._execute, "c1", {})
    jobs.recover()
    assert db["scoring_runs"].find_one({"_id": "s1"})["status"] == "running"
    assert db["runs"].find_one({"_id": "c1"})["status"] == "running"
    cut = db["scoring_runs"].find_one({"_id": "s2"})
    assert cut["status"] == "terminated" and cut["error"] == "interrupted — found running at start-up"


def test_a_worker_stop_leaves_queued_work_alone(db, monkeypatch):
    from agent.analyzer import agent, engine
    from app.services.runs import runner
    monkeypatch.setattr(get_settings(), "jobs_in_worker", True)
    db["scoring_runs"].insert_many([{"_id": "s1", "status": "running"}, {"_id": "s2", "status": "running"}])
    db["runs"].insert_many([{"_id": "c1", "status": "running"}, {"_id": "c2", "status": "running"}])
    jobs.start(agent.run_scoring, "s1")
    jobs.start(runner._execute, "c1", {})
    keep = jobs.waiting()
    engine.shutdown(keep)
    runner.shutdown(keep)
    assert [r["status"] for r in db["scoring_runs"].find(sort=[("_id", 1)])] == ["running", "terminated"]
    assert [r["status"] for r in db["runs"].find(sort=[("_id", 1)])] == ["running", "terminated"]


def test_work_stopped_before_it_started_does_not_run(db, monkeypatch):
    """No model is even made: a run that isn't running when its job comes up ends at once, at no cost."""
    from agent.analyzer import agent
    from app.services.runs import runner

    def no_model(*a, **k):
        raise AssertionError("no model call for work that didn't start")
    monkeypatch.setattr(agent.LLM, "initialize", classmethod(no_model))
    monkeypatch.setattr(runner.LLM, "initialize", classmethod(no_model))
    db["scoring_runs"].insert_many([
        {"_id": "s1", "status": "terminated", "error": "interrupted — found running at start-up"},
        {"_id": "s2", "status": "terminating"}])
    db["runs"].insert_one({"_id": "c1", "status": "terminating"})
    agent.run_scoring("s1")
    agent.run_scoring("s2")
    runner._execute("c1", {})
    assert db["scoring_runs"].find_one({"_id": "s1"})["error"] == "interrupted — found running at start-up"
    s2 = db["scoring_runs"].find_one({"_id": "s2"})
    assert (s2["status"], s2["error"]) == ("terminated", "terminated by user")
    c1 = db["runs"].find_one({"_id": "c1"})
    assert (c1["status"], c1["error"]) == ("terminated", "terminated by user")
