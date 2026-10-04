"""The Changes tab: configuration edits that aren't in the seeding data, and
"Update seeding data" for the ones the user ticks (see services/db/seeding)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db import seeding

router = APIRouter()


class ChangeRef(BaseModel):
    collection: str
    id: str


class UpdateSeedingData(BaseModel):
    items: list[ChangeRef] = Field(min_length=1, max_length=1000)


@router.get("/changes")
def list_changes() -> dict:
    return seeding.changes()


@router.post("/changes/update-seeding-data")
def update_seeding_data(params: UpdateSeedingData) -> dict:
    unknown = sorted({i.collection for i in params.items} - set(seeding.ID_FIELDS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown list(s): {', '.join(unknown)}")
    try:
        return seeding.update_seeding_data([i.model_dump() for i in params.items])
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not write {exc.filename or 'a seed file'}: {exc.strerror or exc}. "
                   "That file is unchanged and its edits stay listed.")
