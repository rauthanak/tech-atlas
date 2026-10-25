"""Scoring-run endpoints (Phase C). A scoring run is decoupled from scout
runs: it assesses the technologies the latest resolve produced, under the
config snapshot frozen at start. Recompute re-derives TORA from stored scores
with current weights (no LLM); a re-score is simply a new run."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.analyzer import engine
from agent.analyzer.agent import resume_scoring_run, start_scoring_run
from agent.analyzer import pov as pov_composer
from agent.analyzer.estimate import estimate
from agent.analyzer.pov import compose_pov
from app.services import busy, decisions, editions, effective, evidence, watch
from app.services.db.mongo import get_collection
from app.services.tech_status import RUN_MAX
from app.services.timezone import request_tz
from app.services.display import display_name

router = APIRouter()


class ScoringRunParams(BaseModel):
    # at least one: an empty list would fall through to every enabled technology
    technologies: list[str] | None = Field(default=None, min_length=1, max_length=RUN_MAX,
                                           description="explicit tech_ids")
    # or a set the lists offer (services/tech_status.SETS): the server picks them, the first RUN_MAX
    select: Literal["new_evidence", "ready"] | None = None
    top: int | None = Field(default=None, ge=1, le=200,
                            description="top N technologies by doc_count")
    min_docs: int | None = Field(default=None, ge=1)
    engine: Literal["stacked", "per_measure"] | None = None  # overrides the Weights & Grid setting for this run


@router.get("/scoring/preview")
def scoring_preview(min_docs: int = 1, technologies: str | None = None) -> dict:
    """How many technologies a run with this evidence floor (or this
    comma-separated list of ids) would assess, and about how many model calls
    — the portal shows it before anything starts."""
    query: dict = {"enabled": True}
    if technologies:
        query["_id"] = {"$in": [t.strip() for t in technologies.split(",") if t.strip()]}
    elif min_docs > 1:
        query["doc_count"] = {"$gte": min_docs}
    return estimate(get_collection("technologies").distinct("_id", query))


class PreviewIds(BaseModel):
    technologies: list[str] = Field(min_length=1, max_length=200_000)


@router.post("/scoring/preview")
def scoring_preview_ids(body: PreviewIds) -> dict:
    """The same as GET /scoring/preview for a list too long for an address
    (choosing thousands on the Technologies list): one request, not one per 100."""
    return estimate(get_collection("technologies").distinct("_id", {"enabled": True, "_id": {"$in": body.technologies}}))


@router.post("/scoring/runs", status_code=202)
def create_run(params: ScoringRunParams) -> dict:
    from app.services import tech_status
    left = 0
    if params.select:
        ids = tech_status.chosen(params.select)
        if not ids:
            raise HTTPException(status_code=409, detail="Nothing in that list now: it was assessed or changed since.")
        params.technologies, left = ids[:RUN_MAX], max(0, len(ids) - RUN_MAX)
    try:
        run_id = start_scoring_run(params.model_dump(exclude_none=True, exclude={"select"}))
    except busy.Busy as exc:
        raise HTTPException(status_code=409, detail=f"{exc} Assessments can start when it finishes.")
    if run_id is None:
        raise HTTPException(status_code=409, detail="a scoring run is already active")
    return {"scoring_run_id": run_id, "left_waiting": left}


@router.get("/scoring/runs")
def list_runs(limit: int = 50) -> dict:
    # the per-technology records (gates, tech_calls) are read by the engine only
    runs = list(get_collection("scoring_runs")
                .find({}, {"snapshot": 0, "gates": 0, "tech_calls": 0})
                .sort("started_at", -1).limit(max(1, min(limit, 200))))
    return {"scoring_runs": runs}


@router.get("/scoring/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """An assessment run and what its page says about the whole of it: how
    many assessments, its fabrics, the collections its evidence came from,
    and the technologies left (a stopped run's resume). Its rows come from
    /rows, 50 at a time."""
    run = get_collection("scoring_runs").find_one({"_id": run_id}, {"snapshot": 0, "gates": 0, "tech_calls": 0})
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown scoring run {run_id!r}")
    assessments = get_collection("assessments")
    mine = {"scoring_run_id": run_id}
    fabrics = sorted({(a["fabric_id"], a.get("fabric") or a["fabric_id"])
                      for a in assessments.find(mine, {"fabric_id": 1, "fabric": 1})}, key=lambda f: f[1])
    done = set(assessments.distinct("tech_id", mine)) | {s["tech_id"] for s in run.get("skipped") or []}
    return {**run, "assessed": assessments.count_documents(mine),
            "fabrics": [{"id": i, "name": n} for i, n in fabrics],
            # older assessments didn't record the collections they read
            "evidence_runs": sorted(assessments.distinct("evidence_runs", mine))
            if assessments.find_one({**mine, "evidence_runs": {"$exists": True}}, {"_id": 1}) else None,
            "left": [t["tech_id"] for t in run.get("technologies") or [] if t["tech_id"] not in done]}


ROW_SORTS = {"technology", "docs", "priority", "horizon"}  # else a score's key (market_potential…) or an extra (X1…)


@router.get("/scoring/runs/{run_id}/rows")
def run_rows(run_id: str, fabric: str | None = None, q: str = "", axis: Literal["priority", "priority_by_disruptiveness"] = "priority",
             cell: str | None = None, sort: str = "market_potential", dir: int = -1, skip: int = 0,
             limit: int = Query(50, ge=1, le=200)) -> dict:
    """An assessment run's table, a page at a time: people's choices applied
    (a person's priority wins), filtered by fabric and search, the grid's
    counts by cell (how-soon band × how-big or threat band) over those, then
    one cell when chosen, sorted, and `limit` rows from `skip`."""
    query: dict = {"scoring_run_id": run_id, **({"fabric_id": fabric} if fabric else {})}
    if q.strip():
        query["technology"] = {"$regex": re.escape(q.strip().lower())}
    rows = list(get_collection("assessments").find(query, {"dossier_pages": 0, "use_cases": 0, "watch_metrics": 0,
                                                           "suggested_bottlenecks": 0, "suggested_use_cases": 0}))
    applied = _applied(rows)
    out = []
    for a in rows:
        e = applied[a["_id"]]
        placement = dict(e["placement"])
        override = _override(e)
        if override:
            placement["priority"] = override["priority"]  # the priority in force: the grid, filters and sort use it
        out.append({k: a.get(k) for k in ("_id", "technology", "tech_id", "fabric", "fabric_id", "doc_count", "extras",
                                          "tora_basis", "evidence_runs")}
                   | {"tora": e["tora"], "placement": placement, **({"override": override} if override else {})})

    def cell_of(r: dict) -> str | None:
        p = r["placement"] or {}
        across = (p.get("timeline") or {}).get("band")
        down = (p.get("potential") if axis == "priority" else p.get("disruptiveness") or {}) or {}
        return f"{across}_{down.get('band')}" if across and down.get("band") else None

    grid: dict[str, int] = {}
    for r in out:
        c = cell_of(r)
        if c:
            grid[c] = grid.get(c, 0) + 1
    shown = [r for r in out if not cell or cell_of(r) == cell]

    def key(r: dict):
        p = r["placement"] or {}
        if sort == "technology":
            return r["technology"] or ""
        if sort == "docs":
            return r["doc_count"] or 0
        if sort == "priority":
            return int((p.get(axis) or "P9")[1:])
        if sort == "horizon":
            return p.get("horizon") or "H9"
        if sort.startswith("X"):
            v = (r.get("extras") or {}).get(sort)
            return -1 if v is None else v
        v = ((r.get("tora") or {}).get(sort) or {}).get("score")
        return -1 if v is None else v

    shown.sort(key=lambda r: (key(r), r["technology"] or ""), reverse=dir < 0)
    return {"rows": shown[skip:skip + limit], "total": len(shown), "scoped": len(out), "grid": grid}


_applied, _override = effective.applied_rows, effective.override_view  # services/effective


@router.get("/scoring/runs/{run_id}/assessments/{assessment_id}")
def get_assessment(run_id: str, assessment_id: str) -> dict:
    a = get_collection("assessments").find_one(
        {"_id": assessment_id, "scoring_run_id": run_id})
    if a is None:
        raise HTTPException(status_code=404, detail=f"unknown assessment {assessment_id!r}")
    return a


@router.post("/scoring/runs/{run_id}/resume", status_code=202)
def resume(run_id: str) -> dict:
    """Re-open a failed or terminated run — existing assessments are kept,
    only the missing work re-runs."""
    try:
        resumed = resume_scoring_run(run_id)
    except busy.Busy as exc:
        raise HTTPException(status_code=409, detail=f"{exc} Resume when it finishes.")
    if not resumed:
        raise HTTPException(status_code=409,
                            detail="run is unknown, already active, completed, "
                                   "or another run is running")
    return {"status": "resumed"}


@router.post("/scoring/runs/{run_id}/terminate")
def terminate(run_id: str) -> dict:
    if not engine.request_terminate(run_id):
        raise HTTPException(status_code=409, detail="run is not running")
    return {"status": "terminating"}


def _rewrite_targets(all_states: dict) -> list[dict]:
    """What "Rewrite all" covers: every switched-on technology with a latest
    assessment, each written from it."""
    return [t for t in evidence.latest_assessments(all_states) if all_states[t["tech_id"]]["state"] != "off"]


@router.get("/scoring/crossed")
def crossed() -> dict:
    """Metrics to watch that crossed their threshold: each switched-on
    technology's latest assessment says, for the metrics the one before it
    set, which crossed, from a page it read (engine.watch_result), with
    people's choices applied (services/watch)."""
    rows, found, candidates = [], [], []
    for a in get_collection("assessments").aggregate([
            {"$match": {"watch_metrics.crossed": True}},
            {"$sort": {"created_at": -1}},
            {"$group": {"_id": "$tech_id", "watch_metrics": {"$first": "$watch_metrics"},
                        "created_at": {"$first": "$created_at"}, "scoring_run_id": {"$first": "$scoring_run_id"}}}]):
        candidates.append(a)
    # only the technologies these name: switched on, with their labels
    labels = {t["_id"]: display_name(t) for t in get_collection("technologies").find(
        {"_id": {"$in": [a["_id"] for a in candidates]}, "enabled": True}, {"label": 1, "name": 1})}
    for a in candidates:
        latest = get_collection("assessments").find_one({"tech_id": a["_id"]}, {"created_at": 1},
                                                        sort=[("created_at", -1)])
        if a["_id"] not in labels or (latest and latest["created_at"] != a["created_at"]):
            continue  # switched off, or a newer assessment has moved on
        found.append(a)
    # as people left them: a person's threshold shows; a person's "not crossed" takes it off the list
    chosen = decisions.by_tech(decisions.active([a["_id"] for a in found], ["watch_threshold", "watch_crossed"]))
    for a in found:
        rows += [{"tech_id": a["_id"], "technology": labels.get(a["_id"], a["_id"]), "assessed_at": a["created_at"],
                  "scoring_run_id": a["scoring_run_id"], **m}
                 for m in watch.apply(a["watch_metrics"], chosen.get(a["_id"], [])) if m.get("crossed") is True]
    return {"crossed": sorted(rows, key=lambda r: r["assessed_at"], reverse=True)}


@router.get("/scoring/povs")
def all_povs(q: str = "", fabric: str | None = None, priority: str | None = None, newer: bool = False,
             unsent: bool = False, sort: Literal["newest", "priority"] = "newest", skip: int = 0,
             limit: int | None = Query(None, ge=1, le=200)) -> dict:
    """Every written Point of View of a switched-on technology, with the
    pages new since it was written and its placements; how many switched-off
    technologies' ones are left out; the technologies waiting for one; how
    many a rewrite covers; and the latest compose-all job — one poll drives
    the whole Points of View list. Each row, and what the list filters and
    sorts by, is kept ready with the technology's answers (services/tech_status),
    so a page of the list reads its own rows only."""
    import re
    from app.services import tech_status
    tech_status.fresh()
    status, kept = get_collection("tech_status"), get_collection("tech_status_rows")
    written = {"f.pov_at": {"$ne": None}, "f.status": {"$ne": "off"}}
    off = get_collection("technologies").distinct("_id", {"enabled": False})
    common = {"switched_off": len(get_collection("povs").distinct("tech_id", {"tech_id": {"$in": off}})),
              "assessed": tech_status.rewrite_count(), "job": pov_composer.batch_status()}

    def rows(match: dict, order: list, skip_: int = 0, limit_: int = 0) -> list[dict]:
        ids = [r["_id"] for r in status.find(match, {"_id": 1}).sort(order).skip(skip_).limit(limit_)]
        by_id = {r["_id"]: r["pov"] for r in kept.find({"_id": {"$in": ids}}, {"pov": 1})}
        page = [by_id[i] for i in ids if by_id.get(i)]
        seen = editions.views([p["tech_id"] for p in page])
        for p in page:
            p["views"] = seen.get(p["tech_id"])
        return page

    newest = [("f.pov_at", -1), ("_id", 1)]
    if limit is None:  # every one, as before (no filter, newest first)
        return {"povs": rows(written, newest), "uncomposed": tech_status.waiting_lists()["pov_targets"], **common}
    # a page of the list, filtered and sorted in the database, with the counts the page's lines and filters show
    shown_edition = editions.latest(full=False)
    published = shown_edition["published_at"] if shown_edition else None
    unsent_n = status.count_documents({**written, "f.pov_at": {"$gt": published}}) if published else 0
    match = dict(written)
    if q.strip():
        match["f.pov_search"] = re.compile(re.escape(q.strip().lower()))
    if fabric:
        match["f.pov_fabrics"] = fabric
    if priority:
        match["f.pov_prio" if fabric else "f.pov_prios"] = f"{fabric}:{priority}" if fabric else priority
    if newer:
        match["f.new_since_pov"] = {"$gt": 0}
    if unsent and unsent_n:  # none left: the filter lets go
        match["f.pov_at"] = {"$gt": published}
    order = [("f.pov_best", 1), ("f.pov_label", 1), ("_id", 1)] if sort == "priority" else newest
    names = {f["_id"]: f.get("name") or f["_id"] for f in get_collection("fabrics").find({}, {"name": 1})}
    fabrics = sorted(((i, names.get(i, i)) for i in status.distinct("f.pov_fabrics", written)), key=lambda f: f[1])
    return {"povs": rows(match, order, max(0, skip), limit), "total": status.count_documents(match),
            "count": status.count_documents(written),
            "behind": status.count_documents({**written, "f.new_since_pov": {"$gt": 0}}), "unsent": unsent_n,
            "fabrics": [{"id": i, "name": n} for i, n in fabrics],
            "uncomposed_count": status.count_documents({"f.state": "no_pov"}), **common}


class ComposeAllParams(BaseModel):
    recompose: bool = False  # True: also rewrite every written Point of View


@router.post("/scoring/povs/compose_all", status_code=202)
def compose_all(params: ComposeAllParams | None = None, tz: str = Depends(request_tz)) -> dict:
    """One background job, one LLM call per technology (scoring_concurrency-
    wide pool). Default: the technologies waiting for a Point of View.
    recompose=true: every switched-on technology with a latest assessment,
    each written from it — existing Points of View from that run are
    replaced and their version bumps. Switched-off ones are left out."""
    all_states = evidence.states()
    targets = (_rewrite_targets(all_states) if params and params.recompose
               else evidence.pov_targets(all_states))
    if not targets:
        raise HTTPException(status_code=409, detail="nothing to compose")
    job_id = pov_composer.start_compose_all(
        [{"scoring_run_id": t["scoring_run_id"], "tech_id": t["tech_id"]}
         for t in targets],
        recompose=bool(params and params.recompose), tz=tz)
    if job_id is None:
        raise HTTPException(status_code=409, detail="a compose-all job is already running")
    return {"job_id": job_id, "total": len(targets)}


@router.get("/scoring/runs/{run_id}/povs")
def list_povs(run_id: str) -> dict:
    return {"povs": list(get_collection("povs")
                         .find({"scoring_run_id": run_id}, {"sections": 0}))}


@router.get("/scoring/runs/{run_id}/pov/{tech_id}")
def get_pov(run_id: str, tech_id: str) -> dict:
    pov = get_collection("povs").find_one({"_id": f"{run_id}:{tech_id}"})
    if pov is None:
        raise HTTPException(status_code=404, detail="no PoV composed yet for this technology")
    run = get_collection("scoring_runs").find_one(
        {"_id": run_id}, {"snapshot.fabrics._id": 1, "snapshot.fabrics.name": 1}) or {}
    rows = list(get_collection("assessments").find(
        {"scoring_run_id": run_id, "tech_id": tech_id}, {"fabric_id": 1}))
    # the text, and what the page shows beside it, numbered in one list of sources
    return {**pov, **pov_composer.pov_view(pov), "not_assessed_in": evidence.not_assessed_in(run, rows)}


@router.post("/scoring/runs/{run_id}/pov/{tech_id}")
def create_pov(run_id: str, tech_id: str, tz: str = Depends(request_tz)) -> dict:
    """Compose (or recompose) the PoV — one LLM call narrating the stored
    assessment; the scores themselves never move."""
    try:
        return compose_pov(run_id, tech_id, tz)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/scoring/runs/{run_id}/recompute")
def recompute(run_id: str) -> dict:
    """Re-derive TORA roll-ups from stored measure scores using the CURRENT
    measure weights — free, no LLM. Use after weight edits."""
    try:
        count = engine.recompute_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    from app.services import tech_status
    tech_status.touch(get_collection("assessments").distinct("tech_id", {"scoring_run_id": run_id}))
    return {"recomputed": count}
