"""F1: the seeding data loads into a fresh database or when it changed;
edits stay live and are listed; Update seeding data writes only what is
ticked, keeps the file layout, and never makes a restart reload."""

import json
import os
import time

import pytest

from app.services.db import seeding
from app.services.db.mongo import get_collection


def _touch(collection: str, item_id: str, **changes):
    """An edit as the app makes it: new values plus updated_at."""
    time.sleep(0.01)
    get_collection(collection).update_one(
        {"_id": item_id}, {"$set": {**changes, "updated_at": seeding._now()}})


def test_load_rule(db, seeds):
    assert seeding.load_if_new() is True          # fresh database
    assert get_collection("sources").count_documents({}) == len(seeding.read_list("sources"))
    assert seeding.load_if_new() is False         # restart: nothing new
    _touch("signals", "ipo", look_for="edited live")
    assert seeding.load_if_new() is False         # a live edit survives a restart
    assert get_collection("signals").find_one({"_id": "ipo"})["look_for"] == "edited live"

    data = json.loads((seeds / "signals.json").read_text())
    data["signals"][0]["look_for"] = "changed in the code"
    (seeds / "signals.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    assert seeding.load_if_new() is True          # a deployment with new seeding data
    first = data["signals"][0]["signal_id"]
    assert get_collection("signals").find_one({"_id": first})["look_for"] == "changed in the code"
    assert get_collection("signals").find_one({"_id": "ipo"})["look_for"] != "edited live"


def test_load_matches_seeding_data_exactly(db, seeds):
    seeding.load_if_new()
    get_collection("signals").insert_one({"_id": "extra", "signal_id": "extra", "name": "Extra",
                                          "look_for": "x", "mode": "never_miss", "enabled": True})
    get_collection("sources").update_one({"_id": "arxiv"},
                                         {"$set": {"progress": {"q": {"through": "2026-09-01"}},
                                                   "url": "https://elsewhere.example"}})
    seeding.load()
    assert get_collection("signals").find_one({"_id": "extra"}) is None    # not in the seeding data
    arxiv = get_collection("sources").find_one({"_id": "arxiv"})
    assert arxiv["url"] != "https://elsewhere.example"                     # seeded field replaced
    assert arxiv["progress"] == {"q": {"through": "2026-09-01"}}           # the app's own note kept


def test_changes_lists_edits_added_and_deleted(db, seeds):
    seeding.load_if_new()
    assert seeding.changes()["count"] == 0
    _touch("prompts", "scout", description="new description")
    get_collection("prompts").update_one({"_id": "scout"}, {"$inc": {"version": 1}})
    _touch("sources", "ietf", enabled=False, progress={"x": {"remaining": 3}})
    get_collection("signals").insert_one({"_id": "new-one", "signal_id": "new-one", "name": "New one",
                                          "look_for": "y", "mode": "never_miss", "enabled": True,
                                          "updated_at": seeding._now()})
    get_collection("signals").delete_one({"_id": "ipo"})
    rows = {(r["collection"], r["id"]): r for r in seeding.changes()["items"]}
    assert rows[("prompts", "scout")]["kind"] == "edited"
    assert [f["field"] for f in rows[("prompts", "scout")]["fields"]] == ["description"]  # version ignored
    assert [f["field"] for f in rows[("sources", "ietf")]["fields"]] == ["enabled"]       # progress ignored
    assert rows[("signals", "new-one")]["kind"] == "added"
    assert rows[("signals", "ipo")]["kind"] == "deleted"
    assert len(rows) == 4

    original = seeding.read_list("prompts")
    scout = next(p for p in original if p["name"] == "scout")
    _touch("prompts", "scout", description=scout["description"])          # changed back by hand
    assert ("prompts", "scout") not in {(r["collection"], r["id"]) for r in seeding.changes()["items"]}


def test_progress_alone_is_not_a_change(db, seeds):
    seeding.load_if_new()
    get_collection("sources").update_one({"_id": "arxiv"},
                                         {"$set": {"progress": {"q": {"remaining": 5}}}})
    assert seeding.changes()["count"] == 0


def test_update_seeding_data_writes_only_ticked(db, seeds):
    seeding.load_if_new()
    before = (seeds / "prompts.json").read_text()
    _touch("prompts", "scout", description="ticked")
    _touch("sources", "ietf", enabled=False)
    result = seeding.update_seeding_data([{"collection": "prompts", "id": "scout"}])
    assert result == {"written": 1, "files": ["seeds/prompts.json"]}
    after = (seeds / "prompts.json").read_text()
    changed = [line for line in after.splitlines() if line not in before.splitlines()]
    assert changed == ['      "description": "ticked",']                # layout kept, one line changed
    remaining = seeding.changes()["items"]
    assert [(r["collection"], r["id"]) for r in remaining] == [("sources", "ietf")]
    assert seeding.load_if_new() is False                                  # a restart doesn't reload
    assert get_collection("sources").find_one({"_id": "ietf"})["enabled"] is False


def test_update_seeding_data_added_and_deleted(db, seeds):
    seeding.load_if_new()
    get_collection("signals").insert_one({"_id": "new-one", "signal_id": "new-one", "name": "New one",
                                          "look_for": "y", "mode": "never_miss", "enabled": True,
                                          "updated_at": seeding._now()})
    get_collection("signals").delete_one({"_id": "ipo"})
    seeding.update_seeding_data([{"collection": "signals", "id": "new-one"},
                                 {"collection": "signals", "id": "ipo"}])
    ids = [s["signal_id"] for s in seeding.read_list("signals")]
    assert "ipo" not in ids and ids[-1] == "new-one"
    assert seeding.read_list("signals")[-1] == {"signal_id": "new-one", "name": "New one",
                                                "look_for": "y", "mode": "never_miss",
                                                "enabled": True}
    assert seeding.changes()["count"] == 0


def test_failed_write_leaves_file_and_listing(db, seeds):
    seeding.load_if_new()
    _touch("prompts", "scout", description="won't fit")
    target = seeds / "prompts.json"
    before = target.read_text()
    os.chmod(target, 0o444)
    try:
        with pytest.raises(PermissionError):
            seeding.update_seeding_data([{"collection": "prompts", "id": "scout"}])
    finally:
        os.chmod(target, 0o644)
    assert target.read_text() == before
    assert [r["id"] for r in seeding.changes()["items"]] == ["scout"]
    assert seeding.load_if_new() is False
