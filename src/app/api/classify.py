"""Classify (agent/classifier): its cost first, start it, and its runs."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.classifier import classify
from agent.classifier.evidence import pack
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import request_tz

router = APIRouter()
CHARS_PER_TOKEN = 4


class ClassifyParams(BaseModel):
    tech_ids: list[str] | None = Field(default=None, min_length=1, max_length=5000)
    all_pending: bool = False


def _targets(tech_ids: list[str] | None, all_pending: bool) -> list[str]:
    if tech_ids:
        return [t["_id"] for t in get_collection("technologies").find(
            {"_id": {"$in": tech_ids}, "enabled": {"$ne": False}}, {"_id": 1})]
    return classify.pending() if all_pending else []


@router.get("/classify/preview")
def preview(ids: str | None = None, pending: bool = False) -> dict:
    """How many technologies, about how many calls and tokens. The tasks and
    lists are sent once and reused; each technology adds its own pages."""
    targets = _targets([i for i in (ids or "").split(",") if i] or None, pending)
    cap = int(radar_settings()["classify_pages_cap"])
    names = [t["name"] for t in get_collection("technologies").find({"_id": {"$in": targets[:40]}}, {"name": 1})]
    sample = [len(pack(n, cap)["text"]) // CHARS_PER_TOKEN + 600 for n in names] or [1500]
    per = sum(sample) // len(sample)
    return {"technologies": len(targets), "calls": len(targets), "tokens_about": per * len(targets),
            "running": classify.active_run() is not None}


@router.post("/classify", status_code=202)
def start(params: ClassifyParams, tz: str = Depends(request_tz)) -> dict:
    targets = _targets(params.tech_ids, params.all_pending)
    if not targets:
        raise HTTPException(status_code=409, detail="nothing to classify: no switched-on technology here has new pages")
    run_id = classify.start(targets, trigger="on demand", tz=tz)
    if run_id is None:
        raise HTTPException(status_code=409, detail="a classification run is already going; this one can start when it ends")
    return {"run_id": run_id, "technologies": len(targets)}


@router.get("/classify/runs")
def runs(limit: int = 20) -> dict:
    return {"runs": list(get_collection("classify_runs").find({}, {"tech_ids": 0})
                         .sort("started_at", -1).limit(max(1, min(limit, 100))))}


@router.post("/classify/runs/{run_id}/terminate")
def terminate(run_id: str) -> dict:
    done = get_collection("classify_runs").update_one({"_id": run_id, "status": "running"},
                                                      {"$set": {"status": "terminating"}}).modified_count
    if not done:
        raise HTTPException(status_code=409, detail="that classification run isn't running")
    return {"status": "terminating"}
