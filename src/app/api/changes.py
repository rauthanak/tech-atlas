"""The Changes tab: configuration edits that aren't in the seeding data, and
"Update seeding data" for the ones the user ticks (see services/db/seeding)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.lists import LISTS, MOVED_AS, repair
from app.services import tech_status
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


@router.get("/changes/count")
def count_changes() -> dict:
    """What the Setup badge shows, without the items (polled by every page)."""
    found = seeding.changes()
    return {"count": found["count"], "awaiting_review": found["awaiting_review"]}


def _known(params: UpdateSeedingData) -> None:
    unknown = sorted({i.collection for i in params.items} - set(seeding.ID_FIELDS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown list(s): {', '.join(unknown)}")


# what an edit through main.CONFIG_PATHS would have marked: putting it back marks the same
ANSWERS_FROM = {"settings", "fabrics", "measures", "scoring_config", *LISTS}


@router.post("/changes/revert")
def revert(params: UpdateSeedingData) -> dict:
    """Put back the default: the ticked items return to the seeding data."""
    _known(params)
    for i in params.items:  # a classification value added in the app is removed: repaired as Remove does
        if i.collection in MOVED_AS and not any(
                s.get(seeding.ID_FIELDS[i.collection]) == i.id for s in seeding.read_list(i.collection)):
            repair(i.collection, i.id)
    done = seeding.revert([i.model_dump() for i in params.items])
    if done["put_back"] and any(i.collection in ANSWERS_FROM for i in params.items):
        tech_status.touch_all()  # as the edit it undoes did
    if any(i.collection == "signals" for i in params.items):
        from app.services import briefing_days
        briefing_days.rerank()  # a kind's place in the Briefing's order may have changed back
    return done


@router.post("/changes/update-seeding-data")
def update_seeding_data(params: UpdateSeedingData) -> dict:
    _known(params)
    try:
        return seeding.update_seeding_data([i.model_dump() for i in params.items])
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"could not write {exc.filename or 'a seed file'}: {exc.strerror or exc}. "
                   "That file is unchanged and its edits stay listed.")
