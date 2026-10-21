"""The signal list and what it found. Never-miss signals add emphasis to a
page's summary; Can ignore rules set qualifying pages aside (kept, with the
reason, and left out of technologies and scoring). Edits apply from the next
run; stored pages catch up through a re-check. The list's order is the order
the Briefing lists findings in; it isn't part of the signals hash, so
reordering marks no page as not yet checked."""

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from app.services import busy
from app.services.db.mongo import get_collection
from app.services.runs.store import COLLECTIONS
from app.services.signals import recheck, snapshot
from app.services.timezone import now_utc

router = APIRouter()

OLDER_AFTER_DAYS = 30  # a page published this long before it was collected is an older article


class SignalEdit(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    look_for: str = Field(min_length=1, max_length=2000)
    mode: Literal["never_miss", "can_ignore"]
    enabled: bool = True


class SignalOrder(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)  # every never-miss signal, in its new order


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "signal"


def _check_name(name: str, own_id: str | None = None) -> str:
    clean = " ".join(name.split())
    if clean.lower() == "other":
        raise HTTPException(status_code=422,
                            detail='"Other" is reserved for developments that match no row.')
    clash = get_collection("signals").find_one(
        {"name": {"$regex": f"^{re.escape(clean)}$", "$options": "i"}, "_id": {"$ne": own_id}},
        {"name": 1})
    if clash:
        raise HTTPException(status_code=409, detail=f"A signal named {clash['name']!r} already exists.")
    return clean


def _names() -> dict[str, str]:
    return {r["_id"]: r["name"] for r in get_collection("signals").find({}, {"name": 1})}


def _counts(run_id: str | None = None) -> dict[str, int]:
    """Hits per never-miss row and set-aside pages per Can ignore rule (stubs
    excluded, so each page counts once)."""
    match: dict = {"is_stub": False}
    if run_id:
        match["run_id"] = run_id
    docs = get_collection("documents")
    counts: dict[str, int] = {}
    for row in docs.aggregate([{"$match": {**match, "signals.0": {"$exists": True}}},
                               {"$unwind": "$signals"},
                               {"$group": {"_id": "$signals.signal_id", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    for row in docs.aggregate([{"$match": {**match, "ignored_by": {"$nin": [None]}}},
                               {"$group": {"_id": "$ignored_by", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = counts.get(row["_id"], 0) + row["n"]
    return counts


@router.get("/signals")
def list_signals() -> dict:
    rows = list(get_collection("signals").find().sort([("mode", -1), ("order", 1), ("name", 1)]))
    latest = get_collection("runs").find_one(COLLECTIONS, sort=[("run_start_date_time", -1)], projection={"_id": 1})
    total, last = _counts(), (_counts(latest["_id"]) if latest else {})
    current = snapshot.current_hash()
    return {"signals": [{**r, "hits_total": total.get(r["_id"], 0),
                         "hits_last_run": last.get(r["_id"], 0)} for r in rows],
            "current_hash": current,
            "stale_pages": recheck.stale_count(current),
            "recheck": recheck.latest_job()}


@router.post("/signals", status_code=201)
def add_signal(edit: SignalEdit) -> dict:
    name = _check_name(edit.name)
    signal_id = _slug(name)
    if signal_id == "other" or get_collection("signals").find_one({"_id": signal_id}, {"_id": 1}):
        raise HTTPException(status_code=409, detail=f"A signal with the id {signal_id!r} already exists; "
                                                    "choose a more distinct name.")
    last = get_collection("signals").find_one(sort=[("order", -1)], projection={"order": 1})
    doc = {"_id": signal_id, "signal_id": signal_id, "name": name,
           "look_for": edit.look_for.strip(), "mode": edit.mode, "enabled": edit.enabled,
           "order": ((last or {}).get("order") or 0) + 1, "updated_at": now_utc()}
    get_collection("signals").insert_one(doc)
    return doc


@router.put("/signals/order")  # before /signals/{signal_id}, which would take "order" as an id
def reorder_signals(params: SignalOrder) -> dict:
    """The never-miss signals in their new order. Only rows that move are
    stamped, so Changes lists just those."""
    coll = get_collection("signals")
    current = {r["_id"]: r.get("order") for r in coll.find({"mode": "never_miss"}, {"order": 1})}
    if len(params.ids) != len(set(params.ids)) or set(params.ids) != set(current):
        raise HTTPException(status_code=422,
                            detail="Send every never-miss signal exactly once, in the new order.")
    now = now_utc()
    for position, signal_id in enumerate(params.ids, start=1):
        if current[signal_id] != position:
            coll.update_one({"_id": signal_id}, {"$set": {"order": position, "updated_at": now}})
    return list_signals()


@router.put("/signals/{signal_id}")
def update_signal(signal_id: str, edit: SignalEdit) -> dict:
    name = _check_name(edit.name, own_id=signal_id)
    updated = get_collection("signals").find_one_and_update(
        {"_id": signal_id},
        {"$set": {"name": name, "look_for": edit.look_for.strip(), "mode": edit.mode,
                  "enabled": edit.enabled, "updated_at": now_utc()}},
        return_document=ReturnDocument.AFTER)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown signal {signal_id!r}")
    return updated


@router.delete("/signals/{signal_id}")
def delete_signal(signal_id: str) -> dict:
    """The row is removed; Changes lists it as deleted until the seeding data
    is updated. Past hits keep their stored name."""
    if get_collection("signals").delete_one({"_id": signal_id}).deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"unknown signal {signal_id!r}")
    return {"deleted": signal_id}


def scope(since: str | None = None, until: str | None = None, run_id: str | None = None,
          source_id: str | None = None) -> dict:
    """The pages a window or one collection covers, optionally from one source."""
    match: dict = {}
    if since or until:
        match["scraped_at"] = {**({"$gte": since} if since else {}), **({"$lt": until} if until else {})}
    if run_id:
        match["run_id"] = run_id
    if source_id:
        match["source_id"] = source_id
    return match


def about(tech: str) -> dict:
    """After $unwind, the hits about a technology whose pages already match it:
    by the hit's own technologies when it has them, otherwise by its page's."""
    return {"$or": [{"signals.technologies_resolved": tech},
                    {"signals.technologies_resolved": {"$exists": False}}]}


def order() -> list[str]:
    """The never-miss signals in the signal list's order: the order findings follow."""
    return [r["_id"] for r in get_collection("signals").find(
        {"mode": "never_miss", "enabled": True}, {"_id": 1}).sort([("order", 1), ("name", 1)])]


def _keys(listed: list[str]) -> dict:
    """Per hit: older (its page was published more than OLDER_AFTER_DAYS
    before it was collected; no publication date counts as recent), rank (its
    place in the signal list; a deleted or switched-off row after the listed
    ones, Other last) and date (published, else collected)."""
    collected_day = {"$substrBytes": ["$scraped_at", 0, 10]}
    published = {"$dateFromString": {"dateString": "$published_date", "onError": None, "onNull": None}}
    collected = {"$dateFromString": {"dateString": collected_day, "onError": None, "onNull": None}}
    place = {"$indexOfArray": [listed, "$signals.signal_id"]}
    return {
        "older": {"$gt": [{"$dateDiff": {"startDate": published, "endDate": collected, "unit": "day"}},
                          OLDER_AFTER_DAYS]},
        "rank": {"$cond": [{"$gte": [place, 0]}, place,
                           {"$cond": [{"$eq": ["$signals.signal_id", "other"]}, len(listed) + 1, len(listed)]}]},
        "date": {"$ifNull": ["$published_date", collected_day]},
    }


def _unwound(match: dict, tech: str | None) -> list[dict]:
    pipeline: list[dict] = [{"$match": {"is_stub": False, "signals.0": {"$exists": True}, **match,
                                        **({"technologies_resolved": tech} if tech else {})}},
                            {"$unwind": {"path": "$signals", "includeArrayIndex": "n"}}]
    if tech:
        pipeline.append({"$match": about(tech)})
    return pipeline


def hits(match: dict, signal_match: dict | None = None, limit: int = 50, skip: int = 0,
         sort: str = "collected", tech: str | None = None) -> tuple[list[dict], int]:
    """Findings, one per hit, and their total: the one shape the Briefing,
    the technology page and the side panel share. `n` is the hit's place on
    its page; `tech` keeps the hits about that technology.

    sort="collected": newest collected first.
    sort="briefing": recent before older, then the signal list's order, then
    newest published. Sorted before paging, so pages walk one order."""
    pipeline = _unwound(match, tech)
    if signal_match:
        pipeline.append({"$match": signal_match})
    pipeline.append({"$addFields": _keys(order())})
    by = {"scraped_at": -1, "_id": 1, "n": 1}
    if sort == "briefing":
        by = {"older": 1, "rank": 1, "date": -1, **by}
    pipeline.append({"$facet": {
        "total": [{"$count": "n"}],
        "page": [{"$sort": by}, {"$skip": skip}, {"$limit": limit},
                 {"$project": {"_id": 0, "doc_id": "$_id", "n": 1, "url": "$end_url", "title": 1,
                               "source_id": 1, "run_id": 1, "scraped_at": 1, "published_date": 1,
                               "older": 1,
                               "technologies": {"$ifNull": ["$signals.technologies_resolved",
                                                            {"$ifNull": ["$technologies_resolved", []]}]},
                               "hit": "$signals"}}],
    }})
    result = next(get_collection("documents").aggregate(pipeline))
    names = _names()
    # technologies are linked by id: a renamed technology keeps the id it was
    # created with, so its id can't be derived from its name
    tech_names = {t for row in result["page"] for t in row["technologies"]}
    known = {t["name"]: t for t in get_collection("technologies").find(
        {"name": {"$in": sorted(tech_names)}}, {"name": 1, "doc_count": 1})} if tech_names else {}
    items = []
    for row in result["page"]:
        hit = row.pop("hit")
        hit.pop("technologies", None)           # the raw names; row["technologies"] is resolved
        hit.pop("technologies_resolved", None)
        if hit.get("signal_id") in names:
            hit["name"] = names[hit["signal_id"]]
        # the filtered technology first, then the ones with the most pages
        row["technologies"] = sorted(row["technologies"], key=lambda t: (
            t != tech, -((known.get(t) or {}).get("doc_count") or 0), t))
        row["technology_ids"] = [(known.get(t) or {}).get("_id") for t in row["technologies"]]
        items.append({**row, **hit})
    return items, result["total"][0]["n"] if result["total"] else 0


def tally(match: dict, tech: str | None = None) -> dict:
    """The findings in a scope, how many are older, and the count per signal
    type in the Briefing's order: the signal list's rows, then deleted or
    switched-off rows, then Other."""
    listed = order()
    groups = list(get_collection("documents").aggregate([
        *_unwound(match, tech),
        {"$addFields": {"older": _keys(listed)["older"]}},
        {"$group": {"_id": "$signals.signal_id", "name": {"$first": "$signals.name"},
                    "count": {"$sum": 1}, "older": {"$sum": {"$cond": ["$older", 1, 0]}}}}]))
    names = _names()
    rank = {signal_id: i for i, signal_id in enumerate(listed)}

    def name(g: dict) -> str:
        return "Other" if g["_id"] == "other" else names.get(g["_id"]) or g["name"] or g["_id"]

    groups.sort(key=lambda g: (rank.get(g["_id"], len(listed) + (g["_id"] == "other")), name(g)))
    return {"findings": sum(g["count"] for g in groups), "older": sum(g["older"] for g in groups),
            "types": [{"signal_id": g["_id"], "name": name(g), "count": g["count"], "older": g["older"]}
                      for g in groups]}


@router.get("/signals/found")
def found(signal_id: str | None = None, tech: str | None = None, source_id: str | None = None,
          run_id: str | None = None, since: str | None = None, until: str | None = None,
          doc_id: str | None = None, sort: Literal["collected", "briefing"] = "collected",
          limit: int = Query(default=50, ge=1, le=100), skip: int = Query(default=0, ge=0)) -> dict:
    """Findings, one row per hit. `doc_id` gives one page's; `since`/`until`
    bound the collection time, so a loaded list pages through a fixed window;
    `sort=briefing` gives the Briefing's order."""
    match = scope(since, until, run_id, source_id)
    if doc_id:
        match["_id"] = doc_id
    items, total = hits(match, {"signals.signal_id": signal_id} if signal_id else None, limit, skip,
                        sort=sort, tech=tech.strip().lower() if tech else None)
    return {"hits": items, "total": total}


@router.get("/signals/other")
def other(since: str | None = None, tech: str | None = None, run_id: str | None = None,
          limit: int = Query(default=50, ge=1, le=200), skip: int = Query(default=0, ge=0)) -> dict:
    """Developments that match no row, grouped by their label (ignoring
    case) — candidates to promote to a row. `total` counts the groups."""
    match: dict = {"is_stub": False, "signals.signal_id": "other"}
    if since:
        match["scraped_at"] = {"$gte": since}
    if tech:
        match["technologies_resolved"] = tech.strip().lower()
    if run_id:
        match["run_id"] = run_id
    result = next(get_collection("documents").aggregate([
        {"$match": match},
        {"$unwind": "$signals"},
        {"$match": {"signals.signal_id": "other"}},
        {"$sort": {"scraped_at": -1}},
        {"$group": {"_id": {"$toLower": "$signals.label"},
                    "label": {"$first": "$signals.label"},
                    "count": {"$sum": 1},
                    "examples": {"$push": {"what": "$signals.what", "url": "$end_url",
                                           "doc_id": "$_id", "scraped_at": "$scraped_at"}}}},
        {"$facet": {
            "total": [{"$count": "n"}],
            "groups": [{"$sort": {"count": -1, "_id": 1}}, {"$skip": skip}, {"$limit": limit},
                       {"$project": {"_id": 0, "label": 1, "count": 1,
                                     "examples": {"$slice": ["$examples", 3]}}}],
        }},
    ]))
    return {"groups": result["groups"], "total": result["total"][0]["n"] if result["total"] else 0}


@router.get("/signals/set-aside")
def set_aside(run_id: str | None = None, since: str | None = None,
              limit: int = Query(default=50, ge=1, le=100),
              skip: int = Query(default=0, ge=0)) -> dict:
    """Pages a Can ignore rule set aside: kept, but not used for technologies
    or assessments."""
    query: dict = {"is_stub": False, "ignored_by": {"$nin": [None]}}
    if run_id:
        query["run_id"] = run_id
    if since:
        query["scraped_at"] = {"$gte": since}
    docs = get_collection("documents")
    names = _names()
    pages = []
    for d in (docs.find(query, {"end_url": 1, "title": 1, "source_id": 1, "ignored_by": 1,
                                "summary_text": 1, "scraped_at": 1, "run_id": 1})
              .sort("scraped_at", -1).skip(skip).limit(limit)):
        pages.append({"doc_id": d["_id"], "url": d.get("end_url"), "title": d.get("title"),
                      "source_id": d.get("source_id"), "run_id": d.get("run_id"),
                      "ignored_by": d["ignored_by"],
                      "rule_name": names.get(d["ignored_by"], d["ignored_by"]),
                      "summary_text": d.get("summary_text"), "scraped_at": d.get("scraped_at")})
    return {"pages": pages, "total": docs.count_documents(query)}


@router.post("/signals/recheck", status_code=202)
def start_recheck() -> dict:
    try:
        return recheck.start()
    except busy.Busy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
