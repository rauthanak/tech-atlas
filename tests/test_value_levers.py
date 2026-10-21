"""Where the value lands (Nick's value note): two levers per use case in the
fabric's order, each with its mechanism, a lever without pages marked
"evidence needed", the capital required on every use case, the key metrics
sent to the model, no figures, a failure that keeps its reason, and the
fabric's blockers the pages show, suggested for a person to confirm."""

import pytest

from agent.analyzer import value
from stacked_fakes import load_seeded

PAGES = ["p1", "p2", "p3"]


def _fabric(db, fabric_id="network"):
    load_seeded(db, "fabrics", "mechanisms")
    return db["fabrics"].find_one({"_id": fabric_id}), value.mechanisms()


def _lever(lever_id, pages=(1,), **kw):
    return {"lever_id": lever_id, "mechanism_id": "protect", "operating_change": "meets the renewal requirement",
            "metric": "incidents per service", "financial_effect": "contribution protected",
            "evidence_needed": "named contracts with renewal dates", "next_step_when": "a customer confirms it",
            "pages": list(pages), **kw}


def _case(levers, capital=None):
    return {"title": "quantum-safe links at renewal", "pages": [1], "levers": levers,
            "capital": capital if capital is not None else {"direction": "light", "why": "software on the existing network"}}


def test_two_levers_in_the_fabrics_order_each_with_its_mechanism(db):
    fabric, mechs = _fabric(db)
    out = value.check(fabric, mechs, PAGES)(
        {"use_cases": [_case([_lever("network_delivery_cost", mechanism_id="nonsense"), _lever("network_contribution")])]}, None)
    levers = out["use_cases"][0]["levers"]
    assert [lv["lever_id"] for lv in levers] == ["network_contribution", "network_delivery_cost"]  # lever 1, then lever 2
    assert [lv["order"] for lv in levers] == [1, 2]
    assert levers[0]["mechanism_id"] == "protect" and levers[1]["mechanism_id"] == "reduce_cost"  # unknown → the fabric's
    assert levers[0]["pages"] == ["p1"] and levers[0]["evidence"] == "cited"
    assert out["use_cases"][0]["capital"] == {"direction": "light", "why": "software on the existing network"}


def test_a_missing_lever_or_capital_is_refused_with_the_reason(db):
    fabric, mechs = _fabric(db)
    check = value.check(fabric, mechs, PAGES)
    with pytest.raises(ValueError, match=r"leaves out lever 2 \(Delivery cost\)"):
        check({"use_cases": [_case([_lever("network_contribution")])]}, None)
    with pytest.raises(ValueError, match="no capital required"):
        check({"use_cases": [_case([_lever("network_contribution"), _lever("network_delivery_cost")], {"direction": "light"})]}, None)
    with pytest.raises(ValueError, match="wrote a figure"):
        check({"use_cases": [_case([_lever("network_contribution", financial_effect="35% more"),
                                    _lever("network_delivery_cost")])]}, None)


def test_a_lever_the_pages_dont_show_says_what_evidence_is_needed(db):
    fabric, mechs = _fabric(db)
    check = value.check(fabric, mechs, PAGES)
    out = check({"use_cases": [_case([_lever("network_contribution"), _lever("network_delivery_cost", pages=())])]}, None)
    assert out["use_cases"][0]["levers"][1]["evidence"] == "needed"
    with pytest.raises(ValueError, match="cites no page and doesn't say what evidence is needed"):
        check({"use_cases": [_case([_lever("network_contribution"),
                                    _lever("network_delivery_cost", pages=(), evidence_needed="")])]}, None)


def test_the_model_is_sent_the_two_levers_and_the_key_metrics(db):
    fabric, mechs = _fabric(db)
    sent = value.task_values(fabric, mechs)["fabric_levers"]
    assert sent.startswith("- Lever 1, contribution — network_contribution:")
    assert "- Lever 2, delivery cost — network_delivery_cost:" in sent
    assert "Key metrics: Engineering hours per connection" in sent


def test_a_failure_keeps_its_reason(db):
    stored = value.fields(value.failed("the reply left this task out"))
    assert stored == {"use_cases": [], "no_use_case": None, "suggested_use_cases": [], "suggested_bottlenecks": [],
                      "value_failed": "the reply left this task out"}
    assert value.fields({"use_cases": [], "no_use_case": None, "suggested": []})["value_failed"] is None


def test_blockers_the_pages_show_are_suggested_and_a_malformed_one_is_left_out(db):
    fabric, mechs = _fabric(db)
    assert value.task_values(fabric, mechs)["fabric_blockers"] == \
        "- Compatibility with the installed network and vendors\n- Customer qualification and procurement"
    good = {"name": "Customer qualification and procurement", "why": "Buyers run long qualification.",
            "quote": "a nine-month qualification cycle", "page": 2}
    out = value.check(fabric, mechs, PAGES)({
        "use_cases": [_case([_lever("network_contribution"), _lever("network_delivery_cost")])],
        "blockers": [good, {**good},                                     # the same one twice: kept once
                     {**good, "name": "Not on the fabric's list"},
                     {**good, "name": "Compatibility with the installed network and vendors", "quote": ""},
                     {**good, "name": "Compatibility with the installed network and vendors", "page": 9},
                     "nonsense"]}, None)
    assert out["blockers"] == [{**good, "page": "p2"}]
    assert len(out["use_cases"]) == 1                                     # use cases stand whatever the blockers say
    assert value.fields(out)["suggested_bottlenecks"] == [{**good, "page": "p2"}]
    assert value.check(fabric, mechs, PAGES)({"use_cases": []}, None)["blockers"] == []


def test_two_levers_with_miscopied_ids_are_taken_in_the_order_asked_for(db):
    fabric, mechs = _fabric(db)
    check = value.check(fabric, mechs, PAGES)
    out = check({"use_cases": [_case([_lever("lever 1's id"), _lever("lever 2's id", metric="hours per ticket")])]}, None)
    assert [lv["lever_id"] for lv in out["use_cases"][0]["levers"]] == ["network_contribution", "network_delivery_cost"]
    assert out["use_cases"][0]["levers"][1]["metric"] == "hours per ticket"
    with pytest.raises(ValueError, match=r"leaves out lever 2"):  # one right id and one wrong: still refused
        check({"use_cases": [_case([_lever("network_contribution"), _lever("something else")])]}, None)
