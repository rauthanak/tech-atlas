"""Re-check stored pages: run the summarizing step again on pages checked
against an older signal list (or never), so they match the current one.
This is also how pages collected before signals existed get theirs.

One background job at a time, never alongside collection or scoring,
because it rewrites stored summaries. Pages done keep the new hash, so after
a restart ("interrupted") the next re-check does only the rest. It ends with
an incremental resolve, so technologies and set-aside exclusions are
current. A page whose new analysis fails keeps its stored summary, records
why (analysis_error) and stays stale, so the next re-check retries it; a
later success clears the reason."""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.services.llm.context import with_context
from app.services import busy
from app.services.db.mongo import get_collection
from app.services.llm import LLM
from app.services.signals import snapshot
from app.services.timezone import now_utc
from app.settings import get_settings

log = logging.getLogger(__name__)


def stale_query(current_hash: str) -> dict:
    """Pages to re-check: not stubs, text still stored, checked against
    another list or never. (The newest version of a page always keeps its
    text; only superseded older versions are pruned.)"""
    return {"is_stub": False, "extracted_text": {"$ne": None},
            "signals_hash": {"$ne": current_hash}}


def stale_count(current_hash: str | None = None) -> int:
    return get_collection("documents").count_documents(
        stale_query(current_hash or snapshot.current_hash()))


def latest_job() -> dict | None:
    return get_collection("recheck_jobs").find_one(sort=[("started_at", -1)])


def start() -> dict:
    """Start a re-check of every stale page. Raises busy.Busy, with the
    reason, while collection, scoring or another re-check is active, or when
    there is nothing to re-check."""
    with busy.start_lock:
        reason = busy.reason("collection", "scoring", "recheck")
        if reason:
            raise busy.Busy(reason)
        snap = snapshot.build()
        ids = [d["_id"] for d in get_collection("documents")
               .find(stale_query(snap["signals_hash"]), {"_id": 1}).sort("scraped_at", 1)]
        if not ids:
            raise busy.Busy("Nothing to check again: every stored page was checked against the current list.")
        job_id = uuid.uuid4().hex[:12]
        get_collection("recheck_jobs").insert_one({
            "_id": job_id, "status": "running", "stage": "checking",
            "total": len(ids), "done": 0, "failed": 0,
            "found": 0, "other": 0, "set_aside": 0, "failed_reasons": {},
            "signals_hash": snap["signals_hash"],
            "started_at": now_utc(), "heartbeat_at": now_utc(), "finished_at": None})
    threading.Thread(target=_run, args=(job_id, ids, snap),
                     name=f"recheck-{job_id}", daemon=True).start()
    return {"job_id": job_id, "total": len(ids)}


def _run(job_id: str, ids: list[str], snap: dict) -> None:
    from agent.resolver import run_resolve_sync
    from agent.scout.tools.summarize import summarize_page

    jobs, docs = get_collection("recheck_jobs"), get_collection("documents")
    llm = LLM.initialize()

    def record(doc_id: str, fields: dict) -> None:
        docs.update_one({"_id": doc_id}, {"$set": fields})
        docs.update_many({"ref_doc_id": doc_id}, {"$set": fields})  # its stubs

    def one(doc_id: str) -> None:
        update = {"$inc": {"done": 1}, "$set": {"heartbeat_at": now_utc()}}
        try:
            doc = docs.find_one({"_id": doc_id}, {"end_url": 1, "extracted_text": 1})
            if doc and doc.get("extracted_text"):
                with with_context(run_kind="recheck", run_id=job_id):
                    analysis = summarize_page(llm, doc["end_url"], doc["extracted_text"], snap)
                error = analysis.get("analysis_error")
                if error:  # failed or partly analysed: counted by reason
                    update["$inc"][f"failed_reasons.{error['reason']}"] = 1
                if analysis.get("failed"):  # keep the earlier analysis, record why
                    update["$inc"]["failed"] = 1
                    record(doc_id, {"analysis_error": error})
                else:
                    other = sum(1 for h in analysis["signals"] if h.get("signal_id") == "other")
                    update["$inc"].update(found=len(analysis["signals"]) - other, other=other,
                                          set_aside=int(bool(analysis["ignored_by"])))
                    record(doc_id, {"summary_text": analysis["summary"],
                                    "technologies": analysis["technologies"],
                                    "scout_take": analysis["scout_take"],
                                    "signals": analysis["signals"],
                                    "ignored_by": analysis["ignored_by"],
                                    "signals_hash": analysis["signals_hash"],
                                    "parts": analysis["parts"],
                                    "partial": analysis["partial"],
                                    "analysis_error": analysis["analysis_error"]})
        except Exception as exc:
            log.exception("re-check of %s failed", doc_id)
            update["$inc"]["failed"] = 1
            update["$inc"]["failed_reasons.unexpected error"] = 1
            record(doc_id, {"analysis_error": {"reason": "unexpected error",
                                               "detail": " ".join(str(exc).split())[:200],
                                               "at": now_utc()}})
        jobs.update_one({"_id": job_id}, update)

    try:
        with ThreadPoolExecutor(max_workers=get_settings().scout_concurrency,
                                thread_name_prefix="recheck") as pool:
            list(pool.map(one, ids))
        jobs.update_one({"_id": job_id}, {"$set": {"stage": "organizing technologies",
                                                   "heartbeat_at": now_utc()}})
        resolve_id = run_resolve_sync()
        jobs.update_one({"_id": job_id}, {"$set": {
            "status": "completed", "stage": "done", "resolve_id": resolve_id,
            "finished_at": now_utc()}})
        log.info("re-check %s completed (%d pages)", job_id, len(ids))
    except Exception as exc:
        log.exception("re-check %s failed", job_id)
        jobs.update_one({"_id": job_id}, {"$set": {
            "status": "failed", "error": str(exc)[:500], "finished_at": now_utc()}})


def reconcile_stale() -> None:
    """At boot: a job still 'running' died with the last process."""
    result = get_collection("recheck_jobs").update_many(
        {"status": "running"}, {"$set": {"status": "interrupted", "finished_at": now_utc()}})
    if result.modified_count:
        log.warning("marked %d re-check job(s) interrupted", result.modified_count)
