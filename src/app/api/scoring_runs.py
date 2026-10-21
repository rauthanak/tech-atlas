"""Scoring-run endpoints (Phase C). A scoring run is decoupled from scout
runs: it assesses the technologies the latest resolve produced, under the
config snapshot frozen at start. Recompute re-derives TORA from stored scores
with current weights (no LLM); a re-score is simply a new run."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.analyzer import engine
from agent.analyzer.agent import resume_scoring_run, start_scoring_run
from agent.analyzer import pov as pov_composer
from agent.analyzer.estimate import estimate
from agent.analyzer.pov import compose_pov
from app.services import busy, evidence
from app.services.db.mongo import get_collection
from app.services.timezone import request_tz

router = APIRouter()


class ScoringRunParams(BaseModel):
    # at least one: an empty list would fall through to every enabled technology
    technologies: list[str] | None = Field(default=None, min_length=1, max_length=2000,
                                           description="explicit tech_ids")
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


@router.post("/scoring/runs", status_code=202)
def create_run(params: ScoringRunParams) -> dict:
    try:
        run_id = start_scoring_run(params.model_dump(exclude_none=True))
    except busy.Busy as exc:
        raise HTTPException(status_code=409, detail=f"{exc} Assessments can start when it finishes.")
    if run_id is None:
        raise HTTPException(status_code=409, detail="a scoring run is already active")
    return {"scoring_run_id": run_id}


@router.get("/scoring/runs")
def list_runs(limit: int = 50) -> dict:
    runs = list(get_collection("scoring_runs")
                .find({}, {"snapshot": 0})
                .sort("started_at", -1).limit(max(1, min(limit, 200))))
    return {"scoring_runs": runs}


@router.get("/scoring/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = get_collection("scoring_runs").find_one({"_id": run_id}, {"snapshot": 0})
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown scoring run {run_id!r}")
    assessments = list(get_collection("assessments")
                       .find({"scoring_run_id": run_id}, {"dossier_pages": 0})  # page lists can be long
                       .sort("technology", 1))
    applied = _applied(assessments)
    for a in assessments:  # people's choices applied; a person's priority wins, the computed one stays in placement
        e = applied[a["_id"]]
        a.update(tora=e["tora"], placement=e["placement"], **({"override": _override(e)} if _override(e) else {}))
        a.pop("measures", None)
    return {**run, "assessments": assessments}


def _applied(rows: list[dict]) -> dict[str, dict]:
    """Each assessment with people's choices applied (services/effective), by
    id: a hand score can move its placement, an override is its priority."""
    from app.services import decisions, effective
    chosen = decisions.active(sorted({a["tech_id"] for a in rows}))
    measures, config = list(get_collection("measures").find()), list(get_collection("scoring_config").find())
    return {a["_id"]: effective.apply(a, chosen, measures, config) for a in rows}


def _override(applied: dict) -> dict | None:
    """A person's priority in force, as the run page and the Points of View list show it."""
    o = applied["effective"]["override"]
    return {"priority": o["value"], "reason": o["reason"], "at": o["at"], "tz": o["tz"],
            "computed": o["computed"]} if o else None


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


def _pov_state(all_states: dict | None = None) -> tuple[list[dict], list[dict]]:
    """(written Points of View, technologies waiting for one) — shared by the
    list, compose-all and the pipeline, so the batch writes exactly what the
    list shows. One Point of View per technology: only technologies still in
    the register and switched on count, and the newest written one wins.
    Waiting follows the readiness rule (services/evidence): none written from
    the latest assessment's run."""
    all_states = evidence.states() if all_states is None else all_states
    existing = set(get_collection("technologies").distinct("_id", {"enabled": {"$ne": False}}))
    povs, seen = [], set()
    for p in (get_collection("povs")
              .find({}, {"sections.headline": 1, "scoring_run_id": 1,
                         "tech_id": 1, "technology": 1, "version": 1,
                         "composed_at": 1, "composed_tz": 1, "assessment_ids": 1})
              .sort("composed_at", -1)):
        if p["tech_id"] in existing and p["tech_id"] not in seen:
            seen.add(p["tech_id"])
            povs.append(p)
    return povs, evidence.pov_targets(all_states)


def _rewrite_targets(all_states: dict) -> list[dict]:
    """What "Rewrite all" covers: every switched-on technology with a latest
    assessment, each written from it."""
    return [t for t in evidence.latest_assessments(all_states) if all_states[t["tech_id"]]["state"] != "off"]


@router.get("/scoring/povs")
def all_povs() -> dict:
    """Every written Point of View of a switched-on technology, with the
    pages new since it was written and its placements; how many switched-off
    technologies' ones are left out; the technologies waiting for one; how
    many a rewrite covers; and the latest compose-all job — one poll drives
    the whole Points of View list."""
    all_states = evidence.states()
    povs, uncomposed = _pov_state(all_states)
    names = {t["_id"]: t["name"] for t in get_collection("technologies").find(
        {"_id": {"$in": [p["tech_id"] for p in povs]}}, {"name": 1})}
    rows = {a["_id"]: a for a in get_collection("assessments").find(
        {"_id": {"$in": [i for p in povs for i in p.get("assessment_ids") or []]}}, {"watch_metrics": 0})}
    applied = _applied(list(rows.values()))
    for p in povs:
        mine = sorted((rows[i] for i in p.get("assessment_ids") or [] if i in rows),
                      key=lambda a: a["fabric_id"])
        read = evidence.reading(mine)
        p["new_since_written"] = len(evidence.new_pages(names[p["tech_id"]], read)) if read else None
        p["assessed_at"] = read["assessed_at"] if read else None  # the assessment it was written from
        p["placements"] = [{"fabric_id": e["fabric_id"], "fabric": e.get("fabric"), "priority": e["effective"]["priority"],
                            "computed_priority": e["effective"]["computed_priority"], "override": _override(e),
                            "horizon": e["effective"]["horizon"]} for e in (applied[a["_id"]] for a in mine)]
        p.pop("assessment_ids", None)
    off = get_collection("technologies").distinct("_id", {"enabled": False})
    return {"povs": povs, "uncomposed": uncomposed,
            "switched_off": len(get_collection("povs").distinct("tech_id", {"tech_id": {"$in": off}})),
            "assessed": len(_rewrite_targets(all_states)),
            "job": pov_composer.batch_status()}


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
    return {"recomputed": count}
