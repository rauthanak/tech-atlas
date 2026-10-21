"""The run executor: one background thread, one active run at a time.

Resilience layers: every failure marks the run terminated with its error
(layer 1); FastAPI shutdown marks running runs interrupted (layer 2); the
crawl heartbeats while working (layer 3); and startup reconciliation flips
anything still 'running' at boot to terminated (layer 4) — a run can never
stay 'running' forever."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from agent.orchestrator.agent import run_orchestrator
from agent.orchestrator.tools.categories import category_keys
from agent.supervisor.agent import Supervisor
from app.services.llm.context import with_context
from app.services import busy
from app.services.db.mongo import get_collection
from app.services.llm import LLM
from app.services.runs import store
from app.services.signals import snapshot
from app.services.timezone import now_utc
from app.settings import get_settings

log = logging.getLogger(__name__)


def active_run_id() -> str | None:
    doc = get_collection("runs").find_one(
        {"status": {"$in": list(store.RUNNING_STATES)}}, {"_id": 1})
    return doc["_id"] if doc else None


def start_run(params: dict) -> str:
    """Start a run in a background thread. It records the signal list and
    crawl settings it uses. Raises busy.Busy when a run or a re-check is
    active (a re-check rewrites stored summaries)."""
    with busy.start_lock:
        reason = busy.reason("collection", "recheck")
        if reason:
            raise busy.Busy(reason)
        run_id = store.create_run(params, snapshot.build())
    threading.Thread(target=_execute, args=(run_id, params),
                     name=f"run-{run_id}", daemon=True).start()
    return run_id


def request_terminate(run_id: str) -> bool:
    result = get_collection("runs").update_one(
        {"_id": run_id, "status": "running"}, {"$set": {"status": "terminating"}})
    return result.modified_count == 1


def _execute(run_id: str, params: dict) -> None:
    log.info("run %s started (params=%s)", run_id, params)
    try:
        llm = LLM.initialize()
        store.set_stage(run_id, "orchestrating")
        store.set_substage(run_id, "orchestrating", "planning")
        try:
            with with_context(run_kind="collection", run_id=run_id, skills=["orchestrator"]):
                report = run_orchestrator(llm)
            log.info("orchestrator: %s", report[:200])
        except Exception:  # placeholder-prompt agent; the fan-out is deterministic anyway
            log.exception("orchestrator agent failed; continuing with deterministic categories")

        categories = params.get("categories") or category_keys()
        store.set_substage(run_id, "orchestrating", "dispatching")
        store.set_stage(run_id, "crawling")
        with ThreadPoolExecutor(max_workers=get_settings().scout_concurrency,
                                thread_name_prefix="scout") as executor:
            for category in categories:  # n categories → n supervisors
                if store.cancelled(run_id):
                    break
                store.set_substage(run_id, "crawling", f"supervisor {category.lower()}")
                Supervisor(category, llm).run(run_id, executor, params)

        # the crawl's new documents resolve into the technology register as the
        # run's final stage — incremental (pinned aliases skip the LLM), and
        # skipped without failing the run when a resolve is already going
        if not store.cancelled(run_id):
            store.set_stage(run_id, "resolving")
            try:
                from agent.resolver import run_resolve_sync
                resolve_id = run_resolve_sync()
                if resolve_id:  # link the run to its resolve for the drill-down view
                    get_collection("runs").update_one(
                        {"_id": run_id}, {"$set": {"resolve_id": resolve_id}})
                log.info("run %s resolve stage: %s", run_id,
                         resolve_id or "skipped — a resolve was already running")
            except Exception:  # resolution can be re-run any time from the portal
                log.exception("resolve stage failed; run continues to completion")

        # then Classify the technologies with new pages (radar setting classify_after_collection)
        if not store.cancelled(run_id):
            from app.services.settings_store import radar_settings
            if radar_settings().get("classify_after_collection"):
                store.set_stage(run_id, "classifying")
                try:
                    from agent.classifier import classify
                    ids = classify.pending()
                    classify_id = classify.start(ids, trigger=f"after collection {run_id}", wait=True) if ids else None
                    if classify_id:
                        get_collection("runs").update_one({"_id": run_id}, {"$set": {"classify_id": classify_id}})
                except Exception:  # Classify can be run again from Operations
                    log.exception("classify stage failed; run continues to completion")

        status = "terminated" if store.cancelled(run_id) else "completed"
        store.set_stage(run_id, "done")
        store.finish_run(run_id, status, "terminated by user" if status == "terminated" else None)
        log.info("run %s %s", run_id, status)
        store.prune_old_text()  # retention, after every run
    except Exception as exc:
        log.exception("run %s crashed", run_id)
        store.finish_run(run_id, "terminated", error=str(exc)[:500])


def shutdown() -> None:
    """Graceful-stop hook (FastAPI lifespan exit): running runs die with this
    process, so record that truthfully."""
    result = get_collection("runs").update_many(
        {"status": {"$in": list(store.RUNNING_STATES)}},
        {"$set": {"status": "terminated", "error": "interrupted — service shutdown",
                  "run_end_date_time": now_utc()}})
    if result.modified_count:
        log.warning("shutdown: marked %d running run(s) terminated", result.modified_count)
