"""The engine comparison (plan 9, item 5): the same technologies assessed by
the stacked engine and the per-measure engine, both on today's model and
today's pages, so only the engine differs. Writes engine-comparison.md.

Inside the API container:
    python compare_engines.py STACKED_RUN PER_MEASURE_RUN [EARLIER_RUN]
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")
from app.services.db.mongo import get_collection  # noqa: E402

OUT = Path(__file__).with_name("engine-comparison.md")


def usage(run_id: str, techs: list[str]) -> dict:
    """The run's calls and tokens for these technologies only, so runs of
    different sizes compare like for like."""
    rows = list(get_collection("llm_calls").aggregate([
        {"$match": {"run_id": run_id, "tech_id": {"$in": techs}}},
        {"$group": {"_id": None, "calls": {"$sum": 1}, "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"}, "cache_read_tokens": {"$sum": "$cache_read_tokens"},
                    "cache_write_tokens": {"$sum": "$cache_write_tokens"}}}]))
    return rows[0] if rows else {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                                 "cache_write_tokens": 0}


def rows(run_id: str) -> dict:
    return {(a["tech_id"], a["fabric_id"]): a for a in get_collection("assessments").find({"scoring_run_id": run_id})}


def calls(run_id: str) -> int:
    return (get_collection("scoring_runs").find_one({"_id": run_id}, {"progress": 1}) or {}).get("progress", {}).get("llm_calls", 0)


def compare(a_run: str, b_run: str, a_name: str, b_name: str) -> list[str]:
    a, b = rows(a_run), rows(b_run)
    techs = sorted({t for t, _ in b})
    both = [k for k in a if k in b]
    diffs, scored_a, scored_b, n, prio_same, horizon_same, gates_same = [], 0, 0, 0, 0, 0, 0
    per_measure: dict[str, list[float]] = {}
    for key in both:
        ma, mb = a[key]["measures"], b[key]["measures"]
        for mid in ma:
            if mid not in mb:
                continue
            sa, sb = ma[mid].get("score"), mb[mid].get("score")
            if (ma[mid].get("scope") or "") == "tata":
                continue  # not asked of the model by the stacked engine
            n += 1
            scored_a += sa is not None
            scored_b += sb is not None
            if sa is not None and sb is not None:
                diffs.append(abs(sa - sb))
                per_measure.setdefault(mid, []).append(abs(sa - sb))
        prio_same += (a[key].get("placement") or {}).get("priority") == (b[key].get("placement") or {}).get("priority")
        horizon_same += (a[key].get("placement") or {}).get("horizon") == (b[key].get("placement") or {}).get("horizon")
    fa = {t: sorted(f for tt, f in a if tt == t) for t in techs}
    fb = {t: sorted(f for tt, f in b if tt == t) for t in techs}
    gates_same = sum(fa[t] == fb[t] for t in techs)
    ua, ub = usage(a_run, techs), usage(b_run, techs)
    sent = lambda u: u["input_tokens"] + u["cache_read_tokens"] + u["cache_write_tokens"]
    paid = lambda u: u["input_tokens"] + u["cache_write_tokens"] * 1.25 + u["cache_read_tokens"] * 0.1
    lines = [
        f"### {a_name} against {b_name}", "",
        f"Technologies: {len(techs)}; technology-fabric pairs in both: {len(both)}; measures compared: {n} "
        "(Tata's two measures left out: the stacked engine doesn't ask the model for them).", "",
        "| | " + a_name + " | " + b_name + " |", "|---|---|---|",
        f"| Fabrics chosen, same as the other | {gates_same} of {len(techs)} technologies | |",
        f"| Measures scored | {scored_a} of {n} ({round(100 * scored_a / max(n, 1))}%) | {scored_b} of {n} ({round(100 * scored_b / max(n, 1))}%) |",
        f"| Model calls (these technologies) | {ua['calls']} | {ub['calls']} |",
        f"| Tokens sent | {sent(ua):,} | {sent(ub):,} |",
        f"| Tokens at the full price (reused at a tenth, stored at 1.25) | {round(paid(ua)):,} | {round(paid(ub)):,} |",
        f"| Tokens written back | {ua['output_tokens']:,} | {ub['output_tokens']:,} |", "",
        f"Where both scored a measure ({len(diffs)}): the scores differ by {statistics.mean(diffs):.2f} on average "
        f"(median {statistics.median(diffs):.1f}); {sum(d <= 1 for d in diffs)} of {len(diffs)} are within one point."
        if diffs else "No measure was scored by both.", "",
        f"Priority the same in {prio_same} of {len(both)} pairs; horizon the same in {horizon_same} of {len(both)}.", "",
        "Average difference by measure (where both scored it):", "",
        *(f"- {m}: {statistics.mean(v):.2f} over {len(v)}" for m, v in sorted(per_measure.items())), ""]
    return lines


def main(stacked: str, per_measure: str, earlier: str | None = None) -> None:
    lines = ["# Engine comparison (plan 9, item 5)", "",
             "Both runs used the same model (Anthropic claude-haiku-5-5) and the same pages, so only the engine differs:",
             "- **stacked:** one technology call (fabric choice, the technology-wide measures, metrics to watch, "
             "domain, TRL and availability), then one call per relevant fabric for that fabric's measures;",
             "- **per measure:** one call per measure per fabric, plus the fabric choice and metrics to watch, "
             "each with the full evidence.", "",
             *compare(stacked, per_measure, "Stacked", "Per measure")]
    if earlier:
        lines += ["## For reference: the 6 Oct run (the earlier model, per measure)", "",
                  "This also changes the model and the pages, so differences mix all three.", "",
                  *compare(stacked, earlier, "Stacked, today", "6 Oct run")]
    OUT.write_text("\n".join(lines) + "\n")
    print(OUT.read_text())


if __name__ == "__main__":
    main(*sys.argv[1:])
