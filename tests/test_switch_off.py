"""Switching a technology off from the list: when and in which zone, in bulk,
and the pages collected since (the wake flag)."""

from fastapi.testclient import TestClient

from app.main import app
from factories import page, tech

client = TestClient(app)  # no lifespan: nothing is seeded
KOLKATA = {"X-Time-Zone": "Asia/Kolkata"}


def test_switching_off_records_when_and_where_and_switching_on_clears_it(db):
    tech(db)
    client.put("/api/technologies/edge-ai", json={"name": "edge ai", "enabled": False}, headers=KOLKATA)
    t = db["technologies"].find_one({"_id": "edge-ai"})
    assert t["enabled"] is False and t["switched_off_tz"] == "Asia/Kolkata" and t["switched_off_at"]
    client.put("/api/technologies/edge-ai", json={"name": "edge ai", "enabled": True})
    t = db["technologies"].find_one({"_id": "edge-ai"})
    assert t["enabled"] is True and "switched_off_at" not in t and "switched_off_tz" not in t


def test_a_rename_keeps_the_switch_off_time(db):
    tech(db, enabled=False)
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"switched_off_at": "2026-09-01T00:00:00+00:00"}})
    client.put("/api/technologies/edge-ai", json={"name": "Edge AI", "enabled": False})
    assert db["technologies"].find_one({"_id": "edge-ai"})["switched_off_at"] == "2026-09-01T00:00:00+00:00"


def test_an_unknown_zone_falls_back_to_the_default(db):
    tech(db)
    client.put("/api/technologies/edge-ai", json={"name": "edge ai", "enabled": False},
               headers={"X-Time-Zone": "Mars/Olympus"})
    assert db["technologies"].find_one({"_id": "edge-ai"})["switched_off_tz"] == "America/Chicago"


def test_bulk_switches_only_those_not_already_switched(db):
    tech(db)
    tech(db, "quic", "quic")
    tech(db, "old", "old tech", enabled=False)
    db["technologies"].update_one({"_id": "old"}, {"$set": {"switched_off_at": "2026-09-01T00:00:00+00:00"}})
    r = client.post("/api/technologies/bulk", json={"ids": ["edge-ai", "quic", "old"], "action": "switch_off"},
                    headers=KOLKATA).json()
    assert r == {"changed": 2, "action": "switch_off"}
    assert db["technologies"].find_one({"_id": "old"})["switched_off_at"] == "2026-09-01T00:00:00+00:00"
    assert client.post("/api/technologies/bulk", json={"ids": ["quic"], "action": "switch_on"}).json()["changed"] == 1
    assert client.post("/api/technologies/bulk", json={"ids": [], "action": "switch_on"}).status_code == 422


def test_switched_off_technologies_leave_the_estimate(db):
    db["measures"].insert_one({"_id": "m1"})
    db["fabrics"].insert_one({"_id": "cloud", "enabled": True})
    tech(db)
    tech(db, "quic", "quic")
    before = client.get("/api/scoring/preview", params={"technologies": "edge-ai,quic"}).json()["technologies"]
    client.post("/api/technologies/bulk", json={"ids": ["quic"], "action": "switch_off"})
    after = client.get("/api/scoring/preview", params={"technologies": "edge-ai,quic"}).json()["technologies"]
    assert (before, after) == (2, 1)


def test_pages_since_switching_off_and_the_wake_flag(db):
    tech(db, enabled=False)
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"switched_off_at": "2026-09-05T00:00:00+00:00"}})
    page(db, "old", 3)
    for n in range(10):
        page(db, f"new-{n}", 6)
    page(db, "new-0", 7)  # a revisit of the same page counts once
    row = client.get("/api/technologies").json()["technologies"][0]
    assert row["pages_since_off"] == 10 and row["wake"] is True
    summary = client.get("/api/technologies/edge-ai/summary").json()["technology"]
    assert summary["pages_since_off"] == 10 and summary["wake"] is True
