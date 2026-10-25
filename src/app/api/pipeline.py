"""The pipeline: the state of all five steps in one call — Collect →
Signals → Organize → Assess → Points of View — and what is waiting for the
analyst. The portal polls it for the status pill, the process view and the
next-step prompts, from every open page: so what waits is read from the
answers kept ready for each technology (services/tech_status, the readiness
rule of services/evidence), and one answer serves every caller for a few
seconds."""

import threading
import time

from fastapi import APIRouter

from agent.analyzer import pov as pov_composer
from agent.analyzer.estimate import estimate
from app.api.runs import analysis_errors
from app.services import tech_status
from app.services.db.mongo import get_collection
from app.services.runs.store import COLLECTIONS
from app.services.problems import didnt_finish, problems, source_access
from app.services.signals import recheck, snapshot

router = APIRouter()


def _job(job: dict | None) -> dict | None:
    if not job:
        return None
    return {"id": job["_id"], "status": job.get("status"), "done": job.get("done", 0),
            "total": job.get("total", 0), **({"stage": job["stage"]} if job.get("stage") else {})}


def _for_analyst(stale: int, waiting: dict, to_assess: list[dict], to_write: list[dict]) -> list[dict]:
    """In process order — check, resume, assess, write — one item per kind
    that has work. Each comes from one waiting list, so a technology is in at
    most one."""
    items: list[dict] = []
    if stale:
        items.append({"kind": "check", "count": stale, "calls": stale})
    stopped = waiting["stopped_runs"]
    if stopped:
        run = stopped[0]
        items.append({"kind": "resume", "scoring_run_id": run["scoring_run_id"],
                      "started_at": run["started_at"], "count": len(run["tech_ids"]),
                      "calls": estimate(run["tech_ids"])["calls"]})
    if to_assess:
        items.append({"kind": "assess", **tech_status.offer("new_evidence")})
    if to_write:
        items.append({"kind": "write", "count": len(to_write), "calls": len(to_write)})
    return items


CACHE_S = 3  # every open page polls; one answer serves them all for this long
_cache: dict = {}
_cache_lock = threading.Lock()


@router.get("/pipeline")
def pipeline() -> dict:
    with _cache_lock:  # several tabs at once: one works it out, the others wait for that answer
        if _cache.get("at", 0) > time.time() - CACHE_S:
            return _cache["body"]
        body = _pipeline()
        _cache.update(at=time.time(), body=body)
        return body


def refresh_now() -> None:
    """Something just started or ended: the next poll works it out afresh."""
    _cache.pop("at", None)


def _pipeline() -> dict:
    runs = get_collection("runs")
    run = runs.find_one(COLLECTIONS, sort=[("run_start_date_time", -1)],
                        projection={"signal_list": 0, "crawl_settings": 0, "substage_history": 0})
    totals = (run or {}).get("totals") or {}
    collect = {"status": "none"}
    access = source_access()
    if run:
        collect = {"status": run["status"], "run_id": run["_id"], "stage": run.get("stage"),
                   "error": run.get("error"),
                   "started_at": run.get("run_start_date_time"),
                   "finished_at": run.get("run_end_date_time"),
                   "sources": totals.get("sources", 0), "pages": totals.get("pages_visited", 0),
                   "documents": totals.get("documents", 0),
                   "new_documents": totals.get("new_documents", 0),
                   "incomplete": sum(didnt_finish(s, access) for s in run.get("sources") or []),
                   "errors": sum(1 for s in run.get("sources") or []
                                 if s.get("error") and s["error"] != "run cancelled"),
                   "analysis_errors": analysis_errors(run["_id"])}

    stale = recheck.stale_count(snapshot.current_hash())
    job = recheck.latest_job()
    check = _job(job)
    if check:
        check.update(found=job.get("found", 0), other=job.get("other", 0),
                     set_aside=job.get("set_aside", 0), failed_reasons=job.get("failed_reasons") or {})
    signals = {"never_miss": totals.get("signals", 0), "other": totals.get("other_signals", 0),
               "set_aside": totals.get("set_aside", 0), "stale_pages": stale, "recheck": check}

    resolve = get_collection("resolves").find_one(sort=[("started_at", -1)]) or {}
    technologies = {"count": get_collection("technologies").estimated_document_count(),
                    "resolve_status": resolve.get("status"),
                    "resolved_at": resolve.get("finished_at"),
                    "new_names": resolve.get("to_resolve")}  # what the last Organize looked at

    tech_status.fresh()
    waiting = tech_status.waiting_lists()
    to_assess = waiting["with_new_evidence"]
    scoring = get_collection("scoring_runs").find_one(sort=[("started_at", -1)],
                                                      projection={"snapshot": 0, "technologies": 0})
    assess: dict = {"status": "none", "techs_with_new_evidence": len(to_assess)}
    if scoring:
        progress = scoring.get("progress") or {}
        assess.update(status=scoring["status"], scoring_run_id=scoring["_id"],
                      started_at=scoring.get("started_at"), finished_at=scoring.get("finished_at"),
                      techs_done=progress.get("techs_done", 0),
                      techs_total=progress.get("techs_total", 0),
                      skipped=len(scoring.get("skipped") or []))

    crun = get_collection("classify_runs").find_one(sort=[("started_at", -1)], projection={"tech_ids": 0})
    classify = {"status": crun["status"] if crun else "none",
                "pending": get_collection("tech_status").count_documents({"f.classify_waiting": True}),
                **({"run_id": crun["_id"], "done": crun.get("done", 0), "total": crun.get("total", 0),
                    "finished_at": crun.get("finished_at"), "stopped_reason": crun.get("stopped_reason"),
                    "unchanged": crun.get("unchanged", 0),
                    "failed": len(crun.get("failed") or []), "error": crun.get("error")} if crun else {})}

    to_write = waiting["pov_targets"]
    batch = pov_composer.batch_status()
    pov_job = _job(batch)
    if pov_job:
        pov_job["failed"] = len(batch.get("failed") or [])
    pov = {"composed": tech_status.written_povs(), "pending": len(to_write), "job": pov_job}
    tag = get_collection("tag_runs").find_one(sort=[("started_at", -1)],
                                              projection={"status": 1, "stage": 1, "done": 1, "techs_named": 1})
    linking = {"status": tag["status"], "stage": tag.get("stage"), "done": tag.get("done", 0),
               "total": tag.get("techs_named", 0)} if tag else {"status": "none"}
    return {"collect": collect, "signals": signals, "technologies": technologies, "classify": classify,
            "linking": linking,
            "assess": assess, "pov": pov, "problems": len(problems()),
            "for_analyst": _for_analyst(stale, waiting, to_assess, to_write),
            "updating": tech_status.pending()}  # technologies whose answers are being worked out again
