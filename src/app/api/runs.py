"""Run endpoints: start, list, detail, terminate."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.scout.tools.collect import page_budget
from agent.supervisor.tools.sources import collectable_query
from app.services import busy
from app.services.db.mongo import get_collection
from app.services.runs.store import COLLECTIONS
from app.services.problems import didnt_finish, source_access
from app.services.runs import runner
from app.services.signals import snapshot

router = APIRouter()


class RunParams(BaseModel):
    categories: list[Literal["H1", "H2", "H3"]] | None = None
    max_sources_per_category: int | None = Field(default=None, ge=1)
    max_pages_per_source: int | None = Field(default=None, ge=1)


@router.post("/runs", status_code=201)
def start_run(params: RunParams | None = None) -> dict:
    try:
        run_id = runner.start_run((params or RunParams()).model_dump(exclude_none=True))
    except busy.Busy as exc:
        raise HTTPException(status_code=409, detail=f"{exc} Start the run when it finishes.")
    return {"id": run_id, "status": "running"}


@router.get("/runs/preview")
def preview() -> dict:
    """What a collection started now would cover — the portal words it as
    the cost before anything starts."""
    sources, query = get_collection("sources"), collectable_query()
    data_sources = sources.count_documents({**query, "access": "query"})
    return {"websites": sources.count_documents(query) - data_sources,
            "data_sources": data_sources,
            "pages_per_source": page_budget(snapshot.build())}


@router.get("/runs")
def list_runs() -> dict:
    """The latest 100 runs, without their per-source rows; `incomplete`
    counts the websites that didn't finish."""
    runs = list(get_collection("runs").aggregate([
        {"$match": COLLECTIONS},
        {"$sort": {"run_start_date_time": -1}},
        {"$limit": 100},
        {"$addFields": {"unfinished": {"$filter": {
            "input": {"$ifNull": ["$sources", []]}, "cond": "$$this.incomplete"}}}},
        {"$project": {"sources": 0, "params": 0, "signal_list": 0, "crawl_settings": 0,
                      "unfinished.incomplete_note": 0}},
    ]))
    access = source_access()
    for run in runs:
        run["incomplete"] = sum(didnt_finish(s, access) for s in run.pop("unfinished"))
    for run in runs:
        run["id"] = run.pop("_id")
    return {"runs": runs}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = get_collection("runs").find_one({"_id": run_id})
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    run["id"] = run.pop("_id")
    if run.get("resolve_id"):  # attach the chained resolve for the drill-down view
        resolve = get_collection("resolves").find_one({"_id": run["resolve_id"]})
        if resolve:
            resolve["id"] = resolve.pop("_id")
            run["resolve"] = resolve
    run.pop("signal_list", None)  # the snapshot's rows are bulky; the hash identifies them
    run["used_in"] = _used_in(run_id)
    latest = get_collection("scoring_runs").find_one(
        sort=[("started_at", -1)], projection={"status": 1, "started_at": 1})
    # timing only — the portal labels it "Latest workspace activity"
    run["latest_activity"] = ({"scoring_run_id": latest["_id"], "status": latest["status"],
                               "started_at": latest["started_at"]} if latest else None)
    run["assessments_before_upgrade"] = get_collection("assessments").count_documents(
        {"evidence_runs": {"$exists": False}})
    run["analysis_errors"] = analysis_errors(run_id)
    return run


def analysis_errors(run_id: str) -> list[dict]:
    """This run's pages that couldn't be analysed (wholly or in part),
    grouped by reason, with an example detail and the sources involved."""
    groups = get_collection("documents").aggregate([
        {"$match": {"run_id": run_id, "is_stub": False, "analysis_error": {"$ne": None}}},
        {"$sort": {"analysis_error.at": -1}},
        {"$group": {"_id": "$analysis_error.reason", "detail": {"$first": "$analysis_error.detail"},
                    "pages": {"$sum": 1}, "sources": {"$addToSet": "$source_id"}}},
        {"$sort": {"pages": -1, "_id": 1}},
    ])
    return [{"reason": g["_id"], "detail": g["detail"], "pages": g["pages"],
             "sources": sorted(g["sources"])} for g in groups]


def _used_in(run_id: str) -> list[dict]:
    """Recorded facts only: the assessments whose evidence actually included
    this run's pages (evidence_runs), grouped by scoring run, with the
    number of Points of View built from them."""
    groups: dict[str, list[dict]] = {}
    for a in get_collection("assessments").find({"evidence_runs": run_id},
                                                {"scoring_run_id": 1, "tech_id": 1}):
        groups.setdefault(a["scoring_run_id"], []).append(a)
    used = []
    for scoring_run_id, assessments in groups.items():
        scoring = get_collection("scoring_runs").find_one(
            {"_id": scoring_run_id}, {"status": 1, "started_at": 1}) or {}
        used.append({"scoring_run_id": scoring_run_id, "status": scoring.get("status"),
                     "started_at": scoring.get("started_at"),
                     "technologies": len({a["tech_id"] for a in assessments}),
                     "povs": get_collection("povs").count_documents(
                         {"assessment_ids": {"$in": [a["_id"] for a in assessments]}})})
    return sorted(used, key=lambda u: u["started_at"] or "", reverse=True)


@router.get("/runs/{run_id}/documents")
def run_documents(run_id: str, source_id: str | None = None,
                  include_text: bool = False,
                  limit: int = Query(default=20, ge=1, le=100),
                  skip: int = Query(default=0, ge=0)) -> dict:
    """Documents collected in a run, optionally for one source, paged (a page
    of full texts is heavy). Pass include_text=true for the as-is extracted
    text (a stub's text is resolved from the document it references)."""
    query: dict = {"run_id": run_id}
    if source_id:
        query["source_id"] = source_id
    projection: dict = {"content_hash": 0}
    if not include_text:
        projection["extracted_text"] = 0
    collection = get_collection("documents")
    total = collection.count_documents(query)
    docs = list(collection.find(query, projection)
                .sort("scraped_at", 1).skip(skip).limit(limit))
    for doc in docs:
        doc["id"] = doc.pop("_id")
        if include_text and doc.get("is_stub") and doc.get("ref_doc_id"):
            ref = collection.find_one({"_id": doc["ref_doc_id"]},
                                      {"extracted_text": 1, "text_pruned": 1})
            if ref:
                doc["extracted_text"] = ref.get("extracted_text")
                doc["text_pruned"] = ref.get("text_pruned", False)
    return {"documents": docs, "total": total}


@router.post("/runs/{run_id}/terminate")
def terminate_run(run_id: str) -> dict:
    run = get_collection("runs").find_one({"_id": run_id}, {"status": 1})
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if run["status"] not in ("running",):
        raise HTTPException(status_code=409, detail=f"run is {run['status']}, not running")
    runner.request_terminate(run_id)
    return {"id": run_id, "status": "terminating"}
