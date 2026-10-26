"""Each technology's answers kept ready (services/tech_status): worked out by
the same rules as before, updated at once after a person's action, picked up
by time after other writes, recounted when the setup changes, and removed
with the technology. These tests run without the "always fresh" mode, as
the radar does."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import radar_status, tech_status
from factories import at, page, tech
from stacked_fakes import load_seeded

client = TestClient(app)


@pytest.fixture(autouse=True)
def as_the_radar_runs(monkeypatch):
    monkeypatch.setattr(tech_status, "ALWAYS_FRESH", False)


def _world(db):
    load_seeded(db, "availability", "domains", "subdomains", "trl_levels", "settings")
    tech(db, "edge-ai", "edge ai")
    tech(db, "quantum-sensing", "quantum sensing")
    db["technologies"].update_many({}, {"$set": {"page_count": 3, "doc_count": 3}})


def test_stored_answers_equal_the_rules(db):
    _world(db)
    ids = ["edge-ai", "quantum-sensing"]
    assert tech_status.refresh(ids) == 2
    live = radar_status.statuses(ids)
    for row in db["tech_status_rows"].find():
        assert row["row"]["status"] == live[row["_id"]]["status"]
        assert row["row"]["classification"] == live[row["_id"]]["classification"]
    small = db["tech_status"].find_one({"_id": "edge-ai"})
    assert small["f"]["status"] == live["edge-ai"]["status"] and "tracked" not in small["f"]["views"]


def test_a_persons_choice_shows_at_once(db):
    _world(db)
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    before = db["tech_status"].find_one({"_id": "edge-ai"})["f"]["availability"]
    out = client.post("/api/decisions", json={"kind": "move", "tech_id": "edge-ai", "field": "availability",
                                               "value": "pilot", "reason": "seen at a trade show"})
    assert out.status_code == 201
    assert db["tech_status"].find_one({"_id": "edge-ai"})["f"]["availability"] == "pilot" != before
    undo = client.delete(f"/api/decisions/{out.json()['decision']['_id']}")
    assert undo.status_code == 200
    assert db["tech_status"].find_one({"_id": "edge-ai"})["f"]["availability"] == before


def test_marked_ones_are_worked_out_by_the_updater_and_unmarked(db):
    _world(db)
    tech_status.touch(["edge-ai"])
    assert tech_status.pending() == 1
    assert tech_status.step() == 1
    assert tech_status.pending() == 0 and db["tech_status"].count_documents({}) == 1


def test_one_marked_again_while_worked_out_stays_marked(db, monkeypatch):
    _world(db)
    tech_status.touch(["edge-ai"])
    real = tech_status.refresh

    def refresh_while_a_new_page_arrives(ids):
        done = real(ids)
        db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {tech_status.DIRTY: "9999"}})  # marked again
        return done
    monkeypatch.setattr(tech_status, "refresh", refresh_while_a_new_page_arrives)
    tech_status.step()
    assert tech_status.pending() == 1


def test_changes_are_picked_up_by_time(db):
    _world(db)
    since = at(10)
    page(db, "https://a.example/new", 12, tech="quantum sensing")
    db["decisions"].insert_one({"_id": "d1", "tech_id": "edge-ai", "kind": "move", "active": True, "at": at(11)})
    assert tech_status._changed_since(since) == {"edge-ai", "quantum-sensing"}
    assert tech_status._changed_since(at(13)) == set()


def test_a_removed_technology_loses_its_answers(db):
    _world(db)
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    db["technologies"].delete_one({"_id": "quantum-sensing"})
    tech_status.refresh(["quantum-sensing"])
    assert db["tech_status"].find_one({"_id": "quantum-sensing"}) is None
    assert db["tech_status_rows"].find_one({"_id": "quantum-sensing"}) is None


def test_a_setup_edit_marks_every_technology(db):
    _world(db)
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    settings = client.get("/api/settings/radar").json()
    assert client.put("/api/settings/radar", json=settings).status_code == 200
    assert tech_status.pending() == 2


def test_a_screen_works_out_the_few_waiting_before_it_reads(db):
    _world(db)
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"enabled": False}})
    tech_status.touch(["edge-ai"])
    body = client.get("/api/technologies", params={"view": "off"}).json()
    assert [t["_id"] for t in body["technologies"]] == ["edge-ai"] and body["updating"] == 0


def test_to_do_carries_the_first_names_and_the_full_count(db):
    _world(db)
    for n in range(60):
        tech(db, f"t{n:02d}", f"tech {n:02d}")
    db["technologies"].update_many({}, {"$set": {"page_count": 3, "doc_count": 3,
                                                 "classification": {"nascent": {"reason": "an early sign", "page": "p"},
                                                                    "at": at(1)}}})
    tech_status.refresh(db["technologies"].distinct("_id"))
    nascent = next(i for i in client.get("/api/gates").json()["gate1"] if i["kind"] == "nascent")
    assert nascent["count"] == 62 and len(nascent["technologies"]) == tech_status.LISTED
    assert nascent["sentence"].startswith("62 possibly nascent")


def test_the_cost_of_many_is_one_request(db):
    _world(db)
    out = client.post("/api/scoring/preview", json={"technologies": ["edge-ai", "quantum-sensing", "not-there"]})
    assert out.status_code == 200 and out.json()["technologies"] == 2


def test_the_safety_net_works_out_the_oldest_records_a_batch_at_a_time(db, monkeypatch):
    _world(db)
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    db["tech_status"].update_one({"_id": "edge-ai"}, {"$set": {"at": at(1)}})          # long ago
    monkeypatch.setattr(tech_status, "BATCH", 1)
    assert tech_status.sweep() == 1
    assert db["tech_status"].find_one({"_id": "edge-ai"})["at"] > at(30)
    assert tech_status.sweep() == 0                                                     # nothing old is left
    assert tech_status.pending() == 0                                                   # nothing was marked


def test_an_organize_marks_only_the_technologies_its_pages_name(db, monkeypatch):
    import json
    from agent.resolver import resolver
    _world(db)
    load_seeded(db, "prompts")                       # the organize skills
    monkeypatch.setattr(resolver.LLM, "initialize", classmethod(lambda cls, *a, **k: type(
        "M", (), {"ask": lambda self, p, system=None, **kw: json.dumps({"groups": [], "labels": {}})})()))
    db["documents"].insert_one({"technologies": ["edge ai"], "ignored_by": None, "is_stub": False, "to_organize": True,
                                "end_url": "https://x/new", "source_id": "s", "category": "H1", "kind": "article"})
    resolver.run_resolve_sync()
    assert db["technologies"].distinct("_id", {tech_status.DIRTY: {"$exists": True}}) == ["edge-ai"]


def test_big_technologies_are_worked_out_in_smaller_batches(db, monkeypatch):
    """A batch holds at most BATCH_PAGES pages between its technologies, so the worker's memory stays small."""
    monkeypatch.setattr(tech_status, "BATCH_PAGES", 100)
    _world(db)
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"page_count": 90}})
    db["technologies"].update_one({"_id": "quantum-sensing"}, {"$set": {"page_count": 30}})
    assert list(tech_status._batches(["edge-ai", "quantum-sensing"])) == [["edge-ai"], ["quantum-sensing"]]
    assert tech_status.refresh(["edge-ai", "quantum-sensing"]) == 2


def test_putting_back_a_list_value_marks_every_technology(db, seeds):
    """Code review CR13: Put back the default refreshes the answers, as the edit it undoes did."""
    from app.services.db import seeding
    _world(db)
    seeding.load_if_new()
    db["availability"].update_one({"_id": "pilot"}, {"$set": {"name": "Trial", "updated_at": "2999-01-01T00:00:00+00:00"}})
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    assert tech_status.pending() == 0
    assert client.post("/api/changes/revert", json={"items": [{"collection": "availability", "id": "pilot"}]}).status_code == 200
    assert tech_status.pending() == 2


def test_putting_back_a_signal_marks_none(db, seeds):
    from app.services.db import seeding
    _world(db)
    seeding.load_if_new()
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    signal = db["signals"].find_one()
    db["signals"].update_one({"_id": signal["_id"]}, {"$set": {"name": "x", "updated_at": "2999-01-01T00:00:00+00:00"}})
    assert client.post("/api/changes/revert", json={"items": [{"collection": "signals", "id": signal["_id"]}]}).status_code == 200
    assert tech_status.pending() == 0


def test_a_setup_edit_marks_every_technology_off_the_event_loop(db, monkeypatch):
    """Code review CR21: the refresh after a Setup edit runs in the threadpool, so other requests go on."""
    import asyncio
    _world(db)
    tech_status.refresh(["edge-ai", "quantum-sensing"])
    on_loop, real = [], tech_status.touch_all

    def touch_all():
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real()
    monkeypatch.setattr(tech_status, "touch_all", touch_all)
    settings = client.get("/api/settings/radar").json()
    assert client.put("/api/settings/radar", json=settings).status_code == 200
    assert on_loop == [False] and tech_status.pending() == 2
