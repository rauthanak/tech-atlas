"""Scoring-run endpoints (Phase C). A scoring run is decoupled from scout
runs: it assesses the technologies the latest resolve produced, under the
config snapshot frozen at start. Recompute re-derives TORA from stored scores
with current weights (no LLM); a re-score is simply a new run."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.analyzer import engine
from agent.analyzer.agent import resume_scoring_run, start_scoring_run
from agent.analyzer import pov as pov_composer
from agent.analyzer.pov import compose_pov
from app.services.db.mongo import get_collection

router = APIRouter()


class ScoringRunParams(BaseModel):
    technologies: list[str] | None = Field(default=None, max_length=200,
                                           description="explicit tech_ids")
    top: int | None = Field(default=None, ge=1, le=200,
                            description="top N technologies by doc_count")
    min_docs: int | None = Field(default=None, ge=1)


@router.get("/scoring/preview")
def scoring_preview(min_docs: int = 1) -> dict:
    """How many technologies a run with this evidence floor would assess —
    the portal shows it live so 'score everything' is an informed choice."""
    query: dict = {"enabled": True}
    if min_docs > 1:
        query["doc_count"] = {"$gte": min_docs}
    return {"technologies": get_collection("technologies").count_documents(query)}


@router.post("/scoring/runs", status_code=202)
def create_run(params: ScoringRunParams) -> dict:
    run_id = start_scoring_run(params.model_dump(exclude_none=True))
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
                       .find({"scoring_run_id": run_id},
                             {"measures": 0})
                       .sort("technology", 1))
    return {**run, "assessments": assessments}


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
    if not resume_scoring_run(run_id):
        raise HTTPException(status_code=409,
                            detail="run is unknown, already active, completed, "
                                   "or another run is running")
    return {"status": "resumed"}


@router.post("/scoring/runs/{run_id}/terminate")
def terminate(run_id: str) -> dict:
    if not engine.request_terminate(run_id):
        raise HTTPException(status_code=409, detail="run is not running")
    return {"status": "terminating"}


def _newest_assessed() -> list[dict]:
    """Every technology still in the register, with the NEWEST completed
    scoring run that assessed it — the composable universe."""
    existing = set(get_collection("technologies").distinct("_id"))
    out, seen = [], set()
    for run in get_collection("scoring_runs").find(
            {"status": "completed"}, {"started_at": 1}).sort("started_at", -1).limit(10):
        for row in get_collection("assessments").aggregate([
                {"$match": {"scoring_run_id": run["_id"]}},
                {"$group": {"_id": "$tech_id", "technology": {"$first": "$technology"}}}]):
            if row["_id"] in existing and row["_id"] not in seen:
                seen.add(row["_id"])
                out.append({"scoring_run_id": run["_id"],
                            "tech_id": row["_id"],
                            "technology": row["technology"],
                            "run_started_at": run["started_at"]})
    out.sort(key=lambda t: t["technology"])
    return out


def _pov_state() -> tuple[list[dict], list[dict]]:
    """(composed povs, uncomposed assessed techs) — shared by the tab's GET
    and the compose-all POST, so the batch targets exactly what the tab shows.
    One PoV per technology: only techs still in the register count, the newest
    composed PoV per tech wins, and a tech with any PoV is never 'uncomposed'
    (merged-away or superseded entries drop out everywhere)."""
    existing = set(get_collection("technologies").distinct("_id"))
    povs, seen = [], set()
    for p in (get_collection("povs")
              .find({}, {"sections.headline": 1, "scoring_run_id": 1,
                         "tech_id": 1, "technology": 1, "version": 1,
                         "composed_at": 1})
              .sort("composed_at", -1)):
        if p["tech_id"] in existing and p["tech_id"] not in seen:
            seen.add(p["tech_id"])
            povs.append(p)
    uncomposed = [t for t in _newest_assessed() if t["tech_id"] not in seen]
    return povs, uncomposed


@router.get("/scoring/povs")
def all_povs() -> dict:
    """Every composed PoV, the assessed technologies without one yet, and the
    latest compose-all job — one poll drives the whole Points of View tab."""
    povs, uncomposed = _pov_state()
    return {"povs": povs, "uncomposed": uncomposed,
            "job": pov_composer.batch_status()}


class ComposeAllParams(BaseModel):
    recompose: bool = False  # True: also rewrite every composed PoV


@router.post("/scoring/povs/compose_all", status_code=202)
def compose_all(params: ComposeAllParams | None = None) -> dict:
    """One background job, one LLM call per technology (scoring_concurrency-
    wide pool). Default: only techs without a PoV. recompose=true: every
    assessed technology, each from its newest completed scoring run —
    existing PoVs are replaced and their version bumps."""
    if params and params.recompose:
        targets = _newest_assessed()
    else:
        _, targets = _pov_state()
    if not targets:
        raise HTTPException(status_code=409, detail="nothing to compose")
    job_id = pov_composer.start_compose_all(
        [{"scoring_run_id": t["scoring_run_id"], "tech_id": t["tech_id"]}
         for t in targets],
        recompose=bool(params and params.recompose))
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
    return pov


@router.post("/scoring/runs/{run_id}/pov/{tech_id}")
def create_pov(run_id: str, tech_id: str) -> dict:
    """Compose (or recompose) the PoV — one LLM call narrating the stored
    assessment; the scores themselves never move."""
    try:
        return compose_pov(run_id, tech_id)
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
