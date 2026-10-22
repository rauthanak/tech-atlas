"""The technology page in one call, and the Points of View list's extras."""

from fastapi.testclient import TestClient

from app.main import app
from factories import assessment, at, page, pov, run, tech

client = TestClient(app)  # no lifespan: nothing is seeded


def test_a_run_that_stopped_partway_offers_resume_and_keeps_the_previous_results(db):
    db["measures"].insert_many([{"_id": "m1"}, {"_id": "m2"}])
    db["fabrics"].insert_many([{"_id": "cloud", "enabled": True}, {"_id": "network", "enabled": True}])
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    run(db, "r2", 3, status="terminated", gates={"edge-ai": ["cloud", "network"]})
    body = client.get("/api/technologies/edge-ai/summary").json()
    assert body["state"] == "stopped_partway"
    assert body["unfinished"]["scoring_run_id"] == "r2" and body["unfinished"]["status"] == "terminated"
    assert body["assessment"]["scoring_run_id"] == "r1"
    assert [f["fabric_id"] for f in body["assessment"]["fabrics"]] == ["cloud"]
    assert body["assessment"]["fabrics"][0]["placement"] == {"priority": "P2", "horizon": "H1"}  # says why one is missing
    # the last gate chose 2 fabrics: 2 + 2 measures x 2 fabrics
    assert body["estimate"] == {"assess_calls": 6, "assess_calls_max": 6, "write_calls": 1}


def test_an_older_point_of_view_and_the_pages_new_since_it(db):
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    pov(db, "r1", 2)
    b1 = page(db, "b", 3)
    run(db, "r2", 4)
    assessment(db, "r2", 4, pages=[a1, b1])
    page(db, "c", 5)

    body = client.get("/api/technologies/edge-ai/summary").json()
    assert body["state"] == "new_evidence"
    assert body["pov"]["scoring_run_id"] == "r1" and body["pov"]["from_latest_assessment"] is False
    assert body["new_pages"]["since_assessment"] == 1 and body["new_pages"]["since_pov"] == 2
    assert [p["url"] for p in body["new_pages"]["recent"]] == ["c"]
    docs = client.get("/api/technologies/edge-ai/documents").json()["documents"]
    assert {d["end_url"]: d["new"] for d in docs} == {"a": False, "b": False, "c": True}
    page(db, "a", 6, stub_of=a1)  # a collected again, unchanged: still one page, its newest copy
    body = client.get("/api/technologies/edge-ai/documents").json()
    assert body["total"] == 3 and [d["end_url"] for d in body["documents"]] == ["a", "c", "b"]
    assert {d["end_url"]: (d["copies"], d["new"]) for d in body["documents"]} == {
        "a": (2, False), "b": (1, False), "c": (1, True)}

    povs = client.get("/api/scoring/povs").json()
    assert povs["povs"][0]["new_since_written"] == 2
    assert povs["povs"][0]["assessed_at"] == at(2)  # the assessment it was written from, not the newest
    assert povs["povs"][0]["placements"] == [{"fabric_id": "cloud", "fabric": "Cloud",
                                              "priority": "P2", "computed_priority": "P2", "override": None,
                                              "horizon": "H1"}]
    assert povs["uncomposed"] == [] and povs["assessed"] == 1  # waits to be assessed, not written


def test_the_fabrics_it_was_not_assessed_in(db):
    tech(db)
    run(db, "r1", 2, fabrics=("cloud", "iot", "network"))  # its gate chose cloud
    assessment(db, "r1", 2, pages=[page(db, "a", 1)])
    pov(db, "r1", 3)
    body = client.get("/api/technologies/edge-ai/summary").json()
    assert body["assessment"]["not_assessed_in"] == ["Iot", "Network"]
    assert client.get("/api/scoring/runs/r1/pov/edge-ai").json()["not_assessed_in"] == ["Iot", "Network"]


def test_an_unknown_technology(db):
    assert client.get("/api/technologies/nope/summary").status_code == 404


def test_the_register_by_state_filtered_before_paging(db):
    tech(db)                                            # assessed, then a new page: new evidence
    tech(db, "quic", "quic")                            # no run included it: not assessed
    tech(db, "old", "old tech", enabled=False)          # switched off
    db["technologies"].update_one({"_id": "quic"}, {"$set": {"page_count": 2}})
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    page(db, "b", 3)
    body = client.get("/api/technologies").json()
    rows = {t["_id"]: (t["state"], t["new_pages"], t["pov"]) for t in body["technologies"]}
    assert rows == {"edge-ai": ("new_evidence", 1, None), "quic": ("not_assessed", 2, None),
                    "old": ("off", 0, None)}
    assert body["state_counts"] == {"new_evidence": 1, "not_assessed": 1, "off": 1}
    assert next(t for t in body["technologies"] if t["_id"] == "edge-ai")["assessed_at"]
    only = client.get("/api/technologies", params={"state": "new_evidence", "limit": 1}).json()
    assert [t["_id"] for t in only["technologies"]] == ["edge-ai"] and only["total"] == 1
    assert only["state_counts"] == body["state_counts"]  # counts cover the search, not the filter
    assert client.get("/api/technologies", params={"state": "bogus"}).status_code == 422


def test_never_assessed_technologies_that_reached_the_last_page_bar(db):
    db["measures"].insert_one({"_id": "m1"})
    db["fabrics"].insert_one({"_id": "cloud", "enabled": True})
    tech(db)                                            # the run below assesses it
    tech(db, "quic", "quic")                            # 3 pages since: over the bar
    tech(db, "lifi", "li-fi")                           # 1 page: under it
    tech(db, "old", "old tech", enabled=False)          # switched off: never offered
    db["technologies"].update_many({"_id": {"$in": ["quic", "old"]}}, {"$set": {"page_count": 3}})
    db["technologies"].update_one({"_id": "lifi"}, {"$set": {"page_count": 1}})
    assert client.get("/api/technologies").json()["over_floor"] is None  # no run by page count yet

    run(db, "r1", 2, params={"min_docs": 3})
    assessment(db, "r1", 2, pages=[page(db, "a", 1)])
    assert client.get("/api/technologies").json()["over_floor"] == {
        "min_pages": 3, "started_at": "2026-09-02T00:00:00+00:00", "tech_ids": ["quic"],
        "technologies": 1, "calls": 3, "calls_max": 3}  # 2 + 1 measure x 1 fabric

    run(db, "r2", 4, status="running", techs=("quic",), params={"technologies": ["quic"]})
    assert client.get("/api/technologies").json()["over_floor"] is None  # being assessed now


def test_the_register_says_what_each_assessment_came_to(db):
    tech(db)
    tech(db, "quic", "quic")                            # never assessed: nothing to say
    run(db, "r1", 2, gates={"edge-ai": ["cloud", "network"]}, fabrics=("cloud", "network"))
    a1 = page(db, "a", 1)
    assessment(db, "r1", 2, pages=[a1], scores=[7, None, 5])                      # placed
    assessment(db, "r1", 2, pages=[a1], fabric="network", scores=[None, None, 4], priority=None)
    rows = {t["_id"]: t for t in client.get("/api/technologies").json()["technologies"]}
    assert rows["edge-ai"]["measures"] == {"scored": 3, "of": 6}
    assert rows["edge-ai"]["priorities"] == [{"fabric_id": "cloud", "fabric": "Cloud", "priority": "P2", "override": False},
                                             {"fabric_id": "network", "fabric": "Network", "priority": None, "override": False}]
    assert rows["quic"]["measures"] is None and rows["quic"]["priorities"] == []
    assert client.get("/api/technologies").json()["no_priority_counts"] == {}  # placed in cloud
    db["assessments"].update_one({"_id": "r1:edge-ai:cloud"}, {"$set": {"placement.priority": None}})
    assert client.get("/api/technologies").json()["no_priority_counts"] == {"no_pov": 1}
    summary = client.get("/api/technologies/edge-ai/summary").json()["assessment"]
    assert summary["measures"] == {"scored": 3, "of": 6}
    assert [f["measures"] for f in summary["fabrics"]] == [{"scored": 2, "of": 3}, {"scored": 1, "of": 3}]
