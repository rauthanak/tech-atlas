"""The Signals endpoints: the signal list's order, findings in the
Briefing's order with their dates and technologies, and time windows on
Not on the list and Set aside."""

from fastapi.testclient import TestClient

from app.main import app
from app.services.signals import snapshot

client = TestClient(app)  # no lifespan: nothing is seeded


def hit(signal_id: str, label: str | None = None, **extra) -> dict:
    return {"signal_id": signal_id, "name": signal_id, "label": label, "what": "w", "who": None,
            "when": None, "quote": "q", "implication": None, **extra}


def rows(db) -> None:
    db["signals"].insert_many([
        {"_id": sid, "signal_id": sid, "name": sid.title(), "look_for": "x", "mode": mode,
         "enabled": enabled, "order": n}
        for n, (sid, mode, enabled) in enumerate([("funding", "never_miss", True), ("launch", "never_miss", True),
                                                  ("paused", "never_miss", False),
                                                  ("job-ad", "can_ignore", True)], start=1)])


def setup(db) -> None:
    db["documents"].insert_many([
        {"_id": "p1", "end_url": "u1", "is_stub": False, "scraped_at": "2026-10-02", "source_id": "ietf",
         "technologies_resolved": ["edge ai"], "signals": [hit("launch"), hit("other", "Draft")]},
        {"_id": "p2", "end_url": "u2", "is_stub": False, "scraped_at": "2026-09-01", "source_id": "arxiv",
         "technologies_resolved": [], "signals": [hit("launch"), hit("other", "draft")]},
        {"_id": "p3", "end_url": "u3", "is_stub": False, "scraped_at": "2026-10-02", "source_id": "ietf",
         "technologies_resolved": [], "signals": [], "ignored_by": "single-job-ad"},
        {"_id": "p4", "end_url": "u4", "is_stub": False, "scraped_at": "2026-09-01", "source_id": "ietf",
         "technologies_resolved": [], "signals": [], "ignored_by": "single-job-ad"}])


def test_one_pages_signals_with_their_place_on_the_page(db):
    setup(db)
    body = client.get("/api/signals/found", params={"doc_id": "p1"}).json()
    assert [(h["doc_id"], h["n"], h["signal_id"]) for h in body["hits"]] == [("p1", 0, "launch"),
                                                                              ("p1", 1, "other")]


def test_not_on_the_list_and_set_aside_take_a_window(db):
    setup(db)
    other = client.get("/api/signals/other").json()
    assert other["total"] == 1 and other["groups"][0]["count"] == 2  # labels group ignoring case
    assert client.get("/api/signals/other", params={"since": "2026-10-01"}).json()["groups"][0]["count"] == 1
    assert client.get("/api/signals/other", params={"skip": 1}).json() == {"groups": [], "total": 1}
    assert client.get("/api/signals/other", params={"tech": "edge ai"}).json()["groups"][0]["count"] == 1
    assert client.get("/api/signals/other", params={"run_id": "nope"}).json() == {"groups": [], "total": 0}
    assert client.get("/api/signals/set-aside").json()["total"] == 2
    windowed = client.get("/api/signals/set-aside", params={"since": "2026-10-01"}).json()
    assert windowed["total"] == 1 and windowed["pages"][0]["doc_id"] == "p3"


# ── the signal list's order ──────────────────────────────────────────

def test_the_list_follows_its_order_and_a_new_signal_goes_last(db):
    rows(db)
    db["signals"].update_one({"_id": "funding"}, {"$set": {"order": 9}})
    listed = client.get("/api/signals").json()["signals"]
    assert [r["_id"] for r in listed] == ["launch", "paused", "funding", "job-ad"]  # never miss first
    added = client.post("/api/signals", json={"name": "Spin-out", "look_for": "x", "mode": "never_miss"}).json()
    assert added["order"] == 10


def test_reordering_stamps_only_what_moved_and_leaves_the_hash(db):
    rows(db)
    before = snapshot.current_hash()
    body = client.put("/api/signals/order", json={"ids": ["paused", "funding", "launch"]})
    assert body.status_code == 200
    assert [r["_id"] for r in body.json()["signals"]] == ["paused", "funding", "launch", "job-ad"]
    stamped = {r["_id"] for r in db["signals"].find({"updated_at": {"$exists": True}})}
    assert stamped == {"paused", "funding", "launch"}           # all three moved
    client.put("/api/signals/order", json={"ids": ["paused", "launch", "funding"]})
    assert snapshot.current_hash() == before                    # no page becomes "not yet checked"
    for wrong in (["paused", "launch"], ["paused", "launch", "funding", "job-ad"],
                  ["paused", "paused", "funding"]):
        assert client.put("/api/signals/order", json={"ids": wrong}).status_code == 422


# ── findings in the Briefing's order ────────────────────────────────

def page(db, doc_id: str, collected: str, published: str | None, signals: list[dict], techs=()) -> None:
    db["documents"].insert_one({"_id": doc_id, "end_url": doc_id, "is_stub": False, "source_id": "s",
                                "run_id": "c", "scraped_at": f"{collected}T10:00:00.123456+00:00",
                                "published_date": published, "technologies_resolved": list(techs),
                                "signals": signals})


def test_recent_first_then_the_lists_order_then_newest(db):
    rows(db)
    page(db, "fresh-launch", "2026-10-03", "2026-10-01", [hit("launch")])
    page(db, "fresh-funding", "2026-10-03", "2026-09-20", [hit("funding"), hit("other", "x")])
    page(db, "boundary", "2026-10-03", "2026-09-03", [hit("funding")])      # exactly 30 days: recent
    page(db, "undated", "2026-10-03", None, [hit("paused")])                # switched off: after the list
    page(db, "old", "2026-10-03", "2026-09-02", [hit("funding")])           # 31 days: older
    page(db, "ancient", "2026-10-03", "2020-01-01", [hit("launch")])
    body = client.get("/api/signals/found", params={"sort": "briefing"}).json()
    assert [(h["doc_id"], h["signal_id"], h["older"]) for h in body["hits"]] == [
        ("fresh-funding", "funding", False), ("boundary", "funding", False),
        ("fresh-launch", "launch", False), ("undated", "paused", False), ("fresh-funding", "other", False),
        ("old", "funding", True), ("ancient", "launch", True)]
    assert body["hits"][0]["published_date"] == "2026-09-20"
    # paging walks the same order: every finding once
    walked = [h["doc_id"] + str(h["n"]) for skip in range(0, 7, 3) for h in client.get(
        "/api/signals/found", params={"sort": "briefing", "limit": 3, "skip": skip}).json()["hits"]]
    assert walked == [h["doc_id"] + str(h["n"]) for h in body["hits"]]
    # the default order is unchanged: newest collected first
    assert client.get("/api/signals/found").json()["total"] == 7


def test_a_fixed_window(db):
    rows(db)
    page(db, "a", "2026-10-01", None, [hit("launch")])
    page(db, "b", "2026-10-03", None, [hit("launch")])
    body = client.get("/api/signals/found", params={"since": "2026-10-01", "until": "2026-10-02"}).json()
    assert [h["doc_id"] for h in body["hits"]] == ["a"]


def test_a_findings_own_technologies_win_over_its_pages(db):
    rows(db)
    db["technologies"].insert_many([{"_id": "edge-ai", "name": "edge ai", "doc_count": 3},
                                    {"_id": "6g", "name": "6g networks", "doc_count": 9},
                                    {"_id": "quic", "name": "quic", "doc_count": 1}])
    page(db, "p", "2026-10-03", None, [hit("launch", technologies_resolved=["quic"]), hit("funding")],
         techs=["edge ai", "6g networks", "quic"])
    found = client.get("/api/signals/found", params={"doc_id": "p"}).json()["hits"]
    assert found[0]["technologies"] == ["quic"] and found[0]["technology_ids"] == ["quic"]
    assert found[1]["technologies"] == ["6g networks", "edge ai", "quic"]   # the page's, most pages first
    about_edge = client.get("/api/signals/found", params={"tech": "edge ai"}).json()["hits"]
    assert [(h["signal_id"], h["technologies"][0]) for h in about_edge] == [("funding", "edge ai")]  # filtered first
    about_quic = client.get("/api/signals/found", params={"tech": "quic"}).json()
    assert about_quic["total"] == 2
