"""The analyzer — a LangGraph deep agent invoked once per scoring run. It
works the run's technology list through its tools; the deterministic sweep in
run_scoring then assesses anything it skipped, so completion never depends on
LLM behavior (the same guarantee the scouts have)."""

import logging
from concurrent.futures import ThreadPoolExecutor

from deepagents import create_deep_agent

from agent.analyzer import engine
from agent.analyzer.tools.workload import make_assess_tool, make_workload_tool
from app.services.llm.context import with_context
from app.services import busy
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM
from app.services.prompts.store import PromptStore
from app.services.timezone import now_utc
from app.settings import get_settings
from app.services import jobs

log = logging.getLogger(__name__)


def start_scoring_run(params: dict) -> str | None:
    """Start a scoring run in a background thread; None when one is active.
    Raises busy.Busy while a re-check rewrites the summaries it would read."""
    with busy.start_lock:
        if engine.active_scoring_run_id():
            return None
        reason = busy.reason("recheck")
        if reason:
            raise busy.Busy(reason)
        run_id = engine.create_scoring_run(params)
    jobs.start(run_scoring, run_id)
    return run_id


def resume_scoring_run(run_id: str) -> bool:
    """Re-open a failed or terminated run: existing assessments are kept (the
    per-fabric existence check skips them) and only the missing work is done.
    False when the run is unknown, still active, or already completed.
    Raises busy.Busy while a re-check runs."""
    with busy.start_lock:
        if engine.active_scoring_run_id():
            return False
        reason = busy.reason("recheck")
        if reason:
            raise busy.Busy(reason)
        doc = get_collection("scoring_runs").find_one_and_update(
            {"_id": run_id, "status": {"$in": ["failed", "terminated"]}},
            {"$set": {"status": "running", "stage": "scoring", "error": None, "failed": [],
                      "finished_at": None, "progress.techs_done": 0},
             "$push": {"stage_history": {"stage": "resumed", "at": now_utc()}}})
    if doc is None:
        return False
    jobs.start(run_scoring, run_id)
    return True


def run_scoring(run_id: str) -> None:
    status = (get_collection("scoring_runs").find_one({"_id": run_id}, {"status": 1}) or {}).get("status")
    if status != "running":  # stopped (or cut off) before it started: nothing to do, nothing spent
        if status == "terminating":
            engine.finish(run_id, "terminated", "terminated by user")
        log.info("scoring run %s is %s: not started", run_id, status)
        return
    log.info("scoring run %s started", run_id)
    try:
        llm = LLM.initialize()
        engine.set_stage(run_id, "scoring")
        if engine.engine_mode(run_id) == "stacked":
            failed = _sweep_in_parallel(run_id, llm)
            if failed:  # which, and why: Resume does only these again
                get_collection("scoring_runs").update_one({"_id": run_id}, {"$set": {"failed": failed}})
            if engine.cancelled(run_id):
                status, error = "terminated", "terminated by user"
            elif failed:
                total = len(get_collection("scoring_runs").find_one({"_id": run_id}, {"technologies": 1})["technologies"])
                status, error = "failed", (f"{len(failed)} of {total} technologies failed: "
                                           + "; ".join(f"{f['name']}: {f['error']}" for f in failed))[:500]
            else:
                status, error = "completed", None
            engine.finish(run_id, status, error)
            log.info("scoring run %s %s", run_id, status)
            return
        with ThreadPoolExecutor(max_workers=get_settings().scoring_concurrency,
                                thread_name_prefix="measure") as executor:
            try:
                with with_context(run_kind="scoring", run_id=run_id, skills=["analyzer"]):
                    agent = create_deep_agent(
                        model=llm.chat_model(),
                        tools=[make_workload_tool(run_id),
                               make_assess_tool(run_id, llm, executor)],
                        system_prompt=PromptStore.get("analyzer").render(),
                        name="analyzer",
                    )
                    agent.invoke(
                        {"messages": [{"role": "user",
                                       "content": "Assess every technology in this scoring run."}]},
                        {"recursion_limit": 60},
                    )
            except Exception:  # the sweep below guarantees completion regardless
                log.exception("analyzer agent failed; deterministic sweep continues")

            # deterministic sweep — assess whatever is still owed. Coverage is
            # per fabric, not per tech: assess_technology skips fabrics that
            # already have assessments and re-uses the stored gate verdict, so
            # sweeping a finished tech costs zero LLM calls.
            run = get_collection("scoring_runs").find_one({"_id": run_id})
            skipped = {s["tech_id"] for s in run.get("skipped", [])}
            for t in run["technologies"]:
                if engine.cancelled(run_id):
                    break
                if t["tech_id"] in skipped:
                    continue
                engine.assess_technology(run_id, t["tech_id"], llm, executor)

        status = "terminated" if engine.cancelled(run_id) else "completed"
        engine.finish(run_id, status,
                      "terminated by user" if status == "terminated" else None)
        log.info("scoring run %s %s", run_id, status)
    except Exception as exc:
        log.exception("scoring run %s crashed", run_id)
        engine.finish(run_id, "failed", str(exc)[:500])


def _sweep_in_parallel(run_id: str, llm) -> list[dict]:
    """The stacked engine's run: technologies assessed several at a time (each
    makes one technology call, then its fabric calls together), every one owed
    covered. A technology's calls are few and large, so the deep agent's
    one-at-a-time plan is left out here: it would only slow the run. Returns
    the technologies that failed: [{tech_id, name, error}]."""
    from app.services.llm.context import carry
    n = get_settings().scoring_concurrency
    run = get_collection("scoring_runs").find_one({"_id": run_id})
    skipped = {s["tech_id"] for s in run.get("skipped", [])}
    owed = [t["tech_id"] for t in run["technologies"] if t["tech_id"] not in skipped]
    names = {t["tech_id"]: t["name"] for t in run["technologies"]}
    failed = []
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="fabric") as fabrics, \
            ThreadPoolExecutor(max_workers=n, thread_name_prefix="technology") as techs:
        futures = {t: techs.submit(carry(engine.assess_technology), run_id, t, llm, fabrics) for t in owed}
        for tech_id, f in futures.items():
            if engine.cancelled(run_id):
                break
            try:
                f.result()
            except Exception as exc:  # one technology must not sink the run; the others go on
                log.exception("assessing a technology failed in run %s", run_id)
                failed.append({"tech_id": tech_id, "name": names.get(tech_id, tech_id),
                               "error": str(exc)[:300] or type(exc).__name__})
    return failed
