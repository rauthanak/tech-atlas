"""Settings documents. One so far, `crawl`: the links the crawler never
follows, the page budget per source, the page-part size and parallelism for
long pages, and the first-run lookback for data sources. Read once per run
and recorded on it."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from app.services.db.mongo import get_collection
from app.services.signals import snapshot

router = APIRouter()


class CrawlSettingsEdit(BaseModel):
    skip_url_patterns: list[str] = Field(max_length=500)
    pages_per_source: int = Field(ge=1, le=500)
    page_part_chars: int = Field(ge=20000)
    page_part_concurrency: int = Field(ge=1, le=16)
    lookback_days: int = Field(ge=1, le=365)

    @field_validator("skip_url_patterns")
    @classmethod
    def _non_empty(cls, patterns: list[str]) -> list[str]:
        cleaned = [p.strip() for p in patterns]
        if any(not p for p in cleaned):
            raise ValueError("each pattern must be a non-empty string")
        return cleaned


@router.get("/settings/crawl")
def get_crawl_settings() -> dict:
    return snapshot.crawl_settings()


@router.put("/settings/crawl")
def update_crawl_settings(edit: CrawlSettingsEdit) -> dict:
    return get_collection("settings").find_one_and_update(
        {"_id": "crawl"},
        {"$set": {**edit.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()},
         "$setOnInsert": {"name": "crawl"}},
        upsert=True, return_document=ReturnDocument.AFTER)
