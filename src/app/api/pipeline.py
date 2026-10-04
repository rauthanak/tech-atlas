"""The pipeline: the state of all five steps in one call — Collect →
Signals → Organize → Assess → Points of View — and what is waiting for the
analyst. The portal polls it for the status pill, the process view and the
next-step prompts. What waits comes from the readiness rule
(services/evidence), the same one every screen reads."""

from fastapi import APIRouter

from agent.analyzer import pov as pov_composer
from agent.analyzer.estimate import estimate
from app.api.runs import analysis_errors
from app.api.scoring_runs import _pov_state
from app.services import evidence
from app.services.db.mongo import get_collection
from app.services.problems import didnt_finish, problems, source_access
from app.services.signals import recheck, snapshot

router = APIRouter()


def _job(job: dict | None) -> dict | None:
    if not job:
        return None
    return {"id": job["_id"], "status": job.get("status"), "done": job.get("done", 0),
            "total": job.get("total", 0), **({"stage": job["stage"]} if job.get("stage") else {})}


def _for_analyst(stale: int, all_states: dict, to_assess: list[dict], to_write: list[dict]) -> list[dict]:
    """In process order — check, resume, assess, write — one item per kind
    that has work. Each comes from one waiting list, so a technology is in at
    most one."""
    items: list[dict] = []
    if stale:
        items.append({"kind": "check", "count": stale, "calls": stale})
    stopped = evidence.stopped_runs(all_states)
    if stopped:
        run = stopped[0]
        items.append({"kind": "resume", "scoring_run_id": run["scoring_run_id"],
                      "started_at": run["started_at"], "count": len(run["tech_ids"]),
                      "calls": estimate(run["tech_ids"])["calls"]})
    if to_assess:
        ids = [t["tech_id"] for t in to_assess]
        cost = estimate(ids)
        items.append({"kind": "assess", "count": len(ids), "calls": cost["calls"],
                      "calls_max": cost["calls_max"], "tech_ids": ids})
    if to_write:
        items.append({"kind": "write", "count": len(to_write), "calls": len(to_write)})
    return items


@router.get("/pipeline")
def pipeline() -> dict:
    runs = get_collection("runs")
    run = runs.find_one(sort=[("run_start_date_time", -1)],
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
                    "resolved_at": resolve.get("finished_at")}

    all_states = evidence.states()
    to_assess = evidence.with_new_evidence(all_states)
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

    composed, to_write = _pov_state(all_states)
    batch = pov_composer.batch_status()
    pov_job = _job(batch)
    if pov_job:
        pov_job["failed"] = len(batch.get("failed") or [])
    pov = {"composed": len(composed), "pending": len(to_write), "job": pov_job}
    return {"collect": collect, "signals": signals, "technologies": technologies,
            "assess": assess, "pov": pov, "problems": len(problems()),
            "for_analyst": _for_analyst(stale, all_states, to_assess, to_write)}
