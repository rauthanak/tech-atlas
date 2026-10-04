"""The analyzer — a LangGraph deep agent invoked once per scoring run. It
works the run's technology list through its tools; the deterministic sweep in
run_scoring then assesses anything it skipped, so completion never depends on
LLM behavior (the same guarantee the scouts have)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from deepagents import create_deep_agent

from agent.analyzer import engine
from agent.analyzer.tools.workload import make_assess_tool, make_workload_tool
from app.services import busy
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM
from app.services.prompts.store import PromptStore
from app.settings import get_settings

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
    threading.Thread(target=run_scoring, args=(run_id,),
                     name=f"scoring-{run_id}", daemon=True).start()
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
            {"$set": {"status": "running", "stage": "scoring", "error": None,
                      "finished_at": None, "progress.techs_done": 0},
             "$push": {"stage_history": {"stage": "resumed", "at": engine._now()}}})
    if doc is None:
        return False
    threading.Thread(target=run_scoring, args=(run_id,),
                     name=f"scoring-{run_id}", daemon=True).start()
    return True


def run_scoring(run_id: str) -> None:
    log.info("scoring run %s started", run_id)
    try:
        llm = LLM.initialize()
        engine.set_stage(run_id, "scoring")
        with ThreadPoolExecutor(max_workers=get_settings().scoring_concurrency,
                                thread_name_prefix="measure") as executor:
            try:
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
