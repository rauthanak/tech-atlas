"""The path to scale's people side: the next rung's evidence, when it's in
hand, the notes held for it, and the execution bottlenecks. Finance figures
were removed (1 Nov 2026): a rung that needs one is never ticked."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import decisions, finance
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)


def _world(db):
    load_seeded(db, "path_steps", "fabrics")
    tech(db)


def test_the_next_rung_says_when_its_evidence_is_in_hand_and_gate_2_lists_it(db):
    _world(db)
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="customer_zero", tz="UTC")
    f = finance.figures("edge-ai", "cloud")
    assert f["next_step"]["name"] == "Proof of concept" and not f["next_step"]["in_hand"]
    assert [n["key"] for n in f["next_step"]["needs"]] == ["buyer", "budget", "price"]  # no exposed contracts: Cloud earns
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"buyer": "Acme's network director", "budget": "FY27 budget line", "price": 12})
    assert finance.figures("edge-ai", "cloud")["next_step"]["in_hand"] is True
    f = finance.figures("edge-ai", "cloud")
    assert f["price"]["value"] == 12 and f["notes"]["buyer"]["value"] == "Acme's network director"
    # One customer needs positive contribution and a payback estimate: figures the radar no longer keeps
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="proof_of_concept", tz="UTC")
    f = finance.figures("edge-ai", "cloud")
    assert f["next_step"]["name"] == "One customer" and not f["next_step"]["in_hand"]
    assert [(n["where"], n["have"]) for n in f["next_step"]["needs"]] == [("figures", False), ("figures", False)]


def test_exposed_contracts_are_asked_for_only_where_the_lever_protects(db):
    _world(db)
    decisions.create("path_step", "edge-ai", fabric_id="network", value="customer_zero", tz="UTC")
    assert "exposed_contracts" in [n["key"] for n in finance.figures("edge-ai", "network")["next_step"]["needs"]]


def test_gate_2_lists_a_technology_ready_for_the_next_step(db):
    from factories import assessment, page, run
    _world(db)
    page(db, "edge-ai-page", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=["edge-ai-page@1"])
    db["assessments"].update_one({"_id": "r1:edge-ai:cloud"}, {"$set": {"measures": {}}})
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="customer_zero", tz="UTC")
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC", value={"buyer": "b", "budget": "y", "price": 1})
    gate2 = {g["kind"]: g for g in client.get("/api/gates").json()["gate2"]}
    assert gate2["ready_next_step"]["technologies"][0]["steps"] == [
        {"fabric_id": "cloud", "fabric": "Cloud", "at": "Customer zero", "next": "Proof of concept"}]
    # the payload the fabric tab and the Point of View read carries it, and the bottlenecks picked
    decisions.create("bottlenecks", "edge-ai", fabric_id="cloud", tz="UTC", value={"picked": ["Migration and data integration"]})
    fin = client.get("/api/technologies/edge-ai/assessment", params={"fabric": "cloud"}).json()["finance"]
    assert fin["next_step"]["in_hand"] is True and fin["bottlenecks"]["picked"] == ["Migration and data integration"]


def test_bottlenecks_are_picked_from_the_fabrics_list(db):
    _world(db)
    with pytest.raises(decisions.Refused, match="not on this fabric's list"):
        decisions.create("bottlenecks", "edge-ai", fabric_id="cloud", tz="UTC", value={"picked": ["Weather"]})
    with pytest.raises(decisions.Refused, match="pick at least one"):
        decisions.create("bottlenecks", "edge-ai", fabric_id="cloud", tz="UTC", value={"picked": [], "other": " "})
    decisions.create("bottlenecks", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"picked": ["Migration and data integration"], "other": "GPU supply"})
    b = finance.figures("edge-ai", "cloud")["bottlenecks"]
    assert b["picked"] == ["Migration and data integration"] and b["other"] == "GPU supply" and b["decision"]["at"]


def test_finance_figures_are_gone_from_gate_2_and_the_point_of_view(db):
    from factories import assessment, page, run
    from agent.analyzer import pov
    from app.services import gates
    _world(db)
    page(db, "edge-ai-page", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=["edge-ai-page@1"])
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="proof_of_concept", tz="UTC")
    assert "finance_missing" not in {g["kind"] for g in client.get("/api/gates").json()["gate2"]}
    [o] = client.get("/api/technologies/edge-ai/summary").json()["open"]
    assert "finance_missing" not in o
    t = db["technologies"].find_one({"_id": "edge-ai"})
    applied = gates.latest_applied(["edge-ai"])["edge-ai"]
    assert "FINANCE" not in pov._extras(t, applied, decisions.active(["edge-ai"]), pov.Sources([]))
    assert client.get("/api/finance").status_code == 404


def test_a_finance_amount_is_refused(db):
    _world(db)
    with pytest.raises(decisions.Refused, match="margin"):
        decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC", value={"margin": 0.35})
