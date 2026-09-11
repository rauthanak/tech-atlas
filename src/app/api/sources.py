"""Source register: the list the portal renders, one document by id, and
edits to it. `source_id`/`_id` are immutable."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from app.horizons import HORIZONS
from app.services.db.mongo import get_collection

router = APIRouter()


class SourceEdit(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(pattern=r"^https?://")
    horizon: Literal["H1", "H2", "H3"]
    cluster: str = Field(min_length=1, max_length=100)
    cost: Literal["free", "free_tier", "licensed"]
    enabled: bool


@router.get("/sources")
def list_sources() -> dict:
    docs = list(get_collection("sources").find().sort([("horizon", 1), ("cluster", 1), ("name", 1)]))
    return {"horizons": HORIZONS, "sources": docs}


@router.get("/sources/{source_id}")
def get_source(source_id: str) -> dict:
    doc = get_collection("sources").find_one({"_id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {source_id!r}")
    return doc


@router.put("/sources/{source_id}")
def update_source(source_id: str, edit: SourceEdit) -> dict:
    updated = get_collection("sources").find_one_and_update(
        {"_id": source_id},
        {"$set": {**edit.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Unknown source {source_id!r}")
    return updated
