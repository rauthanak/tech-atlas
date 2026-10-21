"""About how many model calls assessing technologies takes — a baseline the
portal shows as "about N". Per technology (engine.assess_technology), with
the stacked engine: one technology call and one call per fabric it is
assessed in; with the per-measure engine: one gate call, one call per
measure for each fabric, and one watch-metrics call. The counts come from
the scoring setup; retried calls add to it."""

from app.services.db.mongo import get_collection


def last_gates() -> dict[str, list[str]]:
    """Each technology's most recent recorded gate: the fabrics it was
    assessed in."""
    gates: dict[str, list[str]] = {}
    for run in (get_collection("scoring_runs").find({"gates": {"$exists": True}}, {"gates": 1})
                .sort("started_at", -1)):
        for tech_id, fabric_ids in run["gates"].items():
            gates.setdefault(tech_id, fabric_ids)
    return gates


def estimate(tech_ids: list[str]) -> dict:
    """`calls` uses each technology's last gate (every enabled fabric when it
    has none); `calls_max` assumes every enabled fabric."""
    measures = get_collection("measures").count_documents({})
    enabled = set(get_collection("fabrics").distinct("_id", {"enabled": True}))
    gates = last_gates()

    cfg = get_collection("scoring_config").find_one({"_id": "engine"}) or {}
    stacked = cfg.get("mode") == "stacked"

    def calls(fabrics: int) -> int:
        return 1 + fabrics if stacked else 2 + measures * fabrics

    total = sum(calls(len(enabled & set(gates.get(t, enabled))) or len(enabled)) for t in tech_ids)
    return {"technologies": len(tech_ids), "calls": total,
            "calls_max": len(tech_ids) * calls(len(enabled))}
