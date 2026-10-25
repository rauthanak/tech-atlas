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
    assert moved == {"edge-ai": {"from": "P3", "by_person": False, "reason": "new scores", "why": None},
                     "quic": {"from": "P1", "by_person": False, "reason": "a person's override was undone", "why": None}}


def test_a_move_says_which_score_moved_and_leaders_see_why_the_priority(db):
    """E2, E3, E5: each placement carries its evidence word and pages; a move
    names the score that moved and the new pages; an edition published before
    moves carried that gets it from the edition before; the Point of View's
    fabrics carry how soon, how big and its band, as the edition holds them."""
    _world(db)
    db["assessments"].update_many({}, {"$set": {"doc_count": 10}})
    publish()
    db["assessments"].update_one({"tech_id": "edge-ai"}, {"$set": {"placement.priority": "P2", "doc_count": 50,
                                                                  "placement.potential": {"score": 8}}})
    publish()
    placed = {p["tech_id"]: p for p in client.get("/api/frontier").json()["placed"]}
    assert placed["edge-ai"]["moved"]["why"] == "how big 7 → 8 after 40 new pages"
    assert placed["edge-ai"]["pages"] == 50 and "evidence" in placed["edge-ai"]
    # an edition from before moves carried a why: worked out when read
    db["edition_rows"].update_many({}, {"$unset": {"moved.why": ""}})
    again = {p["tech_id"]: p for p in client.get("/api/frontier").json()["placed"]}
    assert again["edge-ai"]["moved"]["why"] == "how big 7 → 8 after 40 new pages"
    fabric = client.get("/api/frontier/pov/edge-ai").json()["fabrics"][0]
    assert fabric["placement"] == {"how_soon": 6, "how_big": 8, "big_band": "high"}


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
    assert client.get("/api/editions/pov/quic").json() == {"edition": None, "composed_at": None, "composed_tz": None,
                                                          "views": None}
    publish("FY27 Q2")
    seen = client.get("/api/editions/pov/quic").json()
    assert seen["edition"]["label"] == "FY27 Q2" and seen["composed_at"] == db["povs"].find_one({"_id": "r1:quic"})["composed_at"]
    assert client.get("/api/editions/pov/nothing").json()["composed_at"] is None


def test_an_edition_keeps_each_placement_apart_and_older_ones_still_read(db):
    """Rule 3: an edition's record stays small, its placements one record each;
    an edition published before that, with them inside, reads the same."""
    _world(db)
    e = publish().json()["edition"]
    doc = db["editions"].find_one({"_id": e["_id"]})
    assert "placed" not in doc and doc["rows"] == "separate"
    assert db["edition_rows"].count_documents({"edition_id": e["_id"], "kind": "placed"}) == 2
    new = client.get("/api/frontier").json()
    # the same edition as it was kept before: placements inside
    placed = list(db["edition_rows"].find({"edition_id": e["_id"], "kind": "placed"}, {"_id": 0, "edition_id": 0, "kind": 0, "n": 0}).sort("n", 1))
    db["edition_rows"].delete_many({})
    db["editions"].update_one({"_id": e["_id"]}, {"$set": {"placed": placed, "held": []}, "$unset": {"rows": ""}})
    old = client.get("/api/frontier").json()
    assert old["placed"] == new["placed"] and old["held"] == new["held"]
    assert client.get("/api/frontier", params={"fabric": "cloud"}).json()["placed"] == [p for p in new["placed"] if p["fabric_id"] == "cloud"]


def test_a_publish_reads_each_latest_assessment_from_the_answers_kept_ready(db):
    """The same assessments as working each technology's state out from its pages."""
    from app.services import evidence, gates, tech_status
    _world(db)
    run(db, "r2", 5, techs=("edge-ai",))                  # a newer assessment of one of them
    assessment(db, "r2", 5, tech_id="edge-ai", priority="P1")
    from_pages = gates.latest_applied(all_states=evidence.states())
    kept = gates.applied(tech_status.latest_assessments())
    assert {t: [a["_id"] for a in rows] for t, rows in kept.items()} == \
        {t: [a["_id"] for a in rows] for t, rows in from_pages.items()}
    assert kept["edge-ai"][0]["scoring_run_id"] == "r2"
