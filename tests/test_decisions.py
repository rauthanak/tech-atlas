"""People's choices: required reasons, a new choice replacing the old, a hand
score placing a held pair, an override and its moved flag, undo, and the
Before publishing list."""

from fastapi.testclient import TestClient

from app.main import app
from factories import page, pov, run, tech
from stacked_fakes import load_seeded

client = TestClient(app)
WHY = {"X-Time-Zone": "Asia/Kolkata"}


def _assessed(db, scores: dict, fabric="cloud", tech_id="edge-ai", run_id="r1"):
    """A latest assessment with these measure scores (None: unscored); the rest unscored."""
    measures = list(db["measures"].find())
    rows = {m["_id"]: {"code": m["code"], "score": scores.get(m["_id"]), "unscorable": scores.get(m["_id"]) is None,
                       "evidence_urls": ["u"] if scores.get(m["_id"]) is not None else [],
                       "missing": "the pages don't show it"} for m in measures}
    from agent.analyzer.placement import compute_placement
    from agent.analyzer.engine import rollup_tora
    config = list(db["scoring_config"].find())
    db["assessments"].insert_one({"_id": f"{run_id}:{tech_id}:{fabric}", "scoring_run_id": run_id, "tech_id": tech_id,
                                  "technology": tech_id, "fabric_id": fabric, "fabric": fabric.title(),
                                  "created_at": "2026-09-02T00:00:00+00:00", "doc_count": 1, "evidence_runs": ["c"],
                                  "dossier_pages": [f"{tech_id}-page@1"], "measures": rows,
                                  "tora": rollup_tora(rows, measures), "placement": compute_placement(rows, config)})


def _setup(db, scores):
    load_seeded(db, "measures", "scoring_config")
    tech(db)
    page(db, "edge-ai-page", 1)
    run(db, "r1", 2)
    _assessed(db, scores)


def _get(fabric="cloud"):
    return client.get("/api/technologies/edge-ai/assessment", params={"fabric": fabric}).json()["assessment"]


def test_a_reason_is_required_where_it_matters(db):
    _setup(db, {})
    r = client.post("/api/decisions", json={"kind": "override", "tech_id": "edge-ai", "fabric_id": "cloud", "value": "P1"})
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    r = client.post("/api/decisions", json={"kind": "hand_score", "tech_id": "edge-ai", "fabric_id": "cloud",
                                            "measure_id": "growth", "value": 11, "reason": "x"})
    assert r.status_code == 422 and "0 to 10" in r.json()["detail"]
    r = client.post("/api/decisions", json={"kind": "tata_entry", "tech_id": "edge-ai", "fabric_id": "cloud",
                                            "measure_id": "growth", "value": 5, "reason": "x"})
    assert r.status_code == 422 and "score it by hand" in r.json()["detail"]


def test_a_hand_score_places_a_held_pair_and_undo_holds_it_again(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7})  # how soon scored, how big not
    a = _get()
    assert a["effective"]["priority"] is None and a["measures"]["growth"]["state"] == "unscored"
    r = client.post("/api/decisions", json={"kind": "hand_score", "tech_id": "edge-ai", "fabric_id": "cloud",
                                            "measure_id": "growth", "value": 8, "reason": "IDC sizing we hold"},
                    headers=WHY).json()["decision"]
    assert r["fabric_id"] is None and r["tz"] == "Asia/Kolkata"  # growth is judged for the technology as a whole
    a = _get()
    assert a["measures"]["growth"]["state"] == "scored_by_person" and a["measures"]["growth"]["score"] == 8
    assert a["effective"]["priority"] is not None
    client.delete(f"/api/decisions/{r['_id']}")
    assert _get()["effective"]["priority"] is None


def test_the_run_page_and_the_points_of_view_list_show_what_a_hand_score_places(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7})  # how soon scored, how big not
    pov(db, "r1", 3)

    def shown():
        a = client.get("/api/scoring/runs/r1/rows").json()["rows"][0]  # the run's table, a page at a time
        placed = client.get("/api/scoring/povs").json()["povs"][0]["placements"][0]
        return a["placement"]["priority"], placed["priority"], placed["computed_priority"]

    assert shown() == (None, None, None)
    client.post("/api/decisions", json={"kind": "hand_score", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "measure_id": "growth", "value": 8, "reason": "IDC sizing we hold"})
    priority = _get()["effective"]["priority"]
    assert priority is not None and shown() == (priority, priority, priority)


def test_an_override_wins_keeps_the_computed_one_and_flags_a_move(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7, "growth": 8, "addressable-market": 8})
    computed = _get()["effective"]["computed_priority"]
    client.post("/api/decisions", json={"kind": "override", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "value": "P6", "reason": "not for us this year"})
    e = _get()["effective"]
    assert e["priority"] == "P6" and e["computed_priority"] == computed and e["override"]["reason"]
    assert e["override_moved"] is False
    # a later run computes something else (and stores its placement, as a run does)
    from agent.analyzer.placement import compute_placement
    a = db["assessments"].find_one()
    a["measures"]["growth"]["score"] = a["measures"]["addressable-market"]["score"] = 1
    db["assessments"].update_one({}, {"$set": {"measures": a["measures"],
                                               "placement": compute_placement(a["measures"], list(db["scoring_config"].find()))}})
    e = _get()["effective"]
    assert e["priority"] == "P6" and e["override_moved"] is True and e["computed_priority"] != computed
    second = client.post("/api/decisions", json={"kind": "override", "tech_id": "edge-ai", "fabric_id": "cloud",
                                                 "value": "P5", "reason": "revisited"}).json()["decision"]
    assert db["decisions"].count_documents({"kind": "override", "active": True}) == 1  # the new one replaced it
    assert _get()["effective"]["priority"] == "P5"
    client.delete(f"/api/decisions/{second['_id']}")
    assert _get()["effective"]["priority"] == _get()["effective"]["computed_priority"]


def test_the_before_publishing_list_counts_technologies_blocking_first(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7})            # edge-ai: held
    tech(db, "quic", "quic")
    db["scoring_runs"].update_one({"_id": "r1"}, {"$push": {"technologies": {"tech_id": "quic", "name": "quic"}},
                                                  "$set": {"gates.quic": ["cloud"]}})
    _assessed(db, {"maturity-trl": 7, "commercial-adoption": 7, "growth": 8, "addressable-market": 8,
                   "fabric-fit": 6}, tech_id="quic")                       # quic: placed, gaps left
    gate2 = {g["kind"]: g for g in client.get("/api/gates").json()["gate2"]}
    assert gate2["unscored"]["count"] == 2
    assert [t["tech_id"] for t in gate2["unscored"]["technologies"]] == ["edge-ai", "quic"]  # blocking first
    assert gate2["unscored"]["technologies"][0]["blocking"] == [{"fabric_id": "cloud", "fabric": "Cloud"}]
    assert gate2["waiting_for_tata"]["count"] == 2  # disruption threat and serviceable capture
    # accepting every gap takes it off the list
    for mid, r in _get_for("quic")["measures"].items():
        if r["state"] == "unscored":
            client.post("/api/decisions", json={"kind": "accept_gap", "tech_id": "quic", "fabric_id": "cloud",
                                                "measure_id": mid})
    gate2 = {g["kind"]: g for g in client.get("/api/gates").json()["gate2"]}
    assert [t["tech_id"] for t in gate2["unscored"]["technologies"]] == ["edge-ai"]


def _get_for(tech_id):
    return client.get(f"/api/technologies/{tech_id}/assessment").json()["assessment"]


def test_the_technology_page_lists_what_is_still_open_in_each_fabric(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7})
    load_seeded(db, "fabrics", "path_steps")
    [o] = client.get("/api/technologies/edge-ai/summary").json()["open"]
    assert o["fabric_id"] == "cloud" and o["unscored"] > 0 and o["blocking"] is True
    assert o["waiting_for_tata"] == 2 and not o["owner"] and not o["blockers"] and o["step"] is None
    assert o["leader"] == "undefined" and not o["resources"]
    client.post("/api/decisions", json={"kind": "commitment", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "value": {"owner": "A. Rao", "next_action": "a pilot", "due": "2026-12-01"}})
    client.post("/api/decisions", json={"kind": "path_step", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "value": "evaluation"})
    [o] = client.get("/api/technologies/edge-ai/summary").json()["open"]
    assert o["owner"] and o["step"] == "Evaluation" and o["leader"] == "defined"  # the blockers aren't recorded yet
    assert o["next_step"]["name"] == "Customer zero" and o["next_step"]["missing"]


def test_a_technology_history_says_each_choice_in_plain_words(db):
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7})
    load_seeded(db, "fabrics", "path_steps")
    client.post("/api/decisions", json={"kind": "path_step", "tech_id": "edge-ai", "fabric_id": "cloud", "value": "evaluation"})
    client.post("/api/decisions", json={"kind": "override", "tech_id": "edge-ai", "fabric_id": "cloud", "value": "P3",
                                        "reason": "a pilot is funded"})
    ds = client.get("/api/decisions", params={"tech_id": "edge-ai", "include_inactive": True}).json()["decisions"]
    assert [d["what"] for d in ds] == ["Priority in Cloud set to P3", "Step reached in Cloud: Evaluation"]  # held: nothing computed
    assert ds[0]["from_file"] is None


def test_the_run_table_comes_a_page_at_a_time_counted_by_cell(db):
    """P2-5: the run's own answer is a summary; its table is filtered, counted
    by grid cell, sorted and paged on the server; a person's priority wins."""
    _setup(db, {"maturity-trl": 7, "commercial-adoption": 7, "growth": 8, "addressable-market": 8})
    run = client.get("/api/scoring/runs/r1").json()
    assert "assessments" not in run and run["assessed"] == 1 and run["fabrics"][0]["id"] == "cloud"
    body = client.get("/api/scoring/runs/r1/rows").json()
    assert body["total"] == body["scoped"] == 1 and sum(body["grid"].values()) == 1
    row = body["rows"][0]
    assert "use_cases" not in row and "watch_metrics" not in row and "measures" not in row
    cell = next(iter(body["grid"]))
    assert client.get("/api/scoring/runs/r1/rows", params={"cell": cell}).json()["total"] == 1
    assert client.get("/api/scoring/runs/r1/rows", params={"cell": "far_low" if cell != "far_low" else "near_high"}).json()["total"] == 0
    assert client.get("/api/scoring/runs/r1/rows", params={"q": "nothing like it"}).json()["scoped"] == 0
    assert client.get("/api/scoring/runs/r1/rows", params={"skip": 1}).json()["rows"] == []
    client.post("/api/decisions", json={"kind": "override", "tech_id": "edge-ai", "fabric_id": "cloud",
                                        "value": "P6", "reason": "not for us this year"})
    row = client.get("/api/scoring/runs/r1/rows").json()["rows"][0]
    assert row["placement"]["priority"] == "P6" and row["override"]["priority"] == "P6"


# ── one choice in force per thing chosen (code review CR03) ──────────

def _active(db):
    return list(db["decisions"].find({"active": True}))


def test_a_failed_save_keeps_the_choice_in_force(db, monkeypatch):
    from factories import tech
    tech(db)
    from pymongo.collection import Collection
    from pymongo.errors import PyMongoError
    from app.services import decisions
    first = decisions.create("move", "edge-ai", field="trl", value=5, tz="UTC")
    real = Collection.insert_one

    def fail(self, doc, *a, **k):
        if self.name == "decisions":
            raise PyMongoError("the database went away")
        return real(self, doc, *a, **k)
    monkeypatch.setattr(Collection, "insert_one", fail)
    try:
        decisions.create("move", "edge-ai", field="trl", value=6, tz="UTC")
    except PyMongoError:
        pass
    assert [d["_id"] for d in _active(db)] == [first["_id"]]


def test_a_newer_choice_saved_first_stays_in_force(db):
    from factories import tech
    tech(db)
    from app.services import decisions
    db["decisions"].insert_one({"_id": "zzz", "kind": "move", "tech_id": "edge-ai", "fabric_id": None,
                                "measure_id": None, "field": "trl", "key": None, "value": 4,
                                "at": "2999-01-01T00:00:00+00:00", "active": True})
    doc = decisions.create("move", "edge-ai", field="trl", value=6, tz="UTC")
    assert doc["active"] is False and [d["_id"] for d in _active(db)] == ["zzz"]


def test_many_saves_at_once_leave_one_choice(db):
    from factories import tech
    tech(db)
    import threading
    from app.services import decisions
    threads = [threading.Thread(target=decisions.create, args=("move", "edge-ai"),
                                kwargs={"field": "trl", "value": 1 + i, "tz": "UTC"}) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = list(db["decisions"].find())
    newest = max(rows, key=lambda d: (d["at"], d["_id"]))
    assert [d["_id"] for d in _active(db)] == [newest["_id"]]


def test_start_up_keeps_the_newest_of_duplicate_choices(db):
    from app.services.db import bootstrap
    base = {"kind": "move", "tech_id": "edge-ai", "fabric_id": None, "measure_id": None, "field": "availability",
            "active": True}
    db["decisions"].insert_many([
        {"_id": "old", **base, "value": "pilot", "at": "2026-10-01T00:00:00+00:00"},          # no `key` at all
        {"_id": "new", **base, "key": None, "value": "mature", "at": "2026-10-02T00:00:00+00:00"},
        {"_id": "other", **base, "tech_id": "quic", "value": "pilot", "at": "2026-10-01T00:00:00+00:00"}])
    bootstrap.dedupe_decisions()
    assert sorted(d["_id"] for d in _active(db)) == ["new", "other"]
    assert db["decisions"].find_one({"_id": "old"})["replaced_at"]
