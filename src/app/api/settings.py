"""Settings documents. One so far, `crawl`: the links the crawler never
follows, the page budget per source, the page-part size and parallelism for
long pages, and the first-run lookback for data sources. Read once per run
and recorded on it."""


from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from pymongo import ReturnDocument

from app.services import auth
from app.services.db.mongo import get_collection
from app.services.signals import snapshot
from app.services.timezone import now_utc

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
        {"$set": {**edit.model_dump(), "updated_at": now_utc(), "updated_by": auth.by()},
         "$setOnInsert": {"name": "crawl"}},
        upsert=True, return_document=ReturnDocument.AFTER)


class RadarSettingsEdit(BaseModel):
    wake_after_pages: int = Field(ge=1, le=1000)
    default_time_zone: str = Field(min_length=1, max_length=64)
    evidence_floor: int = Field(ge=1, le=100)
    classify_after_collection: bool
    classify_pages_cap: int = Field(ge=1, le=50)
    emerging_availability: list[str] = Field(max_length=20)
    find_evidence_results: int = Field(ge=1, le=10)
    find_evidence_daily_budget: int = Field(ge=0, le=500)

    @field_validator("default_time_zone")
    @classmethod
    def _zone(cls, tz: str) -> str:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(tz)
        except Exception:
            raise ValueError(f"{tz!r} isn't a time zone name, such as America/Chicago")
        return tz


@router.get("/settings/radar")
def get_radar_settings() -> dict:
    from app.services.settings_store import radar_settings
    return radar_settings()


RETIRED = {"classify_token_budget": ""}  # settings the radar no longer has: a save removes them


@router.put("/settings/radar")
def update_radar_settings(edit: RadarSettingsEdit) -> dict:
    return get_collection("settings").find_one_and_update(
        {"_id": "radar"},
        {"$set": {**edit.model_dump(), "updated_at": now_utc(), "updated_by": auth.by()}, "$unset": RETIRED,
         "$setOnInsert": {"name": "radar"}},
        upsert=True, return_document=ReturnDocument.AFTER)
