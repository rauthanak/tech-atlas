"""Publishing editions for Frontier (services/editions): the editions so far,
newest first, and Publish, which freezes what leaders see. For Tech Lens
only: the executive address never reaches these (proxy.ts)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services import editions
from app.services.timezone import request_tz

router = APIRouter()


class PublishIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)  # e.g. "FY27 Q3"; else it's named by its date


@router.get("/editions")
def list_editions() -> dict:
    return {"editions": editions.listed()}


@router.get("/editions/since")
def since_latest() -> dict:
    """What has changed since the latest edition, for the Briefing's publish line."""
    return {"since": editions.since()}


@router.get("/editions/pov/{tech_id}")
def pov_in_latest(tech_id: str) -> dict:
    """Which version of this Point of View leaders see, for its page."""
    return editions.pov_in_latest(tech_id)


@router.post("/editions", status_code=201)
def publish(body: PublishIn | None = None, tz: str = Depends(request_tz)) -> dict:
    try:
        return {"edition": editions.publish(body.name if body else None, tz)}
    except editions.Refused as exc:
        raise HTTPException(status_code=409, detail=str(exc))
