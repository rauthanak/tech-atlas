"""A person owns a sign to watch (services/watch): their threshold shows and
reaches the next assessment as fixed; their "not crossed" takes the sign off
the Briefing; Undo puts the radar's back. A sign is known by its wording."""

from fastapi.testclient import TestClient

from agent.analyzer import engine
from app.main import app
from app.services import watch
from factories import assessment, tech

client = TestClient(app)
ARR = {"metric": "Agentforce ARR", "current_value": "$2.3B", "inflection_threshold": "$2B", "crossed": True,
       "previous_value": "$1.5B", "source": "https://a.example/q3"}


def _crossed(db):
    tech(db, "edge-ai", "edge ai")
    assessment(db, "r1", 1)
    db["assessments"].update_many({}, {"$set": {"watch_metrics": [ARR]}})
    return client.get("/api/scoring/crossed").json()["crossed"]


def test_a_sign_is_known_by_its_wording():
    assert watch.sign_key("Agentforce ARR") == watch.sign_key("  agentforce   arr ")
    assert watch.sign_key("Agentforce ARR") != watch.sign_key("Agentforce revenue")


def test_a_persons_threshold_shows_and_the_next_assessment_keeps_it(db):
    key = _crossed(db)[0]["key"]
    made = client.post("/api/decisions", json={"kind": "watch_threshold", "tech_id": "edge-ai", "key": key,
                                                "value": "$3B in annual revenue"})
    assert made.status_code == 201
    row = client.get("/api/scoring/crossed").json()["crossed"][0]
    assert row["inflection_threshold"] == "$3B in annual revenue" and row["model_threshold"] == "$2B"
    assert row["threshold_by"]["decision_id"] == made.json()["decision"]["_id"]
    told = engine.previous_watch("edge-ai", "r9")
    assert "$3B in annual revenue (set by a person: keep it exactly as written)" in told
    client.delete(f"/api/decisions/{made.json()['decision']['_id']}")
    assert client.get("/api/scoring/crossed").json()["crossed"][0]["inflection_threshold"] == "$2B"


def test_not_crossed_takes_it_off_the_briefing_and_undo_puts_it_back(db):
    key = _crossed(db)[0]["key"]
    made = client.post("/api/decisions", json={"kind": "watch_crossed", "tech_id": "edge-ai", "key": key, "value": "no"})
    assert made.status_code == 201
    assert client.get("/api/scoring/crossed").json()["crossed"] == []
    client.delete(f"/api/decisions/{made.json()['decision']['_id']}")
    assert len(client.get("/api/scoring/crossed").json()["crossed"]) == 1


def test_a_sign_choice_needs_its_sign(db):
    tech(db, "edge-ai", "edge ai")
    assert client.post("/api/decisions", json={"kind": "watch_crossed", "tech_id": "edge-ai", "value": "no"}).status_code == 422
    assert client.post("/api/decisions", json={"kind": "watch_threshold", "tech_id": "edge-ai", "key": "w:1",
                                               "value": "  "}).status_code == 422
