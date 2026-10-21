"""The Briefing: what a window of collecting (or one collection) found, in
one call for the portal's home page — the scope, its counts and the signal
types found, in the Briefing's order. The findings themselves come from
/signals/found?sort=briefing with the same scope, so counts and list agree."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.api.signals import scope as page_scope
from app.api.signals import tally
from app.services.db.mongo import get_collection
from app.services.runs.store import COLLECTIONS

router = APIRouter()


def _freshness() -> dict | None:
    """The latest finished collection (a Find evidence run stores its pages
    under a run too, but it isn't a collection)."""
    run = get_collection("runs").find_one(
        {"run_end_date_time": {"$ne": None}, **COLLECTIONS},
        sort=[("run_start_date_time", -1)],
        projection={"totals": 1, "run_end_date_time": 1})
    if run is None:
        return None
    totals = run.get("totals") or {}
    return {"run_id": run["_id"], "finished_at": run["run_end_date_time"],
            "sources": totals.get("sources", 0), "new_pages": totals.get("new_documents", 0)}


@router.get("/briefing")
def briefing(days: str | None = None, run_id: str | None = None, tech: str | None = None,
             source_id: str | None = None) -> dict:
    """`days` (a number, or "all") or `run_id` (one collection, by membership);
    `tech` and `source_id` narrow both, as they narrow the list."""
    if days is not None and run_id:
        raise HTTPException(status_code=422,
                            detail="Choose a window (days) or one collection (run_id), not both.")
    if run_id:
        run = get_collection("runs").find_one(
            {"_id": run_id}, {"run_start_date_time": 1, "run_end_date_time": 1, "status": 1, "error": 1})
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown collection {run_id!r}")
        window = {"run_id": run_id, "started_at": run.get("run_start_date_time"),
                  "finished_at": run.get("run_end_date_time"), "status": run.get("status"),
                  "error": run.get("error")}
        match = page_scope(run_id=run_id, source_id=source_id)
    else:
        days = days or "7"
        if days != "all" and not (days.isdigit() and 1 <= int(days) <= 365):
            raise HTTPException(status_code=422, detail='days is a number of days (1–365) or "all".')
        now = datetime.now(timezone.utc)
        since = None if days == "all" else (now - timedelta(days=int(days))).isoformat()
        window = {"days": days, "from": since, "to": now.isoformat()}
        match = page_scope(since, now.isoformat(), source_id=source_id)
    name = tech.strip().lower() if tech else None
    pages = get_collection("documents").count_documents(
        {"is_stub": False, **match, **({"technologies_resolved": name} if name else {})})
    found = tally(match, name)
    return {"scope": window,
            "counts": {"findings": found["findings"], "pages": pages, "older": found["older"]},
            "types": found["types"],
            "freshness": _freshness()}
