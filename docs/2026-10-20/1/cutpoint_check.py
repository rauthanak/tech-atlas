"""The cut-point check the engine comparison asked for (plan 9, item 5): how
the full stacked run's "how soon" and "how big" scores spread against the
cut-points on Weights & Grid, next to the 6 Oct run, and what cut-points
would keep the 6 Oct share of each band. Placement is arithmetic, so a
what-if costs no model call. Writes cutpoint-check.md; changes nothing.

Inside the API container:
    python cutpoint_check.py FULL_RUN EARLIER_RUN
"""

import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app/src")
from agent.analyzer.placement import POTENTIAL_BANDS, TIMELINE_BANDS, _band  # noqa: E402
from app.services.db.mongo import get_collection  # noqa: E402

OUT = Path(__file__).with_name("cutpoint-check.md")
GRID = get_collection("scoring_config").find_one({"_id": "priority_grid"})
CUTS = {"timeline": GRID["timeline_cutpoints"], "potential": GRID["potential_cutpoints"]}
LABELS = {"timeline": TIMELINE_BANDS, "potential": POTENTIAL_BANDS}
NAMES = {"timeline": "How soon", "potential": "How big"}


def scores(run_id: str) -> dict[str, list[float]]:
    out = {"timeline": [], "potential": []}
    for a in get_collection("assessments").find({"scoring_run_id": run_id}, {"placement": 1}):
        for axis in out:
            s = ((a.get("placement") or {}).get(axis) or {}).get("score")
            if s is not None:
                out[axis].append(s)
    return out


def pairs(run_id: str) -> list[tuple[float, float]]:
    out = []
    for a in get_collection("assessments").find({"scoring_run_id": run_id}, {"placement": 1}):
        p = a.get("placement") or {}
        t, v = (p.get("timeline") or {}).get("score"), (p.get("potential") or {}).get("score")
        if t is not None and v is not None:
            out.append((t, v))
    return out


def quantiles(xs: list[float]) -> str:
    if len(xs) < 4:
        return "too few"
    q = statistics.quantiles(xs, n=10)
    return f"lowest {min(xs):.1f} · 10% {q[0]:.1f} · 25% {statistics.quantiles(xs, n=4)[0]:.1f} · " \
           f"median {statistics.median(xs):.1f} · 75% {statistics.quantiles(xs, n=4)[2]:.1f} · 90% {q[8]:.1f} · highest {max(xs):.1f}"


def bands(xs: list[float], cuts: list, labels: tuple) -> Counter:
    return Counter(_band(x, cuts, labels) for x in xs)


def share(c: Counter, labels: tuple, n: int) -> str:
    return " · ".join(f"{lab} {c[lab]} ({round(100 * c[lab] / max(n, 1))}%)" for lab in labels)


def matched(xs: list[float], target: Counter, labels: tuple) -> list[float]:
    """Cut-points that give xs the same share of each band as target: the low
    cut leaves the target's share of labels[2] below it, the high cut leaves
    its share of labels[0] above it."""
    xs, n_t = sorted(xs), sum(target.values())
    lo_share, hi_share = target[labels[2]] / n_t, target[labels[0]] / n_t
    lo = xs[min(len(xs) - 1, round(lo_share * len(xs)))]
    hi = xs[max(0, len(xs) - 1 - round(hi_share * len(xs)))]
    return [round(lo, 1), round(hi, 1)]


def priorities(ps: list[tuple[float, float]], t_cuts: list, p_cuts: list) -> Counter:
    grid = GRID["grid"]
    return Counter(grid.get(f"{_band(t, t_cuts, TIMELINE_BANDS)}_{_band(v, p_cuts, POTENTIAL_BANDS)}") for t, v in ps)


def line(c: Counter, n: int) -> str:
    return " · ".join(f"{p} {c[p]} ({round(100 * c[p] / max(n, 1))}%)" for p in ("P1", "P2", "P3", "P4", "P5", "P6"))


def main(full: str, earlier: str) -> None:
    sf, se = scores(full), scores(earlier)
    pf, pe = pairs(full), pairs(earlier)
    lines = ["# Cut-point check (plan 9, item 5)", "",
             f"The full stacked run ({full}) against the 6 Oct run ({earlier}), with the cut-points now on "
             f"Weights & Grid: how soon {CUTS['timeline']}, how big {CUTS['potential']}. A score below the low "
             "cut-point is in the lowest band, above the high one in the highest. Only technology-fabric pairs "
             "with both scores count.", ""]
    match = {}
    for axis in ("timeline", "potential"):
        cf, ce = bands(sf[axis], CUTS[axis], LABELS[axis]), bands(se[axis], CUTS[axis], LABELS[axis])
        match[axis] = matched(sf[axis], ce, LABELS[axis])
        lines += [f"## {NAMES[axis]}", "",
                  f"- **Full run** ({len(sf[axis])}): {quantiles(sf[axis])}",
                  f"- **6 Oct run** ({len(se[axis])}): {quantiles(se[axis])}", "",
                  f"- Bands now, full run: {share(cf, LABELS[axis], len(sf[axis]))}",
                  f"- Bands, 6 Oct run: {share(ce, LABELS[axis], len(se[axis]))}",
                  f"- Cut-points that would give the full run the 6 Oct share: {match[axis]}", ""]
    now = priorities(pf, CUTS["timeline"], CUTS["potential"])
    then = priorities(pe, CUTS["timeline"], CUTS["potential"])
    what_if = priorities(pf, match["timeline"], match["potential"])
    lines += ["## Priorities", "",
              f"- **Full run, cut-points as now** ({len(pf)}): {line(now, len(pf))}",
              f"- **6 Oct run** ({len(pe)}): {line(then, len(pe))}",
              f"- **Full run, with the matched cut-points**: {line(what_if, len(pf))}", ""]
    OUT.write_text("\n".join(lines) + "\n")
    print(OUT.read_text())


if __name__ == "__main__":
    main(*sys.argv[1:])
