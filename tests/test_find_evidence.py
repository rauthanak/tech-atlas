"""Find evidence: known pages skipped, new ones read and filed under the
technology (or set aside by a Can ignore rule, and said so), only the gap's
call run again, the budget refusal, the message when no search is set up,
Add a link without a search, the query built from what the gap says is
missing, each page found counted as its own site, and a Find evidence run
not counted as a collection."""

import json

from fastapi.testclient import TestClient

from agent.find_evidence import job as finder
from app.main import app
from app.services import websearch
from factories import page, tech
from stacked_fakes import load_seeded

client = TestClient(app)


class Model:
    def ask(self, prompt, system=None, **kw):
        if "Its keys are exactly" in "\n".join([*(kw.get("blocks") or []), prompt]):
            return json.dumps({"evidence_strength": {"verdict": "strong", "reason": "new trial page", "pages": [1]},
                               "domain_subdomain": {"domain_id": "ai", "subdomain": None, "reason": "r"},
                               "commercial_availability": {"value_id": "pilot", "reason": "r"},
                               "trl_level": {"level": 6, "reason": "r"}, "possible_nascent": {"flag": False}})
        if "event.example" in prompt:
            return json.dumps({"summary": "Register for our edge AI webinar", "technologies": ["edge ai"],
                               "scout_take": "t", "signals": [], "ignore": "Event or webinar promotion"})
        return json.dumps({"summary": "A field trial of edge AI began", "technologies": ["edge ai"], "scout_take": "t",
                           "signals": []})


def _world(db, monkeypatch):
    load_seeded(db, "prompts", "recipes", "availability", "domains", "subdomains", "trl_levels", "settings", "signals")
    tech(db)
    page(db, "https://known.example/a", 1)
    monkeypatch.setattr(finder.LLM, "initialize", classmethod(lambda cls, *a, **k: Model()))
    import agent.classifier.classify as classify
    monkeypatch.setattr(classify, "LLM", finder.LLM)


def test_known_pages_are_skipped_new_ones_filed_and_only_classify_runs_again(db, monkeypatch):
    _world(db, monkeypatch)
    db["find_evidence_jobs"].insert_one({"_id": "j1", "gap": {"kind": "technology", "tech_id": "edge-ai"},
                                         "query": "edge ai trial", "at": "2026-10-21T00:00:00+00:00", "tz": "UTC",
                                         "results": [], "searched": True})
    found = [{"url": "https://known.example/a", "title": "A"}, {"url": "https://new.example/b", "title": "B"},
             {"url": "https://broken.example/c", "title": "C"}]
    fetch = lambda url: ("A field trial of edge AI began at a Singapore operator. " * 20, {"title": "B"}, None) \
        if "new" in url else (None, {}, "the site answered 404")
    finder.run("j1", fetch=fetch, search=lambda q, n: found)
    j = db["find_evidence_jobs"].find_one({"_id": "j1"})
    assert [r["status"] for r in j["results"]] == ["already", "filed", "failed"]
    assert j["results"][2]["reason"] == "the site answered 404"
    doc = db["documents"].find_one({"end_url": "https://new.example/b"})
    assert "edge ai" in doc["technologies_resolved"] and doc["found_by"]["job_id"] == "j1"
    assert doc["source_id"] == "web_search" and doc["source_name"] == "new.example (web search)"
    assert j["summary"].startswith("1 new page filed under edge ai from 3 results (1 already collected); "
                                   "1 couldn't be read (the site answered 404). Classified again")
    assert db["technologies"].find_one({"_id": "edge-ai"})["classification"]["evidence"]["verdict"] == "strong"


def test_without_a_search_it_says_why_and_a_link_still_works(db, monkeypatch):
    _world(db, monkeypatch)
    monkeypatch.setattr(websearch, "configured", lambda: False)
    r = client.post("/api/find-evidence", json={"gap": {"kind": "technology", "tech_id": "edge-ai"}})
    assert r.status_code == 409 and "web search key" in r.json()["detail"]
    pre = client.get("/api/find-evidence/preview", params={"kind": "technology", "tech_id": "edge-ai"}).json()
    assert "Add a link still works" in pre["why_not"]
    monkeypatch.setattr(finder, "start", lambda gap, tz: "job")
    assert client.post("/api/find-evidence", json={"gap": {"kind": "link", "tech_id": "edge-ai",
                                                           "url": "https://x.example"}}).status_code == 202
    assert client.post("/api/find-evidence", json={"gap": {"kind": "link", "tech_id": "edge-ai",
                                                           "url": "x.example"}}).status_code == 422


def test_the_daily_budget_refuses_with_the_reason(db, monkeypatch):
    _world(db, monkeypatch)
    monkeypatch.setattr(websearch, "configured", lambda: True)
    db["settings"].update_one({"_id": "radar"}, {"$set": {"find_evidence_daily_budget": 1}}, upsert=True)
    from datetime import datetime, timezone
    db["find_evidence_jobs"].insert_one({"_id": "old", "gap": {}, "searched": True, "at": datetime.now(timezone.utc).isoformat()})
    r = client.post("/api/find-evidence", json={"gap": {"kind": "technology", "tech_id": "edge-ai"}})
    assert r.status_code == 429 and "Today's 1 searches are used up" in r.json()["detail"]


TRIAL = "A field trial of edge AI began at a Singapore operator. " * 20


def test_a_page_set_aside_by_a_rule_is_said_so_not_filed_and_nothing_runs_again(db, monkeypatch):
    _world(db, monkeypatch)
    db["find_evidence_jobs"].insert_one({"_id": "j2", "gap": {"kind": "technology", "tech_id": "edge-ai"},
                                         "query": "edge ai trial", "at": "2026-10-21T00:00:00+00:00", "tz": "UTC",
                                         "results": [], "searched": True})
    finder.run("j2", fetch=lambda url: (TRIAL, {}, None),
               search=lambda q, n: [{"url": "https://event.example/webinar", "title": "Webinar"}])
    j = db["find_evidence_jobs"].find_one({"_id": "j2"})
    r = j["results"][0]
    assert r["status"] == "set_aside" and r["rule"] == "Event or webinar promotion" and "webinar" in r["reason"]
    assert db["documents"].find_one({"end_url": "https://event.example/webinar"})["technologies_resolved"] == []
    assert j["summary"] == ('0 new pages filed under edge ai from 1 result; 1 set aside by the Can ignore rule '
                            '"Event or webinar promotion". Nothing was filed under it, so nothing was run again.')
    assert "classification" not in db["technologies"].find_one({"_id": "edge-ai"})


def test_a_job_reads_as_its_pages_are_now_so_an_older_summary_no_longer_overstates(db, monkeypatch):
    _world(db, monkeypatch)
    page(db, "https://event.example/x", 2, tech=None, ignored_by="event-promotion")
    page(db, "https://paper.example/y", 2)
    db["find_evidence_jobs"].insert_one({
        "_id": "old", "gap": {"kind": "technology", "tech_id": "edge-ai"}, "status": "completed", "searched": True,
        "query": "edge ai", "at": "2026-10-21T00:00:00+00:00", "tz": "UTC",
        "summary": "2 new pages from 3 results, 1 couldn't be read. Classified again.",
        "rerun": {"kind": "technology", "outcome": "Classified again."},
        "results": [{"url": "https://event.example/x", "status": "new", "doc_id": "https://event.example/x@2"},
                    {"url": "https://paper.example/y", "status": "new", "doc_id": "https://paper.example/y@2"},
                    {"url": "https://gone.example/z", "status": "failed", "reason": "too little text on the page"}]})
    jobs = client.get("/api/find-evidence", params={"tech_id": "edge-ai"}).json()["jobs"]
    assert [r["status"] for r in jobs[0]["results"]] == ["set_aside", "filed", "failed"]
    assert jobs[0]["summary"] == ('1 new page filed under edge ai from 3 results; 1 set aside by the Can ignore rule '
                                  '"Event or webinar promotion"; 1 couldn\'t be read (too little text on the page). '
                                  'Classified again.')


def test_the_query_is_what_the_gap_says_is_missing_cut_at_a_word(db, monkeypatch):
    tech(db, "pon", "50g-pon")
    db["technologies"].update_one({"_id": "pon"}, {"$set": {"label": "50G-PON"}})
    db["fabrics"].insert_one({"_id": "network", "name": "Network"})
    missing = ("A dated analyst or primary market-size figure for 50G-PON equipment or services, with its scope "
               "and the year it covers.")
    monkeypatch.setattr(finder, "latest_assessment", lambda t, f: {
        "measures": {"m1": {"missing": missing}},
        "no_use_case": {"evidence_needed": "Named operators running 50G-PON for enterprise backhaul (with dates)"}})
    q = finder.query_for({"kind": "measure", "tech_id": "pon", "fabric_id": "network", "measure_id": "m1"})
    assert q == "50G-PON Network dated analyst or primary market-size figure for 50G-PON equipment or services"
    q = finder.query_for({"kind": "use_case", "tech_id": "pon", "fabric_id": "network"})
    assert q == "50G-PON Network Named operators running 50G-PON for enterprise backhaul"
    long = finder._cut("word " * 10 + "figures for regional spending on equipment or software and services", 60)
    assert len(long) <= 60 and long.split()[-1] not in finder.FILLER


def test_each_page_found_by_web_search_counts_as_its_own_site(db):
    from agent.classifier.evidence import pack
    from agent.resolver import restamp_all
    tech(db)
    page(db, "https://arxiv.org/pdf/1", 1, source_id="web_search")
    page(db, "https://partnershiponai.org/r", 1, source_id="web_search")
    page(db, "https://www.arxiv.org/pdf/2", 1, source_id="web_search")  # the same site again
    page(db, "https://collected.example/a", 1)
    assert pack("edge ai", 10)["sources"] == 3
    restamp_all()
    assert db["technologies"].find_one({"_id": "edge-ai"})["source_count"] == 3


def test_the_briefing_does_not_count_a_find_evidence_run_as_a_collection(db):
    db["runs"].insert_many([
        {"_id": "c1", "params": {"categories": ["H1"]}, "run_start_date_time": "2026-10-20T00:00:00+00:00",
         "run_end_date_time": "2026-10-20T01:00:00+00:00", "totals": {"sources": 12, "new_documents": 40}},
        {"_id": "fe", "params": {"kind": "find_evidence", "job_id": "j"}, "run_start_date_time": "2026-10-21T00:00:00+00:00",
         "run_end_date_time": "2026-10-21T00:01:00+00:00", "totals": {"sources": 0, "new_documents": 0}}])
    fresh = client.get("/api/briefing").json()["freshness"]
    assert fresh["run_id"] == "c1" and fresh["sources"] == 12
