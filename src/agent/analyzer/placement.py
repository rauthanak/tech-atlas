"""Placement (Phase D) — pure arithmetic, zero LLM calls, so it recomputes
free whenever cut-points, source-measure lists, or the horizon map change.

From an assessment's measure scores: the *how soon* composite (timeline_from
measures) and *how big* composite (potential_from measures), means over what
scored — an unscorable measure thins a composite, never zeroes it. Cut-points
band each composite, the grid map names the P1–P6 cell, and the timeline band
proposes the horizon. Both grid views are always produced: potential (impact)
and disruptiveness (X1) as the alternative vertical axis."""

DEFAULT_HORIZONS = {"near": "H1", "mid": "H2", "far": "H3"}

TIMELINE_BANDS = ("near", "mid", "far")     # high score → arriving sooner
POTENTIAL_BANDS = ("high", "mid", "low")


def _band(score: float | None, cutpoints: list, labels: tuple) -> str | None:
    if score is None:
        return None
    lo, hi = float(cutpoints[0]), float(cutpoints[1])
    return labels[2] if score < lo else labels[1] if score <= hi else labels[0]


def _composite(measure_results: dict, measure_ids: list[str]) -> dict:
    scores = [r["score"] for mid in measure_ids
              if (r := measure_results.get(mid)) and r["score"] is not None]
    return {
        "score": round(sum(scores) / len(scores), 2) if scores else None,
        "scored": len(scores),
        "of": len(measure_ids),
        "partial": len(scores) < len(measure_ids),
    }


def compute_placement(measure_results: dict, config_docs: list[dict]) -> dict:
    cfg = {c["_id"]: c for c in config_docs}
    grid_cfg = cfg.get("priority_grid", {})
    horizons = (cfg.get("horizons") or {}).get("map") or DEFAULT_HORIZONS
    grid = grid_cfg.get("grid", {})
    t_cuts = grid_cfg.get("timeline_cutpoints", [4.0, 7.0])
    p_cuts = grid_cfg.get("potential_cutpoints", [4.0, 7.0])

    timeline = _composite(measure_results, grid_cfg.get("timeline_from", []))
    potential = _composite(measure_results, grid_cfg.get("potential_from", []))
    t_band = _band(timeline["score"], t_cuts, TIMELINE_BANDS)
    p_band = _band(potential["score"], p_cuts, POTENTIAL_BANDS)

    disr = measure_results.get("disruption-threat", {}).get("score")
    d_band = _band(disr, p_cuts, POTENTIAL_BANDS)

    return {
        "timeline": {**timeline, "band": t_band},
        "potential": {**potential, "band": p_band},
        "disruptiveness": {"score": disr, "band": d_band},
        "priority": grid.get(f"{t_band}_{p_band}") if t_band and p_band else None,
        "priority_by_disruptiveness":
            grid.get(f"{t_band}_{d_band}") if t_band and d_band else None,
        "horizon": horizons.get(t_band) if t_band else None,
    }
