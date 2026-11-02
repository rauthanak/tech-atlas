"""Source register: the list the portal renders, one document by id, edits
to it, and sources an admin adds. `source_id`/`_id` are immutable, and so are
`access` and `adapter` — how a source is read is part of the register, not an
edit. An added source is live at once and listed on Setup › Changes as added,
where Keep as defaults writes it into the seeding data.

access: crawl (a website; optional start pages and one-hop outbound links),
query (a data source; saved searches answered by its adapter) or none (never
collected — terms forbid it or there is no usable access; cannot be enabled).
`note` says why a source is off or never collected, shown on its row.
`progress` (per saved search) is the app's own note, written by runs."""

import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from agent.scout.tools import adapters
from app.horizons import HORIZONS
from app.services import auth
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc
from app.settings import get_settings

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
    note: str | None = Field(default=None, max_length=500)               # why it's off, in plain words
    pages: int | None = Field(default=None, ge=0, le=500)                # its own page budget; 0: the default

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


class SourceNew(SourceEdit):
    access: Literal["crawl", "query"]
    adapter: str | None = None  # a data source's connector


def _refusal(access: str, edit: SourceEdit, note: str | None = None) -> str | None:
    """Why this source can't be saved as sent, in plain words (None: it can)."""
    if access == "none" and edit.enabled:
        return "This source is never collected" + (f": {note}" if note else ".")
    if access != "query" and edit.searches:
        return "Saved searches are for data sources only."
    if access != "crawl" and (edit.entry_urls or edit.follow_outbound):
        return "Start pages and outbound links are for website sources only."
    if edit.cost == "licensed" and edit.enabled and not get_settings().include_paid_sources:
        return "A licensed source stays off until paid sources are allowed (INCLUDE_PAID_SOURCES in .env)."
    return None


def _fields(edit: SourceEdit) -> tuple[dict, dict]:
    """(what to set, what to remove): an empty list or an off switch is stored
    as absent, as the seeding data writes it — so saving a form never shows up
    as a change by itself."""
    changes = {k: v for k, v in edit.model_dump().items() if v is not None}
    cleared = {k: "" for k in ("entry_urls", "follow_outbound", "searches", "note", "pages") if k in changes and not changes[k]}
    for k in cleared:
        changes.pop(k)
    return changes | {"updated_at": now_utc(), "updated_by": auth.by()}, cleared


@router.post("/sources", status_code=201)
def add_source(new: SourceNew) -> dict:
    source_id = re.sub(r"[^a-z0-9]+", "_", new.name.lower()).strip("_")[:60]
    if not source_id:
        raise HTTPException(status_code=422, detail="Give the source a name with letters or digits.")
    if source_id == "new" or get_collection("sources").find_one({"_id": source_id}, {"_id": 1}):  # "new" is the Add page
        raise HTTPException(status_code=409, detail=f"A source with the id {source_id} exists: give it another name.")
    if new.access == "query" and new.adapter not in adapters.REGISTRY:
        raise HTTPException(status_code=422, detail="Choose a data source's connector: "
                            + ", ".join(sorted(adapters.REGISTRY)) + ".")
    if new.access == "crawl" and new.adapter:
        raise HTTPException(status_code=422, detail="A website has no connector.")
    if why := _refusal(new.access, new):
        raise HTTPException(status_code=422, detail=why)
    doc = {"_id": source_id, "source_id": source_id, **_fields(new)[0]}
    get_collection("sources").insert_one(doc)
    return doc


@router.put("/sources/{source_id}")
def update_source(source_id: str, edit: SourceEdit) -> dict:
    current = get_collection("sources").find_one({"_id": source_id})
    if current is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {source_id!r}")
    if why := _refusal(current.get("access", "crawl"), edit, current.get("note")):
        raise HTTPException(status_code=422, detail=why)
    changes, cleared = _fields(edit)
    if edit.searches is not None:  # removing a saved search also removes its progress
        changes["progress"] = [p for p in current.get("progress") or []
                               if p.get("search") in edit.searches]
    update: dict = {"$set": changes}
    if cleared:
        update["$unset"] = cleared
    return get_collection("sources").find_one_and_update(
        {"_id": source_id}, update, return_document=ReturnDocument.AFTER)
