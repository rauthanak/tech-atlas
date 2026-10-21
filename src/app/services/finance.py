"""The value screen's people side for a technology in a fabric: the finance
figures (entered by people, worked out by code, never by the model), the step
reached on its path to scale and whether the evidence for the next one is in
hand, and the execution bottlenecks people picked.

Inputs: the fabric's defaults (Setup › Fabrics: a margin range, loss rates)
and, for the pair, a `finance` choice (services/decisions): upfront
investment, yearly running cost, yearly revenue (or volume × price), the
revenue it displaces, and a margin or loss rates that override the defaults.

Nick's note sets the arithmetic, by how the revenue counts (`mechanism`: the
choice's, else the fabric's contribution lever's):
  protect   contribution protected = revenue at stake × margin
                                     × (loss rate without − loss rate with)
            (only the difference in loss rates is protected, never the
            whole revenue: that overstates it, five-fold in his example)
  earn      contribution = (revenue − revenue it displaces) × margin
  payback     = upfront ÷ (contribution − running)        (years)
  break-even  = the yearly revenue whose contribution covers the running
                cost (plus what it displaces)

Each figure says where it came from, with the date it was set, and a missing
input is named. The card asks for figures from Proof of concept on (where a
buyer, a budget and a price first exist), or once a step is set and the next
rung needs something the card holds.

The next rung: each path step seeds `needs` (keys of NEEDS). When every one
is in hand, the radar flags it: "Evidence for <step> is in hand" (Nick: act
when the evidence for the next rung is in hand, not when the market looks
large), and Gate 2 lists it (services/gates)."""

from app.services import decisions
from app.services.db.mongo import get_collection

POC = "proof_of_concept"
# what a rung can need: its words, and where it comes from (the assessment,
# a note or figure entered on the finance card, or a figure code works out)
NEEDS = {
    "lever": ("a use case with a named lever and its chain", "assessment"),
    "cost_per_outcome": ("measured cost per outcome against the current process", "finance"),
    "buyer": ("a named buyer", "finance"),
    "budget": ("a budget or willingness to pay", "finance"),
    "price": ("an indicative price", "finance"),
    "exposed_contracts": ("the exposed contracts and their renewal dates", "finance"),  # protection levers only
    "positive_contribution": ("positive contribution after running costs", "figures"),
    "payback": ("a payback estimate", "figures"),
}
NOTES = {"buyer": "named buyer", "budget": "budget or willingness to pay",
         "exposed_contracts": "exposed contracts and renewal dates", "cost_per_outcome": "measured cost per outcome"}


def steps() -> dict[str, dict]:
    return {s["_id"]: s for s in get_collection("path_steps").find()}


def _latest_use_cases(tech_id: str, fabric_id: str) -> list[dict]:
    a = get_collection("assessments").find_one({"tech_id": tech_id, "fabric_id": fabric_id}, {"use_cases": 1},
                                                sort=[("created_at", -1)])
    return (a or {}).get("use_cases") or []


def _brief(d: dict | None) -> dict | None:
    return {k: d.get(k) for k in ("_id", "at", "tz", "reason")} if d else None


def figures(tech_id: str, fabric_id: str, decs: list[dict] | None = None, fabric: dict | None = None,
            path: dict | None = None, assessment: dict | None = None) -> dict:
    decs = decisions.active([tech_id]) if decs is None else decs
    fabric = fabric or get_collection("fabrics").find_one({"_id": fabric_id}) or {}
    path = steps() if path is None else path
    step_d = decisions.pick(decs, "path_step", tech_id=tech_id, fabric_id=fabric_id)
    step = path.get(step_d["value"]) if step_d else None
    poc = path.get(POC, {}).get("order", 3)
    entered = decisions.pick(decs, "finance", tech_id=tech_id, fabric_id=fabric_id)
    v = (entered or {}).get("value") or {}
    src = lambda what="set for this technology": {"source": what, "at": entered["at"], "tz": entered.get("tz")}
    mine = lambda k: {"value": v[k], **src()} if v.get(k) is not None else None

    defaults = fabric.get("finance_defaults") or {}
    margin = mine("margin")
    if margin is None and defaults.get("margin_low") is not None and defaults.get("margin_high") is not None:
        lo, hi = defaults["margin_low"], defaults["margin_high"]
        margin = {"value": round((lo + hi) / 2, 4), "source": f"fabric default, the middle of {lo:.0%}–{hi:.0%}"}
    elif margin is None and (defaults.get("margin_low") is not None or defaults.get("margin_high") is not None):
        m = defaults.get("margin_low") if defaults.get("margin_low") is not None else defaults.get("margin_high")
        margin = {"value": m, "source": "fabric default"}
    loss = {k: mine(k) or ({"value": defaults[k], "source": "fabric default"} if defaults.get(k) is not None else None)
            for k in ("loss_without", "loss_with")}
    lever1 = next(iter(fabric.get("levers") or []), {})
    mechanism = ({"value": v["mechanism"], **src()} if v.get("mechanism") else
                 {"value": "protect" if lever1.get("mechanism_id") == "protect" else "earn",
                  "source": f"{fabric.get('name', 'the fabric')}'s contribution lever"})
    protect = mechanism["value"] == "protect"
    revenue = mine("revenue")
    if revenue is None and v.get("volume") is not None and v.get("price") is not None:
        revenue = {"value": round(v["volume"] * v["price"], 2), **src("volume × price, set for this technology")}
    displaced = mine("displaced") if not protect else None
    inputs = {k: mine(k) for k in ("upfront", "running", "volume", "price")}
    names = {"margin": "margin", "upfront": "upfront investment", "running": "yearly running cost",
             "revenue": "yearly revenue at stake (or volume and price)" if protect else "yearly revenue (or volume and price)",
             "loss": "loss rates with and without it"}
    have = {**inputs, "margin": margin, "revenue": revenue,
            "loss": True if not protect or (loss["loss_without"] and loss["loss_with"]) else None}
    need = lambda *keys: [names[k] for k in keys if have[k] is None]

    out: dict = {"step": {"id": step["_id"], "name": step["name"], "order": step["order"]} if step else None,
                 "step_decision": _brief(step_d),
                 "needed": bool(step and step["order"] >= poc) or bool(entered),
                 "entered": _brief(entered), "mechanism": mechanism, "margin": margin, "revenue": revenue,
                 "displaced": displaced, **inputs, **loss,
                 "notes": {k: {"value": v[k], **src()} if v.get(k) else None for k in NOTES}, "missing": {}}
    # the yearly contribution each unit of revenue brings: margin, times the share protected
    per = None
    if not need("margin", "loss"):
        per = margin["value"] * ((loss["loss_without"]["value"] - loss["loss_with"]["value"]) if protect else 1)
    less = displaced["value"] if displaced else 0
    if per is not None and revenue is not None:
        out["contribution"] = {
            "value": round((revenue["value"] - less) * per, 2),
            "label": "Contribution protected, a year" if protect else "Net contribution, a year" if displaced else "Contribution, a year",
            "formula": "revenue at stake × margin × (loss rate without − loss rate with)" if protect else
                       "(revenue − revenue it displaces) × margin" if displaced else "revenue × margin, a year"}
    else:
        out["missing"]["contribution"] = need("revenue", "margin", "loss")
    if "contribution" in out and not need("upfront", "running"):
        net = out["contribution"]["value"] - inputs["running"]["value"]
        out["payback"] = ({"value": round(inputs["upfront"]["value"] / net, 2), "unit": "years",
                           "months": round(12 * inputs["upfront"]["value"] / net),
                           "formula": "upfront ÷ (contribution − running cost)"} if net > 0 else
                          {"value": None, "note": "It doesn't pay back at these figures: contribution doesn't cover the running cost."})
    else:
        out["missing"]["payback"] = need("upfront", "running", "revenue", "margin", "loss")
    if per is not None and not need("running"):
        if per > 0:
            be = inputs["running"]["value"] / per + less
            out["break_even"] = {"value": round(be, 2),
                                 "label": "Break-even revenue at stake, a year" if protect else "Break-even revenue, a year",
                                 "formula": ("running cost ÷ (margin × (loss rate without − loss rate with))" if protect else
                                             "running cost ÷ margin + revenue it displaces" if displaced else "running cost ÷ margin, a year"),
                                 **({"volume": round(be / inputs["price"]["value"])} if inputs["price"] and inputs["price"]["value"] > 0 else {})}
        else:
            out["break_even"] = {"value": None, "note": "No break-even: with these loss rates nothing is protected." if protect and margin["value"] > 0
                                 else "No break-even at a zero margin."}
    else:
        out["missing"]["break_even"] = need("running", "margin", "loss")

    # the next rung on the path to scale, and whether its evidence is in hand
    order = step["order"] if step else 0
    nxt = min((s for s in path.values() if s.get("order", 0) > order), key=lambda s: s["order"], default=None)
    out["next_step"] = None
    if nxt is not None:
        def got(key: str) -> bool:
            if key == "lever":
                cases = (assessment or {}).get("use_cases") if assessment is not None else _latest_use_cases(tech_id, fabric_id)
                return any(lv.get("pages") for uc in cases or [] for lv in uc.get("levers") or [])
            if key == "price":
                return inputs["price"] is not None
            if key == "positive_contribution":
                return "contribution" in out and inputs["running"] is not None and \
                    out["contribution"]["value"] > inputs["running"]["value"]
            if key == "payback":
                return (out.get("payback") or {}).get("value") is not None
            return bool(v.get(key))
        keys = [k for k in nxt.get("needs") or [] if k in NEEDS and (k != "exposed_contracts" or protect)]
        needs = [{"key": k, "label": NEEDS[k][0], "where": NEEDS[k][1], "have": got(k)} for k in keys]
        out["next_step"] = {"id": nxt["_id"], "name": nxt["name"], "order": nxt["order"], "needs": needs,
                            "in_hand": bool(needs) and all(n["have"] for n in needs)}
    # the card asks once a step is set and the next rung needs what it holds
    out["asks"] = out["needed"] or bool(step and out["next_step"] and any(
        n["where"] != "assessment" and not n["have"] for n in out["next_step"]["needs"]))

    picked = decisions.pick(decs, "bottlenecks", tech_id=tech_id, fabric_id=fabric_id)
    out["bottlenecks"] = {**picked["value"], "decision": _brief(picked)} if picked else None
    return out
