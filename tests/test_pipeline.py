"""The pipeline summary: every step's state in one call."""

from fastapi.testclient import TestClient

from app.main import app
from factories import assessment, at, page, run, tech

client = TestClient(app)  # no lifespan: nothing is seeded


def test_the_latest_collection_counts_unfinished_sources_and_errors(db):
    db["runs"].insert_one({
        "_id": "r1", "status": "completed", "run_start_date_time": "2026-10-01T00:00:00+00:00",
        "totals": {"sources": 4},
        "sources": [{"source_id": "a", "incomplete": True, "error": None},
                    {"source_id": "b", "incomplete": False,
                     "error": "not configured: set CONTACT_EMAIL in .env"},
                    {"source_id": "c", "incomplete": False, "error": "run cancelled"},  # not a problem
                    {"source_id": "d"}]})
    collect = client.get("/api/pipeline").json()["collect"]
    assert collect["incomplete"] == 1 and collect["errors"] == 1


def test_for_analyst_lists_waiting_work_in_process_order(db):
    db["measures"].insert_one({"_id": "m"})
    db["fabrics"].insert_one({"_id": "cloud", "enabled": True})  # 2 + 1 measure x 1 fabric = 3 calls each
    db["documents"].insert_many([{"_id": f"s{i}", "end_url": f"s{i}", "is_stub": False,
                                  "extracted_text": "t", "signals_hash": None, "scraped_at": at(1)}
                                 for i in range(2)])                  # not yet checked
    tech(db, "halt", "halt tech")
    run(db, "r9", 9, status="terminated", techs=("halt",))             # stopped before scoring it
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    page(db, "b", 3)                                                   # new evidence
    tech(db, "done", "done tech")
    d1 = page(db, "d", 1, tech="done tech")
    run(db, "r2", 2, techs=("done",))
    assessment(db, "r2", 2, pages=[d1], tech_id="done")                # waiting for its Point of View

    items = client.get("/api/pipeline").json()["for_analyst"]
    assert items == [{"kind": "check", "count": 2, "calls": 2},
                     {"kind": "resume", "scoring_run_id": "r9", "started_at": at(9), "count": 1, "calls": 3},
                     {"kind": "assess", "count": 1, "calls": 3, "calls_max": 3, "tech_ids": ["edge-ai"]},
                     {"kind": "write", "count": 1, "calls": 1}]  # every kind with work: none is cut off
    db["documents"].delete_many({"_id": {"$in": ["s0", "s1"]}})
    items = client.get("/api/pipeline").json()["for_analyst"]
    assert [i["kind"] for i in items] == ["resume", "assess", "write"]


def test_finished_jobs_say_how_they_went(db):
    db["runs"].insert_one({"_id": "c1", "status": "completed", "run_start_date_time": at(1), "sources": []})
    db["documents"].insert_one({"_id": "f1", "run_id": "c1", "is_stub": False, "source_id": "ietf",
                                "analysis_error": {"reason": "model call failed", "detail": "429", "at": at(1)}})
    db["recheck_jobs"].insert_one({"_id": "j1", "status": "completed", "started_at": at(1), "total": 3,
                                   "done": 3, "found": 4, "other": 1, "set_aside": 2,
                                   "failed_reasons": {"model call failed": 1}})
    db["pov_compose_jobs"].insert_one({"_id": "p1", "status": "completed", "started_at": at(1),
                                       "total": 2, "done": 2, "failed": [{"tech_id": "x"}]})
    body = client.get("/api/pipeline").json()
    assert body["collect"]["analysis_errors"] == [
        {"reason": "model call failed", "detail": "429", "pages": 1, "sources": ["ietf"]}]
    assert body["signals"]["recheck"] == {"id": "j1", "status": "completed", "done": 3, "total": 3,
                                          "found": 4, "other": 1, "set_aside": 2,
                                          "failed_reasons": {"model call failed": 1}}
    assert body["pov"]["job"]["id"] == "p1" and body["pov"]["job"]["failed"] == 1


def test_only_websites_count_as_didnt_finish(db):
    db["sources"].insert_many([{"_id": "a", "access": "crawl"}, {"_id": "q", "access": "query"}])
    db["runs"].insert_one({"_id": "r1", "status": "completed", "run_start_date_time": at(1),
                           "sources": [{"source_id": "a", "incomplete": True}, {"source_id": "b"},
                                       {"source_id": "q", "incomplete": True}]})  # still to collect: on track
    run = client.get("/api/runs").json()["runs"][0]
    assert run["incomplete"] == 1 and "sources" not in run and "unfinished" not in run
    assert client.get("/api/pipeline").json()["collect"]["incomplete"] == 1
