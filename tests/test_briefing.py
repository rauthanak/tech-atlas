"""The Briefing summary: a window or one collection, its counts, and the
signal types found in the Briefing's order."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)  # no lifespan: nothing is seeded


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def doc(db, url: str, days_ago: float, techs=(), signals=(), stub: bool = False, run_id: str = "c",
        published: str | None = None) -> None:
    db["documents"].insert_one({
        "_id": url, "end_url": url, "title": url, "is_stub": stub, "scraped_at": ago(days_ago),
        "published_date": published, "technologies_resolved": list(techs), "source_id": "s", "run_id": run_id,
        "signals": [{"signal_id": s, "name": s.title(), "label": "Lab" if s == "other" else None,
                     "what": "w", "who": None, "when": None, "quote": "q", "implication": None}
                    for s in signals]})


def setup(db) -> None:
    db["signals"].insert_many([
        {"_id": "funding", "signal_id": "funding", "name": "Funding round", "look_for": "x",
         "mode": "never_miss", "enabled": True, "order": 1},
        {"_id": "launch", "signal_id": "launch", "name": "Product launch", "look_for": "x",
         "mode": "never_miss", "enabled": True, "order": 2}])
    doc(db, "a1", 1, ["alpha"], ["launch", "launch", "other"])
    doc(db, "a2", 2, ["alpha"], ["funding"], published="2020-01-01")   # an older article
    doc(db, "a3", 3, ["alpha"])                                         # no finding
    doc(db, "b1", 1, ["beta"], ["retired", "other"], run_id="c2")      # "retired" is no longer on the list
    doc(db, "stub", 1, ["alpha"], ["launch"], stub=True)                # an unchanged revisit isn't new
    doc(db, "old", 8, ["alpha"], ["launch"])                            # outside a 7-day window


def test_a_window_its_counts_and_types_in_the_lists_order(db):
    setup(db)
    body = client.get("/api/briefing").json()                          # 7 days by default
    assert body["scope"]["days"] == "7" and body["scope"]["from"] < body["scope"]["to"]
    assert body["counts"] == {"findings": 6, "pages": 4, "older": 1}
    assert [(t["signal_id"], t["name"], t["count"]) for t in body["types"]] == [
        ("funding", "Funding round", 1), ("launch", "Product launch", 2),
        ("retired", "Retired", 1), ("other", "Other", 2)]               # listed, then the rest, Other last
    assert body["freshness"] is None and "new_povs" not in body
    wider = client.get("/api/briefing", params={"days": "all"}).json()
    assert wider["counts"]["findings"] == 7 and wider["scope"]["from"] is None


def test_one_collection_and_the_filters(db):
    setup(db)
    db["runs"].insert_one({"_id": "c2", "status": "terminated", "error": "interrupted — service restarted",
                           "run_start_date_time": ago(1), "run_end_date_time": ago(0.9)})
    body = client.get("/api/briefing", params={"run_id": "c2"}).json()
    assert body["scope"]["status"] == "terminated" and body["scope"]["error"].startswith("interrupted")
    assert body["counts"] == {"findings": 2, "pages": 1, "older": 0}
    assert client.get("/api/briefing", params={"tech": "alpha"}).json()["counts"] == {
        "findings": 4, "pages": 3, "older": 1}
    assert client.get("/api/briefing", params={"run_id": "c2", "days": "7"}).status_code == 422
    assert client.get("/api/briefing", params={"run_id": "nope"}).status_code == 404
    assert client.get("/api/briefing", params={"days": "soon"}).status_code == 422


def test_the_briefings_two_tabs_recent_findings_and_older_articles(db):
    setup(db)
    since = client.get("/api/briefing").json()["scope"]["from"]
    get = lambda older: client.get("/api/signals/found", params={"sort": "briefing", "since": since, "older": older}).json()
    recent, older = get("false"), get("true")
    assert older["total"] == 1 and [h["doc_id"] for h in older["hits"]] == ["a2"]
    assert recent["total"] == 5 and all(not h["older"] for h in recent["hits"])
