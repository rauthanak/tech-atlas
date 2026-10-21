"""An assessment with people's choices applied (services/decisions), with no
model call: what every screen shows, the Before publishing list counts, and
the Point of View and Frontier use.

Each measure ends in one state:
  scored            the model scored it from the pages
  scored_by_person  a person scored it (or Tata entered it); the model's
                    score, when there is one, is kept beside it and the
                    person's is used
  gap_accepted      unscored, and a person accepted the gap
  waiting_for_tata  entered by Tata, not yet entered
  unscored          the pages didn't support a score, and nobody has settled it

When a person's score changed a measure, the scores are rolled up and placed
again, as the run would, with no model call; otherwise the run's own roll-up
and placement stand. A priority override wins over the computed priority,
which stays visible (and is flagged when it has moved since the override)."""

from agent.analyzer.engine import rollup_tora
from agent.analyzer.placement import compute_placement
from app.services.decisions import pick


def _brief(d: dict | None) -> dict | None:
    return None if d is None else {k: d.get(k) for k in ("_id", "kind", "value", "reason", "at", "tz", "computed")}


def apply(assessment: dict, decisions: list[dict], measures: list[dict], config: list[dict]) -> dict:
    """The assessment as people left it: `measures` with a `state` each,
    `tora` and `placement` recomputed, and `effective` {priority, horizon,
    computed_priority, override, override_moved}."""
    fabric = assessment["fabric_id"]
    mine = [d for d in decisions if d["tech_id"] == assessment["tech_id"]]
    scope = {m["_id"]: m.get("scope") or "fabric" for m in measures}
    results: dict[str, dict] = {}
    changed = False
    for mid, stored in (assessment.get("measures") or {}).items():
        r = {**stored, "scope": stored.get("scope") or scope.get(mid, "fabric")}
        hand = pick(mine, "tata_entry" if r["scope"] == "tata" else "hand_score", fabric_id=fabric, measure_id=mid)
        gap = pick(mine, "accept_gap", fabric_id=fabric, measure_id=mid)
        if hand:
            changed = True
            if r.get("score") is not None:
                r["model_score"] = r["score"]
            r.update(score=hand["value"], state="scored_by_person", decision=_brief(hand), unscorable=False)
        elif r.get("score") is not None:
            r["state"] = "scored"
        elif gap:
            r.update(state="gap_accepted", decision=_brief(gap))
        elif r["scope"] == "tata":
            r["state"] = "waiting_for_tata"
        else:
            r["state"] = "unscored"
        results[mid] = r
    placement = compute_placement(results, config) if changed else (assessment.get("placement") or compute_placement(results, config))
    tora = rollup_tora(results, measures) if changed else (assessment.get("tora") or rollup_tora(results, measures))
    override = pick(mine, "override", fabric_id=fabric, measure_id=None)
    computed = placement.get("priority")
    return {**assessment, "measures": results, "tora": tora, "placement": placement, "recomputed": changed,
            "effective": {"priority": override["value"] if override else computed,
                          "horizon": placement.get("horizon"),
                          "computed_priority": computed,
                          "override": _brief(override),
                          "override_moved": bool(override) and override.get("computed") != computed}}


def counts(applied: dict) -> dict:
    """How many measures are in each state."""
    out: dict[str, int] = {}
    for r in applied["measures"].values():
        out[r["state"]] = out.get(r["state"], 0) + 1
    return out


def blocks_placement(applied: dict) -> bool:
    """No priority because how soon or how big has nothing scored: settling
    its measures is what would place it."""
    p = applied["placement"]
    return applied["effective"]["priority"] is None and any(
        (p.get(k) or {}).get("score") is None for k in ("timeline", "potential"))
