"""Link known names (agent/tagger): the latest run, and the catch-up over every
stored page, started by a person. A collection runs it by itself on its own
pages."""

from fastapi import APIRouter, HTTPException

from agent import tagger
from agent.tagger.tagger import NAMES_BATCH, known, view
from app.services.db.mongo import get_collection

router = APIRouter()


@router.get("/tagging")
def latest() -> dict:
    """The latest run, and what a catch-up started now would look for: the
    known technologies, and how many still need their names (one call per
    batch); checking costs one call per 10 pages found, counted as it goes."""
    techs = known()
    waiting = sum(1 for t in techs if not t.get("look_for"))
    return {"latest": view(get_collection("tag_runs").find_one(sort=[("started_at", -1)])),
            "technologies": len(techs), "without_names": waiting, "naming_calls": -(-waiting // NAMES_BATCH)}


@router.post("/tagging", status_code=202)
def catch_up() -> dict:
    run_id = tagger.start()
    if run_id is None:
        raise HTTPException(status_code=409, detail="Known names are being linked now; it can start when that finishes.")
    return {"id": run_id}
