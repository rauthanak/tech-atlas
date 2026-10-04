"""Problems: worked out from the latest collection, sources and jobs; websites
that reached their page limit are coverage, reported apart."""

from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings
from factories import at

client = TestClient(app)  # no lifespan: nothing is seeded


def source(source_id: str, access: str = "crawl", adapter: str | None = None) -> dict:
    return {"_id": source_id, "source_id": source_id, "name": source_id.upper(), "access": access,
            "adapter": adapter, "enabled": True, "cost": "free"}


def row(source_id: str, note: str | None = None, error: str | None = None) -> dict:
    return {"source_id": source_id, "source_name": source_id.upper(), "incomplete": bool(note),
            "incomplete_note": note, "error": error}


def failed(doc_id: str, reason: str, run_id: str = "c2", day: int = 5) -> dict:
    return {"_id": doc_id, "run_id": run_id, "is_stub": False, "title": doc_id, "end_url": doc_id,
            "source_id": "ietf", "analysis_error": {"reason": reason, "detail": "d", "at": at(day)}}


def test_each_kind_of_problem(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "contact_email", "")
    db["sources"].insert_many([source("ietf"), source("inc42"),
                               source("openalex", "query", "openalex_works"),
                               source("nsf", "query", "openalex_awards"),
                               source("sec", "query", "sec_edgar")])
    db["runs"].insert_one({"_id": "c2", "status": "terminated", "error": "interrupted — service restarted",
                           "run_start_date_time": at(5), "sources": [
                               row("ietf", note="didn't finish: 1081 links left"),
                               row("openalex", note="25 still to collect (q: 25); too broad: narrow the search (q2)"),
                               row("nsf", note="5 still to collect (q: 5)"),  # carries on next time
                               row("sec", error="not configured: set CONTACT_EMAIL in .env"),
                               row("inc42", error="boom")]})
    db["documents"].insert_many([failed("f1", "model call failed"), failed("f2", "model call failed"),
                                 failed("f3", "reply not in the expected format"),
                                 failed("old", "model call failed", run_id="c1", day=1),  # older collection
                                 failed("checked", "unexpected error", run_id="c1", day=6)])  # in the latest check
    db["recheck_jobs"].insert_one({"_id": "j1", "status": "interrupted", "started_at": at(6)})
    db["scoring_runs"].insert_one({"_id": "s1", "status": "terminated", "error": "terminated by user",
                                   "started_at": at(4)})  # a person stopped it: not a problem
    db["pov_compose_jobs"].insert_one({"_id": "p1", "status": "failed", "error": "x", "started_at": at(4)})

    body = client.get("/api/problems").json()
    kinds = [(p["kind"], p.get("source_id") or p.get("job")) for p in body["problems"]]
    assert kinds == [("too_broad", "openalex"), ("source_error", "inc42"),
                     ("not_configured", "sec"), ("failed_pages", None), ("job_failed", "collection"),
                     ("job_failed", "check"), ("job_failed", "pov")]
    pages = body["problems"][3]
    assert pages["count"] == 4 and [(r["reason"], r["pages"]) for r in pages["reasons"]] == [
        ("model call failed", 2), ("reply not in the expected format", 1), ("unexpected error", 1)]
    assert body["problems"][2]["keys"] == ["CONTACT_EMAIL"]
    # a website that reached its page limit is coverage, not a problem
    assert [(c["kind"], c["source_id"], c["note"]) for c in body["coverage"]] == [
        ("didnt_finish", "ietf", "didn't finish: 1081 links left")]
    assert body["count"] == 7 and client.get("/api/pipeline").json()["problems"] == 7
