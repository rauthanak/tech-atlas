"""Frontier: the latest published edition, never live data. Placements with
overrides applied, the not-yet-placed with the reason, switched-off
technologies never shown, the Disruption threat for the Defence lens, and
what a leader recorded with its state."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import decisions
from factories import assessment, page, run, tech
from stacked_fakes import load_seeded

client = TestClient(app)


def publish(name: str | None = None) -> dict:
    r = client.post("/api/editions", json={"name": name}, headers={"X-Time-Zone": "Asia/Kolkata"})
    assert r.status_code == 201, r.text
    return r.json()["edition"]


def test_nothing_published_says_so(db):
    assert client.get("/api/frontier").json() == {"edition": None}
    r = client.get("/api/frontier/pov/edge-ai")
    assert r.status_code == 404 and "No edition is published yet" in r.json()["detail"]


def test_overrides_reasons_and_switched_off(db):
    load_seeded(db, "path_steps", "fabrics", "scoring_config")
    tech(db)
    tech(db, "quic", "quic")
    tech(db, "old", "old tech", enabled=False)
    run(db, "r1", 2, techs=("edge-ai", "quic", "old"), gates={"edge-ai": ["cloud"], "quic": ["cloud"], "old": ["cloud"]})
    for t in ("edge-ai", "quic", "old"):
        assessment(db, "r1", 2, pages=[page(db, f"{t}-a", 1, tech=t.replace("-", " ") if t != "old" else "old tech")],
                   tech_id=t, priority="P3" if t != "quic" else None)
    db["assessments"].update_many({"tech_id": {"$ne": "quic"}}, {"$set": {"placement.timeline": {"score": 6},
                                                                          "placement.potential": {"score": 7}}})
    db["assessments"].update_one({"tech_id": "quic"}, {"$set": {"placement.timeline": {"score": None},
                                                                "placement.potential": {"score": 5}}})
    decisions.create("override", "edge-ai", fabric_id="cloud", value="P1", reason="board priority", tz="UTC",
                     computed="P3")
    edition = publish("FY27 Q3")
    assert (edition["label"], edition["tz"], edition["previous"]) == ("FY27 Q3", "Asia/Kolkata", None)
    body = client.get("/api/frontier").json()
    assert body["edition"]["_id"] == edition["_id"]
    assert [(p["tech_id"], p["priority"], p["computed_priority"], p["override"]) for p in body["placed"]] == \
        [("edge-ai", "P1", "P3", True)]
    assert body["held"][0]["tech_id"] == "quic" and body["held"][0]["reason"] == "How soon couldn't be scored from the evidence"
    assert all(r["tech_id"] != "old" for r in body["placed"] + body["held"])
    assert client.get("/api/frontier", params={"fabric": "network"}).json()["placed"] == []


def test_each_placement_carries_its_stage(db):
    load_seeded(db, "path_steps", "fabrics", "scoring_config", "availability", "domains", "trl_levels")
    tech(db)
    tech(db, "quic", "quic")
    run(db, "r1", 2, techs=("edge-ai", "quic"), gates={"edge-ai": ["cloud"], "quic": ["cloud"]})
    for t in ("edge-ai", "quic"):
        assessment(db, "r1", 2, pages=[page(db, f"{t}-a", 1, tech=t.replace("-", " "))], tech_id=t, priority="P3")
    db["assessments"].update_many({}, {"$set": {"placement.timeline": {"score": 6}, "placement.potential": {"score": 7}}})
    decisions.create("move", "quic", field="availability", value="mature", reason="sold widely", tz="UTC")
    publish()
    body = client.get("/api/frontier").json()
    stage = {p["tech_id"]: p["stage"] for p in body["placed"]}
    assert stage["quic"] == {"id": "mature", "name": "Mature", "emerging": False, "known": True}
    assert stage["edge-ai"] == {"id": "unclassified", "name": "Unclassified", "emerging": False, "known": False}
    assert [s["id"] for s in body["stages"]] == ["research", "pilot", "early_commercial", "mature", "unclassified"]


def test_disruption_threat_for_the_defence_lens(db):
    load_seeded(db, "path_steps", "fabrics", "scoring_config", "measures")
    tech(db)
    tech(db, "quic", "quic")
    tech(db, "sase", "sase")
    run(db, "r1", 2, techs=("edge-ai", "quic", "sase"))
    for t in ("edge-ai", "quic", "sase"):
        assessment(db, "r1", 2, pages=[page(db, f"{t}-a", 1, tech=t)], tech_id=t, priority="P3")
    db["assessments"].update_many({}, {"$set": {"placement.timeline": {"score": 6}, "placement.potential": {"score": 7},
                                                "measures.disruption-threat": {"code": "X1", "score": None}}})
    decisions.create("tata_entry", "edge-ai", fabric_id="cloud", measure_id="disruption-threat", value=8,
                     reason="private-line revenue at risk", tz="UTC")
    decisions.create("accept_gap", "sase", fabric_id="cloud", measure_id="disruption-threat", value=True, tz="UTC")
    publish()
    body = client.get("/api/frontier").json()  # Tata's entry places the scores again: edge-ai may be held
    got = {p["tech_id"]: (p["threat"], p["threat_missing"]) for p in body["placed"] + body["held"]}
    assert got == {"edge-ai": (8.0, None), "quic": (None, "Disruption threat not entered by Tata yet"),
                   "sase": (None, "Disruption threat left out: a person accepted the gap")}


def test_what_a_leader_records_is_frozen_with_its_state(db):
    load_seeded(db, "path_steps", "fabrics", "scoring_config")
    tech(db)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[page(db, "a", 1)], priority="P3")
    db["assessments"].update_many({}, {"$set": {"placement.timeline": {"score": 6}, "placement.potential": {"score": 7}}})
    decisions.create("commitment", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"owner": "A. Nimbhorkar", "next_action": "Pilot with one bank", "due": "2026-11-15"})
    publish()
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="evaluation", tz="UTC")  # after: not in the edition
    leader = client.get("/api/frontier").json()["placed"][0]["leader"]
    assert (leader["state"], leader["owner"], leader["due"]) == ("defined", "A. Nimbhorkar", "2026-11-15")
    assert leader["needs"] == "the step Tata has reached and the blockers recorded"
