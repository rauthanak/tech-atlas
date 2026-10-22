"""Publishing an edition: it freezes what leaders see (placements, Points of
View, assumptions, evidence) until the next publish; the next one says what
moved since, and why; and it waits while an assessment is running."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import decisions
from factories import assessment, page, run, tech
from factories import pov as written
from stacked_fakes import load_seeded

client = TestClient(app)


def publish(name: str | None = None):
    return client.post("/api/editions", json={"name": name} if name else None)


def _world(db, techs=("edge-ai", "quic")):
    load_seeded(db, "path_steps", "fabrics", "scoring_config", "measures", "assumptions", "availability", "domains",
                "subdomains", "trl_levels", "mechanisms")
    for t in techs:
        tech(db, t, t.replace("-", " "))
    run(db, "r1", 2, techs=techs)
    for t in techs:
        assessment(db, "r1", 2, pages=[page(db, f"{t}-a", 1, tech=t.replace("-", " "))], tech_id=t, priority="P3")
        written(db, "r1", 3, tech_id=t)
    db["assessments"].update_many({}, {"$set": {"placement.timeline": {"score": 6}, "placement.potential": {"score": 7}}})


def test_nothing_to_publish_says_why(db):
    r = publish()
    assert r.status_code == 409 and r.json()["detail"] == "Nothing to publish yet: no technology is assessed."


def test_an_edition_freezes_placements_povs_and_assumptions(db):
    _world(db)
    first = publish("FY27 Q2").json()["edition"]
    assert first["counts"] == {"placements": 2, "held": 0, "povs": 2, "moved": 0, "technologies": 2}
    # work goes on after publishing: a rewrite, an override, an edited assumption
    db["povs"].update_one({"_id": "r1:edge-ai"}, {"$set": {"sections.headline": "rewritten", "version": 2}})
    decisions.create("override", "edge-ai", fabric_id="cloud", value="P1", reason="board priority", tz="UTC",
                     computed="P3")
    db["assumptions"].update_many({}, {"$set": {"name": "changed"}})
    body = client.get("/api/frontier").json()
    assert {p["priority"] for p in body["placed"]} == {"P3"}  # leaders still see the edition
    assert body["assumptions"][0] == {"statement": "AI infrastructure investment stays high through FY27.",
                                      "date": "2026-09-26"}
    pov = client.get("/api/frontier/pov/edge-ai").json()
    assert pov["sections"]["headline"] == "h" and pov["edition"]["label"] == "FY27 Q2"
    assert pov["fabrics"][0]["leader"]["state"] == "undefined"  # what a leader recorded, beside each fabric

    second = publish().json()["edition"]
    assert second["previous"]["label"] == "FY27 Q2" and second["counts"]["moved"] == 1
    body = client.get("/api/frontier").json()
    moved = {p["tech_id"]: p.get("moved") for p in body["placed"]}
    assert moved == {"edge-ai": {"from": "P3", "by_person": True, "reason": "board priority"}, "quic": None}
    assert client.get("/api/frontier/pov/edge-ai").json()["sections"]["headline"] == "rewritten"
    assert [e["_id"] for e in client.get("/api/editions").json()["editions"]] == [second["_id"], first["_id"]]


def test_a_move_says_new_scores_or_override_undone(db):
    _world(db)
    override = decisions.create("override", "quic", fabric_id="cloud", value="P1", reason="r", tz="UTC", computed="P3")
    publish()
    decisions.deactivate(override["_id"], "UTC")
    db["assessments"].update_one({"tech_id": "edge-ai"}, {"$set": {"placement.priority": "P2"}})
    publish()
    moved = {p["tech_id"]: p["moved"] for p in client.get("/api/frontier").json()["placed"]}
    assert moved == {"edge-ai": {"from": "P3", "by_person": False, "reason": "new scores"},
                     "quic": {"from": "P1", "by_person": False, "reason": "a person's override was undone"}}


def test_a_technology_with_no_point_of_view_says_so(db):
    _world(db)
    db["povs"].delete_one({"_id": "r1:quic"})
    publish()
    r = client.get("/api/frontier/pov/quic")
    assert r.status_code == 404 and "has no Point of View of this technology" in r.json()["detail"]


def test_evidence_this_edition(db):
    _world(db, techs=("edge-ai",))
    db["sources"].insert_many([{"_id": "a", "name": "A", "enabled": True}, {"_id": "b", "name": "B", "enabled": False}])
    db["documents"].update_one({}, {"$set": {"signals": [{"signal_id": "funding-round", "name": "Funding round"}]}})
    publish()
    ev = client.get("/api/frontier").json()["evidence"]
    assert ev == {"sources_on": 1, "pages_read": 1, "signals_found": 1, "technologies": 1,
                  "by_signal_type": [{"signal_id": "funding-round", "name": "Funding round", "count": 1}]}
    assert client.get("/api/frontier").json()["near_band"] == 0.5


def test_publishing_waits_for_a_running_assessment(db):
    _world(db, techs=("edge-ai",))
    db["scoring_runs"].update_one({"_id": "r1"}, {"$set": {"status": "running"}})
    r = publish()
    assert r.status_code == 409 and r.json()["detail"].startswith("An assessment run is in progress. Publish when")
    assert client.get("/api/frontier").json() == {"edition": None}


def test_an_assumption_needs_its_date(db):
    r = client.post("/api/lists/assumptions", json={"name": "Spectrum auctions slip a year."})
    assert r.status_code == 422 and r.json()["detail"] == "an assumption needs the date it was stated"
    r = client.post("/api/lists/assumptions", json={"name": "Spectrum auctions slip a year.", "date": "2026-10-21"})
    assert r.status_code == 201 and r.json()["item"]["date"] == "2026-10-21"


def test_the_briefing_says_what_changed_since_the_edition(db):
    _world(db)
    assert client.get("/api/editions/since").json()["since"] is None  # nothing published yet
    publish("FY27 Q2")
    assert {k: v for k, v in client.get("/api/editions/since").json()["since"].items()
            if k in ("edition", "moved", "placed_new", "placed_gone", "povs_written")} == {
        "edition": "FY27 Q2", "moved": 0, "placed_new": 0, "placed_gone": 0, "povs_written": 0}
    decisions.create("override", "edge-ai", fabric_id="cloud", value="P1", reason="board priority", tz="UTC", computed="P3")
    db["povs"].update_one({"_id": "r1:quic"}, {"$set": {"composed_at": "2099-01-01T00:00:00+00:00"}})  # written after it
    since = client.get("/api/editions/since").json()["since"]
    assert since["moved"] == 1 and since["povs_written"] == 1
    assert since["now"] == {"placements": 2, "held": 0, "povs": 2}  # what a publish now would send


def test_a_point_of_view_says_which_version_leaders_see(db):
    _world(db)
    assert client.get("/api/editions/pov/quic").json() == {"edition": None, "composed_at": None, "composed_tz": None}
    publish("FY27 Q2")
    seen = client.get("/api/editions/pov/quic").json()
    assert seen["edition"]["label"] == "FY27 Q2" and seen["composed_at"] == db["povs"].find_one({"_id": "r1:quic"})["composed_at"]
    assert client.get("/api/editions/pov/nothing").json()["composed_at"] is None
