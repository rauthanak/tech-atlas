"""What a leader records for a technology in a fabric (deck p.13): an owner
and a next action with its date, then resources; the state follows from what
is recorded, each step needing the one before."""

from fastapi.testclient import TestClient

from app.main import app
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)


def record(value: dict, fabric: str | None = "cloud"):
    return client.post("/api/decisions", json={"kind": "commitment", "tech_id": "edge-ai", "fabric_id": fabric,
                                               "value": value})


def state() -> dict:
    return client.get("/api/decisions/leader", params={"tech_id": "edge-ai", "fabric_id": "cloud"}).json()


def test_a_record_needs_an_owner_a_next_action_and_its_date(db):
    tech(db)
    r = record({"owner": "A. Nimbhorkar"})
    assert r.status_code == 422
    assert r.json()["detail"] == ("a record needs an owner, a next action and its date: "
                                  "the next action and its date are missing")
    assert record({"owner": "x", "next_action": "y", "due": "next week"}).json()["detail"] == \
        "the next action's date is a day, like 2026-11-15"
    assert record({"owner": "x", "next_action": "y", "due": "2026-11-15"}, fabric=None).status_code == 422


def test_the_state_follows_what_is_recorded(db):
    load_seeded(db, "path_steps", "fabrics")
    tech(db)
    assert (state()["state"], state()["needs"]) == ("undefined", "an owner and a next action, with its date")
    assert record({"owner": "A. Nimbhorkar", "next_action": "Pilot with one bank", "due": "2026-11-15",
                   "people": "  "}).status_code == 201
    got = state()
    assert (got["state"], got["owner"], got["people"]) == ("defined", "A. Nimbhorkar", None)
    assert got["needs"] == "the step Tata has reached and the blockers recorded"
    client.post("/api/decisions", json={"kind": "path_step", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "value": "evaluation"})
    assert state()["needs"] == "the blockers recorded"
    blocker = db["fabrics"].find_one({"_id": "cloud"})["bottlenecks"][0]
    client.post("/api/decisions", json={"kind": "bottlenecks", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "value": {"picked": [blocker]}})
    assert (state()["state"], state()["needs"]) == ("aligned", "resources: people, budget or a proof of concept")
    assert record({"owner": "A. Nimbhorkar", "next_action": "Pilot with one bank", "due": "2026-11-15",
                   "budget": "$250k in FY27"}).status_code == 201
    got = state()
    assert (got["state"], got["needs"], got["budget"]) == ("integrated", None, "$250k in FY27")
    # Undo withdraws the record (the one it replaced stays on file, inactive)
    client.delete(f"/api/decisions/{got['decision']['_id']}")
    assert state()["state"] == "undefined"
