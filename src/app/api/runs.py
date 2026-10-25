"""Run endpoints: start, list, detail, terminate."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.scout.tools.collect import page_budget
from agent.supervisor.tools.sources import collectable_query
from app.services import busy, editions, evidence, page_texts
from app.services.db.mongo import get_collection
from app.services.runs.store import COLLECTIONS
from app.services.problems import didnt_finish, source_access
from app.services.runs import runner
from app.services.signals import snapshot
from app.services.timezone import request_tz

router = APIRouter()


class RunParams(BaseModel):
    categories: list[Literal["H1", "H2", "H3"]] | None = None
    max_sources_per_category: int | None = Field(default=None, ge=1)
    max_pages_per_source: int | None = Field(default=None, ge=1)


@router.post("/runs", status_code=201)
def start_run(params: RunParams | None = None, tz: str = Depends(request_tz)) -> dict:
    try:
        run_id = runner.start_run((params or RunParams()).model_dump(exclude_none=True))
    except busy.Busy as exc:
        raise HTTPException(status_code=409, detail=f"{exc} Start the run when it finishes.")
    # its times show in the zone of the person who started it
    get_collection("runs").update_one({"_id": run_id}, {"$set": {"tz": tz}})
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


@router.get("/runs/named")
def named(ids: str = Query("", description="comma-separated run ids")) -> dict:
    """When each of these runs started and what it was, a collection or a
    Find evidence job's reading: for naming evidence by its day, at any age."""
    wanted = [i for i in ids.split(",") if i][:200]
    return {"runs": {r["_id"]: {"at": r.get("run_start_date_time"), "tz": r.get("tz"),
                                "kind": "find_evidence" if (r.get("params") or {}).get("kind") == "find_evidence"
                                else "collection"}
                     for r in get_collection("runs").find({"_id": {"$in": wanted}},
                                                          {"run_start_date_time": 1, "tz": 1, "params.kind": 1})}}


@router.get("/runs")
def list_runs() -> dict:
    """The latest 100 runs, without their per-source rows; `incomplete`
    counts the websites that didn't finish, `failed_sources` the sources that
    stopped with an error."""
    runs = list(get_collection("runs").aggregate([
        {"$match": COLLECTIONS},
        {"$sort": {"run_start_date_time": -1}},
        {"$limit": 100},
        {"$addFields": {"unfinished": {"$filter": {
            "input": {"$ifNull": ["$sources", []]}, "cond": "$$this.incomplete"}},
            # sources that stopped with an error (a cancel isn't one): the list says how many
            "failed_sources": {"$size": {"$filter": {"input": {"$ifNull": ["$sources", []]}, "cond": {"$and": [
                {"$gt": [{"$ifNull": ["$$this.error", None]}, None]}, {"$ne": ["$$this.error", "run cancelled"]}]}}}}}},
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
    # its last step, judging the evidence of each technology with new pages, runs on its own record
    judged = get_collection("classify_runs").find_one({"trigger": f"after collection {run_id}"},
                                                      sort=[("started_at", -1)])
    run["classify"] = {"id": judged["_id"], **{k: judged.get(k) for k in ("status", "total", "done", "started_at", "finished_at",
                                                    "stopped_reason", "error")},
                       "failed": len(judged.get("failed") or []),
                       "failed_why": sorted({str(f.get("reason") or "no reason was recorded")[:120]
                                             for f in judged.get("failed") or []})[:3],
                       "finished_by": _finished_by(judged)} if judged else None
    # Organize's second part: known technologies named on this collection's pages (agent/tagger)
    linked = get_collection("tag_runs").find_one({"trigger": f"after collection {run_id}"}, sort=[("started_at", -1)])
    run["link"] = {k: linked.get(k) for k in ("status", "stage", "techs_named", "named_on", "done", "pages_about",
                                              "pages_mention", "pages_other", "error")} | {
        "id": linked["_id"], "linked": len(linked.get("linked_techs") or []), "failed": linked.get("failed") or []} \
        if linked else None
    run["after"] = after(run["run_start_date_time"]) if run.get("run_start_date_time") else None
    return run


def _finished_by(judged: dict) -> dict | None:
    """When a collection's Classify stopped part-way, the later Classify that
    judged what it left: the first one started after it that completed with
    nothing left to judge. None while the rest still wait."""
    if judged.get("status") not in ("stopped", "terminated"):
        return None
    later = get_collection("classify_runs").find_one(
        {"started_at": {"$gt": judged["started_at"]}, "status": "completed"},
        sort=[("started_at", 1)], projection={"done": 1, "finished_at": 1, "tz": 1})
    if later is None:
        return None
    return {"id": later["_id"], "done": later.get("done", 0), "at": later.get("finished_at"), "tz": later.get("tz")}


def after(started: str) -> dict:
    """What happened from this collection's start until the next one's: the
    assessment runs, Points of View written and editions published in that
    time, and which edition leaders see now (an edition's own name, if it
    has one: the portal names the others by their day). Recorded times only;
    the portal words it as "since this collection"."""
    following = get_collection("runs").find_one({**COLLECTIONS, "run_start_date_time": {"$gt": started}},
                                                {"run_start_date_time": 1}, sort=[("run_start_date_time", 1)])
    window: dict = {"$gte": started}
    if following:
        window["$lt"] = following["run_start_date_time"]
    assessments = [{"id": s["_id"], "status": s.get("status"), "started_at": s.get("started_at"),
                    "finished_at": s.get("finished_at"),
                    "techs_done": (s.get("progress") or {}).get("techs_done", 0),
                    "techs_total": (s.get("progress") or {}).get("techs_total", 0)}
                   for s in get_collection("scoring_runs").find({"started_at": window}, {"status": 1, "started_at": 1,
                                                                 "finished_at": 1, "progress": 1}).sort("started_at", 1)]
    povs = get_collection("povs").distinct("tech_id", {"composed_at": window})
    published = [{"id": e["_id"], "name": e.get("name"), "published_at": e["published_at"], "tz": e.get("tz")}
                 for e in get_collection("editions").find({"published_at": window}, {"name": 1, "published_at": 1, "tz": 1}).sort("published_at", 1)]
    seen = editions.latest(full=False)
    return {"next_collection": {"id": following["_id"], "started_at": following["run_start_date_time"]} if following else None,
            "assessments": assessments, "povs_written": len(povs), "published": published,
            "leaders_see": {"id": seen["_id"], "name": seen.get("name"), "published_at": seen["published_at"],
                            "tz": seen.get("tz")} if seen else None}


def analysis_errors(run_id: str) -> list[dict]:
    """This run's pages that couldn't be analysed (wholly or in part),
    grouped by reason, with an example detail and the sources involved."""
    groups = get_collection("documents").aggregate([
        # "analysis_error.reason" exists only on pages that failed: the partial index holds just those
        {"$match": {"run_id": run_id, "is_stub": False, "analysis_error.reason": {"$exists": True}}},
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
    collection = get_collection("documents")
    total = collection.count_documents(query)
    docs = list(collection.find(query, {"content_hash": 0})
                .sort("scraped_at", 1).skip(skip).limit(limit))
    if include_text:  # a stub shows the text of the version it repeats; none left means pruned
        texts = page_texts.get({evidence.version(d) for d in docs})
        for doc in docs:
            doc["extracted_text"] = texts.get(evidence.version(doc))
            doc["text_pruned"] = doc["extracted_text"] is None
    for doc in docs:
        doc["id"] = doc.pop("_id")
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
