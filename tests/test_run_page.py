"""A collection's page: its times in the zone of the person who started it,
and how far its last step, judging each technology's evidence, has got."""

from fastapi.testclient import TestClient

from app.main import app
from app.services.runs import runner

client = TestClient(app)


def test_a_collection_records_who_started_its_zone(db, monkeypatch):
    def start(params):
        db["runs"].insert_one({"_id": "c9", "status": "running", "sources": []})
        return "c9"
    monkeypatch.setattr(runner, "start_run", start)
    assert client.post("/api/runs", json={}, headers={"X-Time-Zone": "America/Chicago"}).status_code == 201
    assert db["runs"].find_one({"_id": "c9"})["tz"] == "America/Chicago"


def test_its_page_says_how_far_judging_the_evidence_has_got(db):
    db["runs"].insert_one({"_id": "c9", "status": "running", "sources": []})
    assert client.get("/api/runs/c9").json()["classify"] is None
    db["classify_runs"].insert_one({"_id": "k1", "trigger": "after collection c9", "status": "stopped", "total": 8715,
                                    "done": 2900, "started_at": "2026-10-22T15:56:00+00:00",
                                    "stopped_reason": "Stopped: the token budget of 8,000,000 was reached",
                                    "failed": [{"tech_id": "x", "reason": "r"}]})
    c = client.get("/api/runs/c9").json()["classify"]
    assert (c["status"], c["done"], c["total"], c["failed"]) == ("stopped", 2900, 8715, 1)
    assert c["stopped_reason"].startswith("Stopped: the token budget") and c["failed_why"] == ["r"]
    assert c["finished_by"] is None                      # the rest still wait

    # the rest judged later, on demand: the page says who finished the work
    db["classify_runs"].insert_one({"_id": "k2", "trigger": "on demand", "status": "completed", "done": 5815,
                                    "started_at": "2026-10-22T17:55:00+00:00",
                                    "finished_at": "2026-10-22T18:30:00+00:00", "tz": "America/Chicago"})
    c = client.get("/api/runs/c9").json()["classify"]
    assert c["finished_by"] == {"id": "k2", "done": 5815, "at": "2026-10-22T18:30:00+00:00", "tz": "America/Chicago"}


def test_failed_model_calls_say_why(db):
    db["llm_calls"].insert_many([
        {"_id": "a", "run_id": "c9", "ok": False, "skills": ["article_summary"], "at": "2026-10-22T15:00:00+00:00",
         "error": "{'type': 'api_error', 'message': 'Unable to complete this request right now. Please try again.'}"},
        {"_id": "b", "run_id": "c9", "ok": True, "skills": ["article_summary"], "at": "2026-10-22T15:00:00+00:00"}])
    u = client.get("/api/usage?run_id=c9").json()
    assert u["total"]["failed"] == 1 and u["failures"] == [{"reason": "the model service was briefly unavailable", "calls": 1}]


def test_its_page_says_what_followed_until_the_next_collection(db):
    db["runs"].insert_many([
        {"_id": "c1", "status": "completed", "sources": [], "run_start_date_time": "2026-10-20T10:00:00+00:00"},
        {"_id": "c2", "status": "completed", "sources": [], "run_start_date_time": "2026-10-22T10:00:00+00:00"},
        {"_id": "f1", "status": "completed", "sources": [], "params": {"kind": "find_evidence"},
         "run_start_date_time": "2026-10-21T10:00:00+00:00"}])  # finding evidence isn't a collection
    db["scoring_runs"].insert_many([
        {"_id": "s0", "status": "completed", "started_at": "2026-10-19T10:00:00+00:00"},
        {"_id": "s1", "status": "completed", "started_at": "2026-10-21T11:00:00+00:00",
         "progress": {"techs_done": 5, "techs_total": 5}}])
    db["povs"].insert_many([{"_id": "p1", "tech_id": "a", "composed_at": "2026-10-21T12:00:00+00:00"},
                            {"_id": "p2", "tech_id": "a", "composed_at": "2026-10-21T13:00:00+00:00"},
                            {"_id": "p3", "tech_id": "b", "composed_at": "2026-10-22T12:00:00+00:00"}])
    db["editions"].insert_one({"_id": "e1", "name": "FY27 Q3", "published_at": "2026-10-21T14:00:00+00:00",
                               "tz": "America/Chicago", "placed": [], "held": []})
    first = client.get("/api/runs/c1").json()["after"]
    assert first["next_collection"]["id"] == "c2"
    assert [a["id"] for a in first["assessments"]] == ["s1"] and first["assessments"][0]["techs_done"] == 5
    assert first["povs_written"] == 1 and [e["name"] for e in first["published"]] == ["FY27 Q3"]
    latest = client.get("/api/runs/c2").json()["after"]
    assert latest["next_collection"] is None and latest["assessments"] == [] and latest["published"] == []
    assert latest["povs_written"] == 1 and latest["leaders_see"]["name"] == "FY27 Q3"


def test_settings_drop_what_the_radar_no_longer_has(db):
    db["settings"].insert_one({"_id": "radar", "name": "radar", "classify_token_budget": 8000000, "frontier_near_band": 0.4})
    body = {k: v for k, v in client.get("/api/settings/radar").json().items() if k not in ("_id", "name", "updated_at")}
    body.pop("classify_token_budget", None)
    assert client.put("/api/settings/radar", json=body).status_code == 200
    kept = db["settings"].find_one({"_id": "radar"})
    assert "classify_token_budget" not in kept and kept["frontier_near_band"] == 0.4  # the form doesn't carry every setting
