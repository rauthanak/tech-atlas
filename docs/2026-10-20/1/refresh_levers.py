"""Refresh the value levers on every latest assessment (21 Oct, after Nick's
rules went in: two levers per use case, capital on every card, key metrics;
run again the same day for value_levers v3, which also suggests blockers, and for v4, plain titles).
Each technology-fabric pair's value levers are asked again alone, on its
evidence now, exactly as Find use cases does; scores are not touched.
Calls are recorded under run kind "value_refresh".

Inside the API container:
    python refresh_levers.py            # what it would do, no calls
    python refresh_levers.py --go
    python refresh_levers.py --go --again <log>   # only the pairs that log says weren't updated
"""

import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/app/src")
from agent.find_evidence.job import rerun_use_cases  # noqa: E402
from app.services import evidence  # noqa: E402
from app.services.db.mongo import get_collection  # noqa: E402
from app.services.llm.context import carry, with_context  # noqa: E402
from app.services.timezone import now_utc  # noqa: E402

RUN_ID = "value-refresh-" + now_utc()[:16].replace(":", "")  # one id per run, to the minute


def pairs() -> list[tuple[dict, str]]:
    """(technology, fabric id) for every fabric of each technology's latest assessment, switched-off ones left out."""
    latest = evidence.latest_assessments(evidence.states())
    techs = {t["_id"]: t for t in get_collection("technologies").find(
        {"_id": {"$in": [x["tech_id"] for x in latest]}, "enabled": {"$ne": False}}, {"name": 1})}
    out = []
    for x in latest:
        if x["tech_id"] in techs:
            for a in get_collection("assessments").find({"scoring_run_id": x["scoring_run_id"], "tech_id": x["tech_id"]},
                                                        {"fabric_id": 1}):
                out.append((techs[x["tech_id"]], a["fabric_id"]))
    return out


def one(item: tuple[dict, str]) -> str:
    tech, fabric_id = item
    with with_context(tech_id=tech["_id"]):
        try:
            return f"{tech['_id']} · {fabric_id}: " + rerun_use_cases({"tech_id": tech["_id"], "fabric_id": fabric_id}, tech, RUN_ID)
        except Exception as exc:  # one failure doesn't stop the rest, and says why
            return f"{tech['_id']} · {fabric_id}: FAILED ({exc})"


def failed_in(log: str) -> set[tuple[str, str]]:
    """(tech id, fabric id) of each pair a past run's log says it couldn't update."""
    return {tuple(line.split(":", 1)[0].split(" · ")) for line in open(log)
            if "weren't updated" in line or "FAILED" in line}


def main(go: bool, again: str | None = None) -> None:
    todo = pairs()
    if again:
        redo = failed_in(again)
        todo = [(t, f) for t, f in todo if (t["_id"], f) in redo]
    print(f"{len(todo)} technology-fabric pairs, one call each")
    if not go:
        return
    with with_context(run_kind="value_refresh", run_id=RUN_ID, skills=["value_levers"]):
        with ThreadPoolExecutor(max_workers=6) as pool:
            for f in [pool.submit(carry(one), item) for item in todo]:  # one context copy per submission
                print(f.result(), flush=True)


if __name__ == "__main__":
    main("--go" in sys.argv, sys.argv[sys.argv.index("--again") + 1] if "--again" in sys.argv else None)
