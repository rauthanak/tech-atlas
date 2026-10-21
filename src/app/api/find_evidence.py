"""Find evidence (agent/find_evidence): its cost first, start it, and how it
went. Only a person starts it; searches have a daily budget (radar settings),
counted in the default time zone. Add a link needs no search, so no budget."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.find_evidence import job as finder
from app.services import websearch
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import request_tz

router = APIRouter()


class Gap(BaseModel):
    kind: Literal["technology", "measure", "use_case", "link"]
    tech_id: str = Field(min_length=1)
    fabric_id: str | None = None
    measure_id: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    target: Literal["technology", "measure", "use_case"] | None = None  # what a pasted link re-runs


class Start(BaseModel):
    gap: Gap


def searches_today() -> tuple[int, int]:
    """(searches started today, the daily budget), today in the default zone."""
    settings = radar_settings()
    zone = ZoneInfo(settings["default_time_zone"])
    today = datetime.now(zone).date()
    used = sum(1 for j in get_collection("find_evidence_jobs").find({"searched": True}, {"at": 1})
               if datetime.fromisoformat(j["at"]).astimezone(zone).date() == today)
    return used, int(settings["find_evidence_daily_budget"])


def _why_not(used: int, limit: int) -> HTTPException | None:
    """Why a search can't start now, as the refusal starting one gets; None when it can."""
    if not websearch.configured():
        return HTTPException(status_code=409, detail="Find evidence needs a web search key (the server's .env). "
                                                     "Add a link still works.")
    if used >= limit:
        return HTTPException(status_code=429, detail=f"Today's {limit} searches are used up (counted in "
                             f"{radar_settings()['default_time_zone']}); more tomorrow. Add a link still works.")
    return None


@router.get("/find-evidence/preview")
def preview(kind: str, tech_id: str, fabric_id: str | None = None, measure_id: str | None = None) -> dict:
    used, limit = searches_today()
    gap = {"kind": kind, "tech_id": tech_id, "fabric_id": fabric_id, "measure_id": measure_id}
    why = _why_not(used, limit)
    return {"configured": websearch.configured(), "provider": websearch.provider(),
            "query": finder.query_for(gap) if kind != "link" else None,
            "searches": 1, "page_reads": int(radar_settings()["find_evidence_results"]), "reruns": 1,
            "budget": {"used": used, "limit": limit}, "why_not": why.detail if why else None}


@router.post("/find-evidence", status_code=202)
def start(body: Start, tz: str = Depends(request_tz)) -> dict:
    gap = body.gap.model_dump()
    if not get_collection("technologies").find_one({"_id": gap["tech_id"]}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"unknown technology {gap['tech_id']!r}")
    if gap["kind"] == "link":
        if not (gap.get("url") or "").startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="paste the page's full address, starting with http:// or https://")
    elif why := _why_not(*searches_today()):
        raise why
    if gap["kind"] == "measure" and not gap.get("measure_id"):
        raise HTTPException(status_code=422, detail="say which measure")
    return {"job_id": finder.start(gap, tz)}


@router.get("/find-evidence/{job_id}")
def get_job(job_id: str) -> dict:
    j = get_collection("find_evidence_jobs").find_one({"_id": job_id})
    if j is None:
        raise HTTPException(status_code=404, detail="no such Find evidence job")
    return finder.view(j)


@router.get("/find-evidence")
def list_jobs(tech_id: str, limit: int = 10) -> dict:
    """The technology's jobs, newest first, each as it reads now: what was
    filed, set aside (by which rule) and not read (why)."""
    name = finder.name_of(tech_id)
    return {"jobs": [finder.view(j, name) for j in get_collection("find_evidence_jobs").find({"gap.tech_id": tech_id})
                     .sort("at", -1).limit(max(1, min(limit, 50)))]}
