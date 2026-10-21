"""Source register: the list the portal renders, one document by id, and
edits to it. `source_id`/`_id` are immutable, and so are `access` and
`adapter` — how a source is read is part of the register, not an edit.

access: crawl (a website; optional start pages and one-hop outbound links),
query (a data source; saved searches answered by its adapter) or none (never
collected — terms forbid it or there is no usable access; cannot be enabled).
`progress` (per saved search) is the app's own note, written by runs."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from agent.scout.tools import adapters
from app.horizons import HORIZONS
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

router = APIRouter()


class SourceEdit(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(pattern=r"^https?://")
    horizon: Literal["H1", "H2", "H3"]
    cluster: str = Field(min_length=1, max_length=100)
    cost: Literal["free", "free_tier", "licensed"]
    enabled: bool
    entry_urls: list[str] | None = Field(default=None, max_length=50)    # websites
    follow_outbound: bool | None = None                                  # websites
    searches: list[str] | None = Field(default=None, max_length=100)     # data sources

    @field_validator("entry_urls")
    @classmethod
    def _urls(cls, urls: list[str] | None) -> list[str] | None:
        if urls is None:
            return None
        cleaned = list(dict.fromkeys(u.strip() for u in urls if u.strip()))
        bad = [u for u in cleaned if not u.startswith(("http://", "https://"))]
        if bad:
            raise ValueError(f"start pages must be web addresses (http/https): {', '.join(bad[:3])}")
        return cleaned

    @field_validator("searches")
    @classmethod
    def _searches(cls, searches: list[str] | None) -> list[str] | None:
        if searches is None:
            return None
        return list(dict.fromkeys(s.strip() for s in searches if s.strip()))


@router.get("/sources")
def list_sources() -> dict:
    docs = list(get_collection("sources").find().sort([("horizon", 1), ("cluster", 1), ("name", 1)]))
    return {"horizons": HORIZONS, "sources": docs}


@router.get("/sources/adapters")
def list_adapters() -> list[dict]:
    """Search help per data-source adapter, and whether its keys are set."""
    return adapters.describe()


@router.get("/sources/{source_id}")
def get_source(source_id: str) -> dict:
    doc = get_collection("sources").find_one({"_id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {source_id!r}")
    return doc


@router.put("/sources/{source_id}")
def update_source(source_id: str, edit: SourceEdit) -> dict:
    current = get_collection("sources").find_one({"_id": source_id})
    if current is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {source_id!r}")
    access = current.get("access", "crawl")
    if access == "none" and edit.enabled:
        raise HTTPException(status_code=422, detail="This source is never collected"
                            + (f": {current['note']}" if current.get("note") else "."))
    if access != "query" and edit.searches:
        raise HTTPException(status_code=422, detail="Saved searches are for data sources only.")
    if access != "crawl" and (edit.entry_urls or edit.follow_outbound):
        raise HTTPException(status_code=422,
                            detail="Start pages and outbound links are for website sources only.")

    changes = {k: v for k, v in edit.model_dump().items() if v is not None}
    # an empty list or an off switch is stored as absent, as the seeding data
    # writes it — so saving a form never shows up as a change by itself
    cleared = {k: "" for k in ("entry_urls", "follow_outbound", "searches")
               if k in changes and not changes[k]}
    for k in cleared:
        changes.pop(k)
    if edit.searches is not None:  # removing a saved search also removes its progress
        changes["progress"] = [p for p in current.get("progress") or []
                               if p.get("search") in edit.searches]
    changes["updated_at"] = now_utc()
    update: dict = {"$set": changes}
    if cleared:
        update["$unset"] = cleared
    return get_collection("sources").find_one_and_update(
        {"_id": source_id}, update, return_document=ReturnDocument.AFTER)
