"""The value screen's people side for a technology in a fabric: the step
reached on its path to scale and whether the evidence for the next one is in
hand, and the execution bottlenecks people picked.

A rung's evidence (a named buyer, a budget, a price, a measured cost per
outcome, the exposed contracts) is kept in the pair's `finance` choice
(services/decisions); the name stays as stored. Finance figures
(contribution, payback, break-even) were removed (1 Nov 2026): Tata isn't
adding them, so a rung that needs one is never ticked by the radar.

The next rung: each path step seeds `needs` (keys of NEEDS). When every one
is in hand, the radar flags it: "Evidence for <step> is in hand" (Nick: act
when the evidence for the next rung is in hand, not when the market looks
large), and Gate 2 lists it (services/gates)."""

from app.services import decisions
from app.services.db.mongo import get_collection

# what a rung can need: its words, and where it comes from (the assessment,
# a note entered on the path to scale, or a figure the radar doesn't work out)
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
    """The step reached, the next rung and what it still needs, the notes
    held for it, and the bottlenecks picked."""
    decs = decisions.active([tech_id]) if decs is None else decs
    fabric = fabric or get_collection("fabrics").find_one({"_id": fabric_id}) or {}
    path = steps() if path is None else path
    step_d = decisions.pick(decs, "path_step", tech_id=tech_id, fabric_id=fabric_id)
    step = path.get(step_d["value"]) if step_d else None
    entered = decisions.pick(decs, "finance", tech_id=tech_id, fabric_id=fabric_id)
    v = (entered or {}).get("value") or {}
    src = {"source": "set for this technology", "at": entered["at"], "tz": entered.get("tz")} if entered else {}
    # the exposed contracts are asked for only where the fabric's contribution lever protects revenue
    protect = next(iter(fabric.get("levers") or []), {}).get("mechanism_id") == "protect"
    out: dict = {"step": {"id": step["_id"], "name": step["name"], "order": step["order"]} if step else None,
                 "step_decision": _brief(step_d), "entered": _brief(entered),
                 "price": {"value": v["price"], **src} if v.get("price") is not None else None,
                 "notes": {k: {"value": v[k], **src} if v.get(k) else None for k in NOTES}}

    # the next rung on the path to scale, and whether its evidence is in hand
    order = step["order"] if step else 0
    nxt = min((s for s in path.values() if s.get("order", 0) > order), key=lambda s: s["order"], default=None)
    out["next_step"] = None
    if nxt is not None:
        def got(key: str) -> bool:
            if key == "lever":
                cases = (assessment or {}).get("use_cases") if assessment is not None else _latest_use_cases(tech_id, fabric_id)
                return any(lv.get("pages") for uc in cases or [] for lv in uc.get("levers") or [])
            if NEEDS[key][1] == "figures":
                return False  # finance figures aren't kept
            return v.get(key) is not None if key == "price" else bool(v.get(key))
        keys = [k for k in nxt.get("needs") or [] if k in NEEDS and (k != "exposed_contracts" or protect)]
        needs = [{"key": k, "label": NEEDS[k][0], "where": NEEDS[k][1], "have": got(k)} for k in keys]
        out["next_step"] = {"id": nxt["_id"], "name": nxt["name"], "order": nxt["order"], "needs": needs,
                            "in_hand": bool(needs) and all(n["have"] for n in needs)}

    picked = decisions.pick(decs, "bottlenecks", tech_id=tech_id, fabric_id=fabric_id)
    out["bottlenecks"] = {**picked["value"], "decision": _brief(picked)} if picked else None
    return out
