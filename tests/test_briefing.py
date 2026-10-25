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


def test_copies_of_one_story_are_one_finding_that_says_where_else(db):
    setup(db)
    for n, site in enumerate(("entrackr", "inc42")):  # on one page it's the second finding, on the other the first
        doc(db, f"https://{site}.example/karta", 1, signals=["partnership", "funding"] if n else ["funding"])
        db["documents"].update_one({"_id": f"https://{site}.example/karta"},  # each site titles its page its own way
                                   {"$set": {"title": f"{site}: Karta AI funding", "source_id": site,
                                             # each site's finding in its own words; the company and day match
                                             f"signals.{n}.what": f"Karta AI raised $3 million ({site})",
                                             f"signals.{n}.who": "Karta AI; PeerCapital", "published_date": "2026-10-22"}})
    db["sources"].insert_many([{"_id": "entrackr", "name": "Entrackr"}, {"_id": "inc42", "name": "Inc42"}])
    found = client.get("/api/signals/found", params={"sort": "briefing", "older": "false"}).json()
    karta = [h for h in found["hits"] if "karta" in h["url"] and h["signal_id"] == "funding"]
    assert len(karta) == 1 and karta[0]["also"][0]["source"] in ("Entrackr", "Inc42")
    assert client.get("/api/briefing", params={"days": "7"}).json()["counts"]["findings"] == found["total"]


def test_the_briefing_reads_findings_kept_ready_and_stays_current(db):
    """Findings kept ready a day at a time (services/briefing_days): the same
    counts and order as working them out from the pages; a page stored later
    shows on the next read; reordering the signal list reorders the list."""
    from app.api.signals import hits, scope, tally
    from app.services import briefing_days
    setup(db)
    for days in ("7", "all"):
        body = client.get("/api/briefing", params={"days": days}).json()
        since, until = body["scope"]["from"], body["scope"]["to"]
        live = tally(scope(since, until), group=True)
        assert (body["counts"]["findings"], body["counts"]["older"], body["types"]) == (live["findings"], live["older"], live["types"])
        ready = client.get("/api/signals/found", params={"sort": "briefing", "since": since or "", "until": until}).json()
        items, total = hits(scope(since, until), sort="briefing", group=True)
        assert ready["total"] == total and [(h["doc_id"], h["n"]) for h in ready["hits"]] == [(h["doc_id"], h["n"]) for h in items]
        assert ready["hits"][0]["technologies"] == items[0]["technologies"]
    assert db["briefing_days"].count_documents({"build": {"$exists": True}}) >= 2

    doc(db, "late", 0.01, ["alpha"], ["funding"])     # stored while a collection runs
    briefing_days.touch(db["documents"].find_one({"_id": "late"})["scraped_at"])
    assert client.get("/api/briefing").json()["counts"]["findings"] == 7

    order = lambda: [h["signal_id"] for h in client.get("/api/signals/found", params={"sort": "briefing", "older": "false"}).json()["hits"]]  # noqa: E731
    assert order().index("funding") < order().index("launch")
    client.put("/api/signals/order", json={"ids": ["launch", "funding"]})
    assert order().index("launch") < order().index("funding")


def test_days_changed_in_bulk_catch_up_in_the_background_and_say_so(db, monkeypatch):
    """Today's and yesterday's changes are worked out when read; older changed
    days (a Check again) show as last kept, the Briefing says how many are
    being brought up to date, and catch_up brings them."""
    from app.services import briefing_days
    setup(db)
    assert client.get("/api/briefing", params={"days": "all"}).json()["counts"]["findings"] == 7
    monkeypatch.setattr(briefing_days, "ALWAYS_NOW", False)
    db["documents"].update_one({"_id": "old"}, {"$set": {"signals": []}})      # a Check again changed an old page
    briefing_days.touch(db["documents"].find_one({"_id": "old"})["scraped_at"])
    body = client.get("/api/briefing", params={"days": "all"}).json()
    assert body["updating_days"] == 1 and body["counts"]["findings"] == 7      # as last kept, and it says so
    assert briefing_days.catch_up() == 1
    body = client.get("/api/briefing", params={"days": "all"}).json()
    assert "updating_days" not in body and body["counts"]["findings"] == 6


def test_switching_a_signal_off_moves_only_its_own_findings(db):
    """Each kept finding holds its signal's own place in the whole list (signals.places): switching one
    off puts its findings after every listed one's, and leaves the others' as they were."""
    from app.services import briefing_days
    setup(db)
    client.get("/api/briefing", params={"days": "all"})              # the days kept ready
    rows = db["briefing_rows"]
    launch_before = sorted(r["rank"] for r in rows.find({"signal_id": "launch"}))
    db["signals"].update_one({"_id": "funding"}, {"$set": {"enabled": False}})
    briefing_days.rerank()
    assert sorted(r["rank"] for r in rows.find({"signal_id": "launch"})) == launch_before
    assert {r["rank"] for r in rows.find({"signal_id": "funding"})} == {1000}   # after every listed one's
    order = [h["signal_id"] for h in client.get("/api/signals/found", params={"sort": "briefing", "older": "false"}).json()["hits"]]
    assert "funding" not in order or order.index("launch") < order.index("funding")
