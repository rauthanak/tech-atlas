"""The finance screen: the arithmetic (Nick's protection and displacement
examples), where each figure came from, what's missing, when the card asks
for anything, the next rung's evidence, and the execution bottlenecks."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import decisions, finance, gates
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)


def _world(db):
    load_seeded(db, "path_steps", "fabrics")
    tech(db)
    db["fabrics"].update_one({"_id": "cloud"}, {"$set": {"finance_defaults": {"margin_low": 0.3, "margin_high": 0.4}}})


def test_nothing_needed_before_proof_of_concept_and_missing_inputs_named(db):
    _world(db)
    f = finance.figures("edge-ai", "cloud")
    assert f["needed"] is False and f["asks"] is False and f["margin"]["source"] == "fabric default, the middle of 30%–40%"
    assert f["missing"]["payback"] == ["upfront investment", "yearly running cost", "yearly revenue (or volume and price)"]
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="proof_of_concept", tz="UTC")
    assert finance.figures("edge-ai", "cloud")["needed"] is True


def test_the_arithmetic_and_where_each_figure_came_from(db):
    _world(db)
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"upfront": 1_000_000, "running": 100_000, "revenue": 1_200_000})
    f = finance.figures("edge-ai", "cloud")
    assert f["contribution"]["value"] == 420_000                  # 1.2M × 35%
    assert f["payback"]["value"] == round(1_000_000 / 320_000, 2)  # upfront ÷ (contribution − running)
    assert f["break_even"]["value"] == round(100_000 / 0.35, 2)    # running ÷ margin
    assert f["upfront"]["source"] == "set for this technology" and f["upfront"]["at"] and f["missing"] == {}
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"upfront": 1_000_000, "running": 500_000, "revenue": 1_000_000, "margin": 0.2})
    f = finance.figures("edge-ai", "cloud")
    assert f["margin"] == {"value": 0.2, "source": "set for this technology", "at": f["margin"]["at"], "tz": "UTC"}
    assert f["payback"]["value"] is None and "doesn't pay back" in f["payback"]["note"]


def test_a_protection_lever_counts_only_the_difference_in_loss_rates(db):
    """Nick's PQC example: 20 contracts × $2.0m at 35%, 30% lost without, 10% with."""
    _world(db)
    f = finance.figures("edge-ai", "network")
    assert f["mechanism"]["value"] == "protect"          # Network's contribution lever protects
    db["fabrics"].update_one({"_id": "network"}, {"$set": {"finance_defaults": {"loss_without": 0.3, "loss_with": 0.1}}})
    decisions.create("finance", "edge-ai", fabric_id="network", tz="UTC",
                     value={"revenue": 40_000_000, "margin": 0.35, "upfront": 4_000_000, "running": 500_000})
    f = finance.figures("edge-ai", "network")
    assert f["contribution"]["value"] == 2_800_000 and f["contribution"]["label"] == "Contribution protected, a year"
    assert f["payback"]["value"] == 1.74 and f["payback"]["months"] == 21
    assert f["loss_without"] == {"value": 0.3, "source": "fabric default"}
    assert f["break_even"]["value"] == round(500_000 / (0.35 * 0.2), 2)
    # without loss rates, it says so rather than counting the whole revenue
    db["fabrics"].update_one({"_id": "network"}, {"$set": {"finance_defaults": {}}})
    f = finance.figures("edge-ai", "network")
    assert "contribution" not in f and "loss rates with and without it" in f["missing"]["contribution"]


def test_volume_times_price_and_the_revenue_it_displaces(db):
    """Nick's Interaction example: 1.2m tasks a year at $0.50, 40% margin; the voice
    minutes it removes carried $0.12 of contribution a task ($360k of revenue at 40%)."""
    _world(db)
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"volume": 1_200_000, "price": 0.5, "margin": 0.4, "displaced": 360_000, "running": 10_000})
    f = finance.figures("edge-ai", "cloud")
    assert f["revenue"]["value"] == 600_000 and f["revenue"]["source"] == "volume × price, set for this technology"
    assert f["contribution"]["value"] == 96_000 and f["contribution"]["label"] == "Net contribution, a year"  # $8k a month
    assert f["break_even"]["value"] == 10_000 / 0.4 + 360_000 and f["break_even"]["volume"] == round(385_000 / 0.5)


def test_the_next_rung_says_when_its_evidence_is_in_hand_and_gate_2_lists_it(db):
    _world(db)
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="customer_zero", tz="UTC")
    f = finance.figures("edge-ai", "cloud")
    assert f["asks"] is True and f["needed"] is False      # Proof of concept needs what the card holds
    assert f["next_step"]["name"] == "Proof of concept" and not f["next_step"]["in_hand"]
    assert [n["key"] for n in f["next_step"]["needs"]] == ["buyer", "budget", "price"]  # no exposed contracts: Cloud earns
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"buyer": "Acme's network director", "budget": "FY27 budget line", "price": 12})
    assert finance.figures("edge-ai", "cloud")["next_step"]["in_hand"] is True
    # One customer needs positive contribution after running costs and a payback estimate
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="proof_of_concept", tz="UTC")
    assert finance.figures("edge-ai", "cloud")["next_step"]["in_hand"] is False
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC",
                     value={"revenue": 1_000_000, "upfront": 500_000, "running": 100_000})
    f = finance.figures("edge-ai", "cloud")
    assert f["next_step"]["name"] == "One customer" and f["next_step"]["in_hand"] is True


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
    rows = client.get("/api/finance").json()["rows"]
    assert [(r["tech_id"], r["fabric_id"]) for r in rows] == [("edge-ai", "cloud")]
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


def test_a_margin_above_one_is_refused(db):
    _world(db)
    try:
        decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC", value={"margin": 35})
        raise AssertionError("expected a refusal")
    except decisions.Refused as exc:
        assert "at most 1" in str(exc)


def test_finance_set_aside_asks_for_nothing_and_a_rungs_note_alone_never_does(db, monkeypatch):
    from factories import assessment, page, run
    from agent.analyzer import pov
    _world(db)
    page(db, "edge-ai-page", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=["edge-ai-page@1"])
    decisions.create("finance", "edge-ai", fabric_id="cloud", tz="UTC", value={"cost_per_outcome": "$4 a ticket, was $9"})
    assert finance.figures("edge-ai", "cloud")["needed"] is False  # a note for the next rung isn't a business case
    decisions.create("path_step", "edge-ai", fabric_id="cloud", value="proof_of_concept", tz="UTC")
    kinds = lambda: {g["kind"] for g in client.get("/api/gates").json()["gate2"]}
    [o] = client.get("/api/technologies/edge-ai/summary").json()["open"]
    assert finance.SHOWN is False and "finance_missing" not in kinds() and o["finance_missing"] == []
    t = db["technologies"].find_one({"_id": "edge-ai"})
    applied = gates.latest_applied(["edge-ai"])["edge-ai"]
    assert "FINANCE" not in pov._extras(t, applied, decisions.active(["edge-ai"]), pov.Sources([]))
    monkeypatch.setattr(finance, "SHOWN", True)  # brought back: Gate 2 asks for its figures again
    assert "finance_missing" in kinds()
    assert "FINANCE" in pov._extras(t, applied, decisions.active(["edge-ai"]), pov.Sources([]))
