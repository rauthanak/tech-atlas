"""The two to-do lists, read off the latest assessments with people's
choices applied (services/effective):

  Before scoring (Gate 1)      what to settle before a technology is assessed
                               (filled in by services/radar_status)
  Before publishing (Gate 2)   what to settle before a Point of View goes to
                               leaders: unscored measures, measures waiting for
                               Tata, overrides whose computed priority moved, …

Counted by technology, never by measure, and ordered so that what blocks a
placement comes first."""

from app.services import decisions, evidence
from app.services import effective as eff
from app.services.db.mongo import get_collection


def latest_applied(tech_ids: list[str] | None = None, all_states: dict | None = None,
                   chosen: list[dict] | None = None) -> dict[str, list[dict]]:
    """Each technology's latest assessment, fabric by fabric, as people left
    it (`chosen`: their choices in force, when already read)."""
    states = all_states if all_states is not None else evidence.states(tech_ids)
    ids = [f["assessment_id"] for s in states.values() if s.get("assessment") for f in s["assessment"]["fabrics"]]
    if not ids:
        return {}
    rows = list(get_collection("assessments").find({"_id": {"$in": ids}}))
    measures = list(get_collection("measures").find())
    config = list(get_collection("scoring_config").find())
    chosen = decisions.active(sorted({r["tech_id"] for r in rows})) if chosen is None else chosen
    out: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda a: a["fabric_id"]):
        out.setdefault(r["tech_id"], []).append(eff.apply(r, chosen, measures, config))
    return out


def _best(fabrics: list[dict]) -> str:
    return min((f["effective"]["priority"] for f in fabrics if f["effective"]["priority"]), default="P9")


MATURITY = "maturity-trl"


def trl_band(level: int) -> str:
    return "low" if level <= 3 else "mid" if level <= 6 else "high"


def score_band(score: float) -> str:
    """The Maturity measure's anchors: 0–2 ↔ TRL 1–3, 5 ↔ TRL 4–6, 8–10 ↔ TRL 7–9."""
    return "low" if score < 3.5 else "mid" if score < 6.5 else "high"


def gate2(all_states: dict | None = None) -> list[dict]:
    all_states = evidence.states() if all_states is None else all_states
    on = {i: s for i, s in all_states.items() if s["state"] != "off"}  # switched off: nothing to publish
    chosen = decisions.active([i for i, s in on.items() if s.get("assessment")])
    applied = latest_applied(all_states=on, chosen=chosen)
    items: dict[str, list[dict]] = {"unscored": [], "waiting_for_tata": [], "override_moved": [], "maturity_mismatch": [],
                                    "suggested_use_cases": [], "finance_missing": [], "ready_next_step": []}
    from app.services import finance
    path = finance.steps()
    from app.services import classify_effective
    lists = classify_effective.names()
    techs = {t["_id"]: t for t in get_collection("technologies").find(
        {"_id": {"$in": list(applied)}}, {"label": 1, "name": 1, "classification": 1, "assessed_classification": 1})}
    for tech_id, fabrics in applied.items():
        name = (techs[tech_id].get("label") or techs[tech_id]["name"]) if tech_id in techs else tech_id
        row = {"tech_id": tech_id, "name": name, "best": _best(fabrics),
               "fabrics": [f["fabric_id"] for f in fabrics]}
        mine = [d for d in chosen if d["tech_id"] == tech_id]
        opens = [fabric_open(tech_id, f, mine, path) for f in fabrics]
        unscored = sum(o["unscored"] for o in opens)
        if unscored:
            blocking = [{"fabric_id": o["fabric_id"], "fabric": o["fabric"]} for o in opens if o["blocking"]]
            items["unscored"].append({**row, "measures": unscored, "blocking": blocking})
        waiting = sum(o["waiting_for_tata"] for o in opens)
        if waiting:
            items["waiting_for_tata"].append({**row, "measures": waiting})
        moved = [f for f in fabrics if f["effective"]["override_moved"]]
        if moved:
            items["override_moved"].append({**row, "moves": [
                {"fabric_id": f["fabric_id"], "fabric": f["fabric"], "override": f["effective"]["priority"],
                 "was": f["effective"]["override"]["computed"], "now": f["effective"]["computed_priority"]}
                for f in moved]})
        waiting_cases = [{"fabric_id": o["fabric_id"], "fabric": o["fabric"], "title": t}
                         for o in opens for t in o["suggested_use_cases"]]
        if waiting_cases:
            items["suggested_use_cases"].append({**row, "cases": waiting_cases})
        gaps = [{"fabric_id": o["fabric_id"], "fabric": o["fabric"], "missing": o["finance_missing"]}
                for o in opens if o["finance_missing"]]
        if gaps:
            items["finance_missing"].append({**row, "gaps": gaps})
        ready = [{"fabric_id": o["fabric_id"], "fabric": o["fabric"], "at": o["step"], "next": o["next_step"]["name"]}
                 for o in opens if o["next_step"] and o["next_step"]["in_hand"]]
        if ready:
            items["ready_next_step"].append({**row, "steps": ready})
        # the readiness level and the Maturity score should tell the same story
        level = classify_effective.effective(techs[tech_id], chosen, lists)["trl"]["level"] if tech_id in techs else None
        maturity = next((f["measures"].get(MATURITY, {}).get("score") for f in fabrics
                         if f["measures"].get(MATURITY, {}).get("score") is not None), None)
        if level and maturity is not None and trl_band(level) != score_band(maturity):
            items["maturity_mismatch"].append({**row, "trl": level, "maturity": maturity})
    items["unscored"].sort(key=lambda r: (not r["blocking"], r["best"], r["name"]))
    for kind in ("waiting_for_tata", "override_moved", "maturity_mismatch", "suggested_use_cases", "finance_missing",
                 "ready_next_step"):
        items[kind].sort(key=lambda r: (r["best"], r["name"]))
    return [{"kind": kind, "count": len(rows), "technologies": rows} for kind, rows in items.items() if rows]


def fabric_open(tech_id: str, f: dict, mine: list[dict], path: dict) -> dict:
    """What's still open for a technology in one fabric, as people left it
    (`mine`: its choices in force): Gate 2's items (measures to settle,
    suggested use cases, finance figures from Proof of concept on), then what
    isn't recorded yet (the step reached, the blockers, an owner) and what the
    next step still needs. One count for the technology page and Gate 2."""
    from app.services import finance
    c = eff.counts(f)
    fig = finance.figures(tech_id, f["fabric_id"], mine, None, path, f)
    nxt = fig["next_step"]
    decided = {d["key"] for d in mine if d["kind"] == "use_case"}
    return {
        "fabric_id": f["fabric_id"], "fabric": f["fabric"], "priority": f["effective"]["priority"],
        "unscored": c.get("unscored", 0), "blocking": eff.blocks_placement(f),
        "waiting_for_tata": c.get("waiting_for_tata", 0),
        "override_moved": f["effective"]["override_moved"],
        # suggested use cases (not from the pages) wait for a person to accept or reject
        "suggested_use_cases": [s["title"] for s in f.get("suggested_use_cases") or [] if s["key"] not in decided],
        # at Proof of concept or later, finance figures need their inputs
        "finance_missing": sorted({x for v in fig["missing"].values() for x in v}) if fig["needed"] and finance.SHOWN else [],
        "step": fig["step"]["name"] if fig["step"] else None,
        # Nick's ladder: once a step is set, what the next rung still needs (services/finance)
        "next_step": {"name": nxt["name"], "in_hand": nxt["in_hand"],
                      "missing": [{"label": n["label"], "where": n["where"]} for n in nxt["needs"] if not n["have"]]}
        if nxt and fig["step"] else None,
        "blockers": fig["bottlenecks"] is not None,
        "owner": (rec := decisions.pick(mine, "commitment", tech_id=tech_id, fabric_id=f["fabric_id"])) is not None,
        "resources": any((rec or {}).get("value", {}).get(k) for k in decisions.RESOURCES),  # people, budget or a trial
        "leader": decisions.leader_state(mine, tech_id, f["fabric_id"])["state"],  # the owner's record's state
    }


def open_for(tech_id: str) -> list[dict]:
    """fabric_open for each fabric of a technology's latest assessment."""
    from app.services import finance
    fabrics = latest_applied([tech_id]).get(tech_id, [])
    mine = decisions.active([tech_id])
    path = finance.steps()
    return [fabric_open(tech_id, f, mine, path) for f in fabrics]
