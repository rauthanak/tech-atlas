"""F1: the seeding data loads into a fresh database or when it changed;
edits stay live and are listed; Update seeding data writes only what is
ticked, keeps the file layout, and never makes a restart reload.
SEED: a change in the code loads into everything not edited in the app, and
removes only what the code removed."""

import json
import logging
import os
import threading
import time

import pytest

from app.services.db import seeding
from app.services.db.mongo import get_collection


def _touch(collection: str, item_id: str, **changes):
    """An edit as the app makes it: new values plus updated_at."""
    time.sleep(0.01)
    get_collection(collection).update_one(
        {"_id": item_id}, {"$set": {**changes, "updated_at": seeding._now()}})


def _code(seeds, listed: str, item_id: str, remove: bool = False, **changes):
    """A change in the code: new values for one seed item, or the item removed."""
    path = seeds / f"{listed}.json"
    data = json.loads(path.read_text())
    items = data[listed]
    n = next(k for k, i in enumerate(items) if i[seeding.ID_FIELDS[listed]] == item_id)
    if remove:
        del items[n]
    else:
        items[n].update(changes)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _live(collection: str, item_id: str) -> dict | None:
    return get_collection(collection).find_one({"_id": item_id})


def _listed() -> set:
    return {(r["collection"], r["id"], r["kind"]) for r in seeding.changes()["items"]}


def test_load_rule(db, seeds):
    assert seeding.load_if_new() is True          # fresh database
    assert get_collection("sources").count_documents({}) == len(seeding.read_list("sources"))
    assert seeding.load_if_new() is False         # restart: nothing new
    _touch("signals", "ipo", look_for="edited live")
    assert seeding.load_if_new() is False         # a live edit survives a restart
    assert _live("signals", "ipo")["look_for"] == "edited live"

    _code(seeds, "signals", "funding-round", look_for="changed in the code")
    _code(seeds, "signals", "ipo", look_for="ipo changed in the code")
    assert seeding.load_if_new() is True          # a deployment with new seeding data
    assert _live("signals", "funding-round")["look_for"] == "changed in the code"
    assert _live("signals", "ipo")["look_for"] == "edited live"      # the app's edit is kept
    assert seeding.load_if_new() is False


def test_load_keeps_what_the_seeds_dont_hold(db, seeds):
    """A code change replaces the seeded fields of an item not edited in the
    app (no updated_at), keeps the app's own notes, and leaves app-added items."""
    seeding.load_if_new()
    get_collection("signals").insert_one({"_id": "extra", "signal_id": "extra", "name": "Extra",
                                          "look_for": "x", "mode": "never_miss", "enabled": True})
    get_collection("sources").update_one({"_id": "arxiv"},
                                         {"$set": {"progress": {"q": {"through": "2026-09-01"}},
                                                   "url": "https://elsewhere.example"}})
    _code(seeds, "sources", "ietf", name="IETF, renamed")
    assert seeding.load_if_new() is True
    assert _live("signals", "extra") is not None                          # added in the app
    arxiv = _live("sources", "arxiv")
    assert arxiv["url"] != "https://elsewhere.example"                     # seeded field replaced
    assert arxiv["progress"] == {"q": {"through": "2026-09-01"}}           # the app's own note kept
    assert "seeded_at" not in seeding.read_list("sources")[0]


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


def test_proposals_waiting_for_review_are_counted_apart(db, seeds):
    seeding.load_if_new()
    get_collection("subdomains").insert_many([
        {"_id": "ai--proposed", "subdomain_id": "ai--proposed", "domain_id": "ai", "name": "Proposed", "status": "new"},
        {"_id": "ai--accepted", "subdomain_id": "ai--accepted", "domain_id": "ai", "name": "Accepted", "status": "seeded",
         "updated_at": seeding._now()}])
    found = seeding.changes()
    assert [(r["collection"], r["id"]) for r in found["items"]] == [("subdomains", "ai--accepted")]
    assert found["awaiting_review"] == {"subdomains": 1}
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/changes/count").json() == {"count": 1, "awaiting_review": {"subdomains": 1}}


def test_revert_puts_back_the_default(db, seeds):
    """Put back the default: edited back to the seed, added removed, deleted back; the tab empties."""
    seeding.load_if_new()
    seeded = get_collection("signals").find_one({"_id": "ipo"})["look_for"]
    _touch("signals", "ipo", look_for="edited live")
    get_collection("signals").insert_one({"_id": "new-one", "signal_id": "new-one", "name": "New one",
                                          "look_for": "y", "mode": "never_miss", "enabled": True,
                                          "updated_at": seeding._now()})
    get_collection("sources").delete_one({"_id": "ietf"})
    assert seeding.changes()["count"] == 3
    refs = [{"collection": "signals", "id": "ipo"}, {"collection": "signals", "id": "new-one"},
            {"collection": "sources", "id": "ietf"}]
    assert seeding.revert(refs) == {"put_back": 3}
    assert get_collection("signals").find_one({"_id": "ipo"})["look_for"] == seeded
    assert get_collection("signals").find_one({"_id": "new-one"}) is None
    assert get_collection("sources").find_one({"_id": "ietf"}) is not None
    assert seeding.changes()["count"] == 0
    assert seeding.load_if_new() is False   # the seed files are untouched


# ── SEED: a change in the code keeps edits made in the app ──────────

def test_code_change_loads_into_untouched_items(db, seeds):
    seeding.load_if_new()
    _code(seeds, "prompts", "scout", description="new in the code")
    _code(seeds, "sources", "arxiv", enabled=False)
    assert seeding.load_if_new() is True
    assert _live("prompts", "scout")["description"] == "new in the code"
    assert _live("sources", "arxiv")["enabled"] is False
    assert seeding.changes()["count"] == 0


def test_app_edit_survives_code_change_and_is_listed(db, seeds):
    seeding.load_if_new()
    _touch("signals", "ipo", look_for="edited live")
    _code(seeds, "signals", "ipo", look_for="new in the code")
    assert seeding.load_if_new() is True
    assert _live("signals", "ipo")["look_for"] == "edited live"
    row = next(r for r in seeding.changes()["items"] if r["id"] == "ipo")
    assert row["kind"] == "edited"
    assert row["fields"] == [{"field": "look_for", "seeding_value": "new in the code",
                              "live_value": "edited live"}]
    assert seeding.load_if_new() is False
    assert ("signals", "ipo", "edited") in _listed()                      # still listed after a restart


def test_kept_as_default_then_changed_in_code_loads(db, seeds):
    seeding.load_if_new()
    _touch("signals", "ipo", look_for="edited live")
    seeding.update_seeding_data([{"collection": "signals", "id": "ipo"}])
    assert seeding.changes()["count"] == 0
    _code(seeds, "signals", "ipo", look_for="new in the code")
    assert seeding.load_if_new() is True
    assert _live("signals", "ipo")["look_for"] == "new in the code"      # no false keep
    assert seeding.changes()["count"] == 0


def test_put_back_then_changed_in_code_loads(db, seeds):
    seeding.load_if_new()
    _touch("signals", "ipo", look_for="edited live")
    seeding.revert([{"collection": "signals", "id": "ipo"}])
    _code(seeds, "signals", "ipo", look_for="new in the code")
    assert seeding.load_if_new() is True
    assert _live("signals", "ipo")["look_for"] == "new in the code"
    assert seeding.changes()["count"] == 0


def test_removed_from_code_is_removed_and_app_added_survives(db, seeds):
    seeding.load_if_new()
    get_collection("signals").insert_one({"_id": "new-one", "signal_id": "new-one", "name": "New one",
                                          "look_for": "y", "mode": "never_miss", "enabled": True,
                                          "updated_at": seeding._now()})
    _code(seeds, "signals", "acquisition", remove=True)
    assert seeding.load_if_new() is True
    assert _live("signals", "acquisition") is None
    assert _live("signals", "new-one") is not None
    assert _listed() == {("signals", "new-one", "added")}


def test_removed_from_code_but_edited_in_app_stays(db, seeds):
    seeding.load_if_new()
    _touch("signals", "acquisition", look_for="edited live")
    _code(seeds, "signals", "acquisition", remove=True)
    assert seeding.load_if_new() is True
    assert _live("signals", "acquisition")["look_for"] == "edited live"
    assert _listed() == {("signals", "acquisition", "added")}


def test_proposals_awaiting_review_survive_a_load(db, seeds):
    seeding.load_if_new()
    get_collection("subdomains").insert_one(
        {"_id": "ai--proposed", "subdomain_id": "ai--proposed", "domain_id": "ai", "name": "Proposed",
         "status": "new", "updated_at": seeding._now()})
    get_collection("subdomains").update_one({"_id": "ai--ai_agents"}, {"$set": {"status": "new"}})
    _code(seeds, "subdomains", "ai--ai_agents", remove=True)
    assert seeding.load_if_new() is True
    assert _live("subdomains", "ai--proposed") is not None
    assert _live("subdomains", "ai--ai_agents") is not None               # awaiting review: never removed
    assert seeding.changes()["awaiting_review"] == {"subdomains": 2}


def test_deleted_in_app_stays_deleted(db, seeds):
    seeding.load_if_new()
    get_collection("signals").delete_one({"_id": "ipo"})
    _code(seeds, "signals", "ipo", look_for="new in the code")
    assert seeding.load_if_new() is True
    assert _live("signals", "ipo") is None
    assert _listed() == {("signals", "ipo", "deleted")}


def test_database_from_before_this_version_removes_nothing(db, seeds):
    seeding.load_if_new()
    get_collection("seeding").update_one({"_id": "state"}, {"$unset": {"ids": "", "kept": ""}})
    assert seeding.load_if_new() is False                                  # first start: ids recorded
    assert "ids" in seeding._state()
    get_collection("seeding").update_one({"_id": "state"}, {"$unset": {"ids": "", "kept": ""}})
    _code(seeds, "signals", "acquisition", remove=True)
    _code(seeds, "signals", "funding-round", look_for="new in the code")
    assert seeding.load_if_new() is True
    assert _live("signals", "acquisition") is not None                     # nothing removed
    assert _live("signals", "funding-round")["look_for"] == "new in the code"
    assert seeding._state()["ids"]["signals"] == [s["signal_id"] for s in seeding.read_list("signals")]


def test_database_from_before_this_version_keeps_no_written_item(db, seeds):
    """Edited, then written into the files before this version: after the first
    start on this version, the code's next change loads into it."""
    seeding.load_if_new()
    _touch("signals", "ipo", look_for="edited live")
    seeding.update_seeding_data([{"collection": "signals", "id": "ipo"}])
    get_collection("signals").update_many({}, {"$unset": {"seeded_at": ""}})
    get_collection("seeding").update_one({"_id": "state"}, {"$unset": {"ids": "", "kept": ""}})
    assert seeding.load_if_new() is False
    _code(seeds, "signals", "ipo", look_for="new in the code")
    assert seeding.load_if_new() is True
    assert _live("signals", "ipo")["look_for"] == "new in the code"
    assert seeding._state()["kept"] == []


def test_two_exports_at_once_both_land(db, seeds):
    seeding.load_if_new()
    _touch("prompts", "scout", description="first")
    _touch("prompts", "supervisor", description="second")
    start = threading.Barrier(2)

    def export(item_id):
        start.wait()
        seeding.update_seeding_data([{"collection": "prompts", "id": item_id}])

    threads = [threading.Thread(target=export, args=(i,)) for i in ("scout", "supervisor")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    written = {p["name"]: p["description"] for p in seeding.read_list("prompts")}
    assert written["scout"] == "first" and written["supervisor"] == "second"
    assert seeding.changes()["count"] == 0


def test_the_log_names_the_kept_items(db, seeds, caplog):
    seeding.load_if_new()
    _touch("signals", "ipo", look_for="edited live")
    _touch("prompts", "scout", description="edited live")
    _touch("signals", "acquisition")                                      # saved, but equal to the files
    _code(seeds, "signals", "funding-round", look_for="new in the code")
    with caplog.at_level(logging.INFO, logger=seeding.__name__):
        assert seeding.load_if_new() is True
    assert ("seeding data: loaded the code's changes; kept 2 edits made in the app "
            "(prompts/scout, signals/ipo); Setup › Changes lists them") in caplog.messages
