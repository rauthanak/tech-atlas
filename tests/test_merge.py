"""Merging technologies (code review CR04): the absorbed technology's choices
in force move to the one kept, unless it has its own on the same thing (then
its own is kept, and the merge says which); catalog membership moves; history
stays where it was; running a merge again after a stop is safe."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import decisions
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)


def _world(db):
    load_seeded(db, "availability", "domains", "subdomains", "trl_levels", "measures", "fabrics")
    tech(db, "a", "agent ai")
    tech(db, "b", "ai agents")
    decisions.create("move", "a", field="availability", value="mature", tz="UTC")
    decisions.create("move", "b", field="availability", value="pilot", tz="UTC")
    decisions.create("move", "b", field="trl", value=6, tz="UTC")
    decisions.create("commitment", "b", fabric_id="cloud", value={"owner": "Priya", "next_action": "pilot", "due": "2026-12-01"}, tz="UTC")


def _active(db, tech_id):
    return {(d["kind"], d.get("field"), d.get("fabric_id")): d for d in db["decisions"].find({"tech_id": tech_id, "active": True})}


def test_merge_moves_the_absorbed_choices_and_names_the_conflicts(db):
    _world(db)
    r = client.post("/api/technologies/a/merge", json={"others": ["b"]})
    assert r.status_code == 200
    merge = r.json()["merge"]
    assert merge["absorbed"] == [{"id": "b", "name": "ai agents"}] and merge["choices_moved"] == 2
    assert merge["conflicts"] == [{"kept": "Commercial availability set to Mature",
                                   "dropped": "Commercial availability set to Pilot", "from": "ai agents"}]
    on_a = _active(db, "a")
    assert on_a[("move", "availability", None)]["value"] == "mature"          # its own is kept
    assert on_a[("move", "trl", None)]["value"] == 6 and ("commitment", None, "cloud") in on_a
    assert db["decisions"].count_documents({"tech_id": "b"}) == 0              # nothing left on the deleted id
    dropped = db["decisions"].find_one({"value": "pilot"})
    assert not dropped["active"] and dropped["merged_from"] == "b" and dropped["replaced_at"]   # History shows it
    assert db["technologies"].find_one({"_id": "b"}) is None


def test_merge_carries_catalog_membership_when_the_target_lacks_it(db):
    _world(db)
    db["technologies"].update_one({"_id": "b"}, {"$set": {"origin": "imported", "imported": {"import_id": "i1"}}})
    assert client.post("/api/technologies/a/merge", json={"others": ["b"]}).json()["merge"]["catalog_carried"]
    a = db["technologies"].find_one({"_id": "a"})
    assert a["origin"] == "imported" and a["imported"] == {"import_id": "i1"}
    assert decisions.in_catalog(a, None)["in"]


def test_a_target_keeps_its_own_catalog_record(db):
    _world(db)
    db["technologies"].update_one({"_id": "a"}, {"$set": {"origin": "imported", "imported": {"import_id": "mine"}}})
    db["technologies"].update_one({"_id": "b"}, {"$set": {"origin": "imported", "imported": {"import_id": "theirs"}}})
    assert not client.post("/api/technologies/a/merge", json={"others": ["b"]}).json()["merge"]["catalog_carried"]
    assert db["technologies"].find_one({"_id": "a"})["imported"] == {"import_id": "mine"}


def test_merge_leaves_history_where_it_was(db):
    _world(db)
    db["assessments"].insert_one({"_id": "r:b:cloud", "tech_id": "b", "fabric_id": "cloud"})
    db["povs"].insert_one({"_id": "r:b", "tech_id": "b"})
    db["edition_povs"].insert_one({"_id": "e1:b", "tech_id": "b"})
    client.post("/api/technologies/a/merge", json={"others": ["b"]})
    for c in ("assessments", "povs", "edition_povs"):
        assert db[c].find_one()["tech_id"] == "b"


def test_a_merge_stopped_part_way_can_be_run_again(db, monkeypatch):
    from pymongo.collection import Collection
    _world(db)
    real, calls = Collection.delete_many, []

    def stop_once(self, *a, **k):
        if self.name == "technologies" and not calls:
            calls.append(1)
            raise RuntimeError("stopped")
        return real(self, *a, **k)
    monkeypatch.setattr(Collection, "delete_many", stop_once)
    try:
        client.post("/api/technologies/a/merge", json={"others": ["b"]})
    except RuntimeError:
        pass
    assert client.post("/api/technologies/a/merge", json={"others": ["b"]}).status_code == 200
    on_a = list(db["decisions"].find({"tech_id": "a", "active": True}))
    assert len(on_a) == len({(d["kind"], d.get("field"), d.get("fabric_id")) for d in on_a}) == 3
    assert db["technologies"].find_one({"_id": "b"}) is None


def test_two_absorbed_with_the_same_choice_the_first_wins(db):
    _world(db)
    tech(db, "c", "agentic ai")
    decisions.create("move", "c", field="trl", value=3, tz="UTC")
    merge = client.post("/api/technologies/a/merge", json={"others": ["b", "c"]}).json()["merge"]
    assert _active(db, "a")[("move", "trl", None)]["value"] == 6
    assert merge["conflicts"][-1] == {"kept": "Readiness (TRL) set to TRL 6", "dropped": "Readiness (TRL) set to TRL 3",
                                      "from": "agentic ai"}
