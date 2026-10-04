"""Technology endpoints (Phase B). The register is built by the resolver;
admin edits here (rename, alias moves, enable/disable) restamp documents
deterministically — no LLM involved — so corrections are cheap and safe."""

from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.analyzer.estimate import estimate
from agent.resolver import restamp_all, start_resolve
from app.services import evidence
from app.services.db.mongo import get_collection

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


STATES = Literal["new_evidence", "no_pov", "not_assessed", "stopped_partway", "assessing", "current", "off"]


def _over_floor(ids: list[str], found: dict[str, dict]) -> dict | None:
    """Technologies never assessed that now have as many pages as the latest
    assessment by page count asked for: they got there after it ran, so no
    run included them. The Not assessed filter offers them, with the cost."""
    run = get_collection("scoring_runs").find_one({"params.min_docs": {"$gte": 1}},
                                                  {"params": 1, "started_at": 1}, sort=[("started_at", -1)])
    if run is None:
        return None
    floor = run["params"]["min_docs"]
    over = [i for i in ids if found[i]["state"] == "not_assessed" and found[i]["new_pages"] >= floor]
    return {"min_pages": floor, "started_at": run["started_at"], "tech_ids": over,
            **estimate(over)} if over else None


@router.get("/technologies")
def list_technologies(q: str = "", state: STATES | None = None, limit: int = 100, skip: int = 0) -> dict:
    """The register, most pages first, each row with its state (services/
    evidence), new pages, assessment date and newest Point of View. `state`
    filters before paging; `state_counts` and `over_floor` cover the search's
    matches."""
    import re as _re
    coll = get_collection("technologies")
    query: dict = {}
    if q.strip():
        rx = _re.compile(_re.escape(q.strip().lower()))
        query = {"$or": [{"name": rx}, {"aliases": rx}, {"label": _re.compile(_re.escape(q.strip()), _re.I)}]}
    ids = [t["_id"] for t in coll.find(query, {"_id": 1}).sort([("doc_count", -1), ("_id", 1)])]
    found = evidence.list_states(ids)
    state_counts = Counter(s["state"] for s in found.values())
    over_floor = _over_floor(ids, found)
    if state:
        ids = [i for i in ids if found[i]["state"] == state]
    start = max(0, skip)
    page = ids[start:start + max(1, min(limit, 500))]
    rows = {t["_id"]: t for t in coll.find({"_id": {"$in": page}})}
    povs = {p["_id"]: {"scoring_run_id": p["scoring_run_id"], "composed_at": p["composed_at"]}
            for p in get_collection("povs").aggregate([
                {"$match": {"tech_id": {"$in": page}}}, {"$sort": {"composed_at": -1}},
                {"$group": {"_id": "$tech_id", "scoring_run_id": {"$first": "$scoring_run_id"},
                            "composed_at": {"$first": "$composed_at"}}}])}
    techs = [{**rows[i], **found[i], "pov": povs.get(i)} for i in page if i in rows]
    total = len(ids)
    docs = get_collection("documents")
    tagged = docs.count_documents({"technologies_resolved": {"$exists": True, "$ne": []}})
    kinds: dict[str, int] = {}
    horizons: dict[str, int] = {}
    for row in docs.aggregate([
        {"$match": {"technologies_resolved": {"$exists": True, "$ne": []}}},
        {"$group": {"_id": {"kind": "$kind", "category": "$category"}, "n": {"$sum": 1}}},
    ]):
        kinds[row["_id"].get("kind") or "article"] = kinds.get(row["_id"].get("kind") or "article", 0) + row["n"]
        horizons[row["_id"].get("category") or "?"] = horizons.get(row["_id"].get("category") or "?", 0) + row["n"]
    last = get_collection("resolves").find_one(sort=[("started_at", -1)])
    return {
        "technologies": techs,
        "total": total,
        "state_counts": dict(state_counts),
        "over_floor": over_floor,
        "summary": {"tech_count": coll.estimated_document_count(),
                    "tagged_docs": tagged,
                    "kinds": kinds, "horizons": horizons},
        "last_resolve": last,
    }


class ResolveParams(BaseModel):
    replace: bool = False


@router.post("/technologies/resolve", status_code=202)
def trigger_resolve(params: ResolveParams | None = None) -> dict:
    try:
        resolve_id = start_resolve(replace=bool(params and params.replace))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"resolve_id": resolve_id}


@router.get("/technologies/resolves")
def list_resolves() -> dict:
    return {"resolves": list(
        get_collection("resolves").find().sort("started_at", -1).limit(20))}


@router.get("/technologies/labels")  # before /technologies/{tech_id}
def technology_labels() -> dict:
    """Display names, {name: label}, for technologies that have one
    ("ml-kem" → "ML-KEM"). The portal shows a label wherever it shows a name."""
    return {t["name"]: t["label"] for t in get_collection("technologies").find(
        {"label": {"$nin": [None, ""]}}, {"name": 1, "label": 1})}


@router.get("/technologies/{tech_id}")
def get_technology(tech_id: str) -> dict:
    t = get_collection("technologies").find_one({"_id": tech_id})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    return t


@router.get("/technologies/{tech_id}/summary")
def technology_summary(tech_id: str) -> dict:
    """The technology page in one call: the technology and its one state
    (services/evidence), its latest assessment, any newer run still going or
    stopped partway, its newest Point of View, its new pages, and about how
    many model calls the next step takes."""
    t = get_collection("technologies").find_one({"_id": tech_id})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    s = evidence.state(tech_id)
    a = s["assessment"]
    pov = get_collection("povs").find_one(
        {"tech_id": tech_id}, {"sections.headline": 1, "scoring_run_id": 1, "composed_at": 1,
                               "version": 1, "assessment_ids": 1}, sort=[("composed_at", -1)])
    since_pov = None
    if pov:
        read = evidence.reading(list(get_collection("assessments").find(
            {"_id": {"$in": pov.get("assessment_ids") or []}}, {"measures": 0, "watch_metrics": 0})))
        since_pov = len(evidence.new_pages(t["name"], read)) if read else None
    cost = estimate([tech_id])
    return {
        "technology": {"id": t["_id"], "name": t["name"], "aliases": t.get("aliases", []),
                       "enabled": t.get("enabled", True), "page_count": t.get("page_count", 0),
                       "source_count": t.get("source_count", 0)},
        "state": s["state"],
        "assessment": {k: a[k] for k in ("scoring_run_id", "run_status", "assessed_at", "pages_read",
                                         "evidence_runs", "fabrics", "not_assessed_in")} if a else None,
        "unfinished": s["unfinished"],
        "pov": {"id": pov["_id"], "scoring_run_id": pov["scoring_run_id"],
                "composed_at": pov["composed_at"], "version": pov.get("version"),
                "headline": (pov.get("sections") or {}).get("headline"),
                "from_latest_assessment": bool(a) and pov["scoring_run_id"] == a["scoring_run_id"]}
        if pov else None,
        "new_pages": {"since_assessment": len(s["new"]), "since_pov": since_pov,
                      "recent": [evidence.page(d) for d in s["new"][:5]]},
        "estimate": {"assess_calls": cost["calls"], "assess_calls_max": cost["calls_max"],
                     "write_calls": 1},
    }


@router.get("/technologies/{tech_id}/documents")
def technology_documents(tech_id: str, limit: int = 50, skip: int = 0,
                         sort: str = "scraped") -> dict:
    t = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    match = {"technologies_resolved": t["name"]}
    docs_coll = get_collection("documents")
    total = docs_coll.count_documents(match)
    # sort=published: newest published first; docs without a published date
    # sort below any dated ones (missing < value in Mongo), then by extraction
    order = [("published_date", -1), ("scraped_at", -1)] if sort == "published" \
        else [("scraped_at", -1)]
    docs = list(docs_coll.find(match, {"extracted_text": 0})
                .sort(order)
                .skip(max(0, skip)).limit(max(1, min(limit, 500))))
    new_versions = {evidence.version(d) for d in evidence.state(tech_id)["new"]}
    for d in docs:
        d["new"] = evidence.version(d) in new_versions  # not read by the latest assessment
        d["id"] = str(d.pop("_id"))
    return {"name": t["name"], "documents": docs, "total": total}


class TechEdit(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool


@router.put("/technologies/{tech_id}")
def update_technology(tech_id: str, edit: TechEdit) -> dict:
    techs = get_collection("technologies")
    name = edit.name.strip().lower()
    clash = techs.find_one({"name": name, "_id": {"$ne": tech_id}}, {"_id": 1})
    if clash:
        raise HTTPException(status_code=422,
                            detail=f"another technology already uses the name {name!r}"
                                   " — move its aliases instead")
    current = techs.find_one({"_id": tech_id}, {"name": 1})
    if current is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    update: dict = {"$set": {"name": name, "enabled": edit.enabled, "updated_at": _now()},
                    "$addToSet": {"aliases": name}}
    typed = edit.name.strip()
    if typed != name:                 # typed with capitals: that's how it's shown
        update["$set"]["label"] = typed
    elif name != current["name"]:     # renamed in lowercase: the next organize labels it
        update["$unset"] = {"label": ""}
    techs.update_one({"_id": tech_id}, update)
    restamp_all()
    return get_collection("technologies").find_one({"_id": tech_id})


class MergeParams(BaseModel):
    others: list[str] = Field(min_length=1, max_length=50)


@router.post("/technologies/{tech_id}/merge")
def merge_technologies(tech_id: str, params: MergeParams) -> dict:
    """Merge whole technologies into this one — the user's judgment overriding
    the LLM's. Each entry in `others` is a tech id or exact name. The target's
    name survives; every alias of the absorbed technologies moves over, the
    absorbed entries are deleted, and all documents restamp."""
    techs = get_collection("technologies")
    target = techs.find_one({"_id": tech_id})
    if target is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    absorbed: list[dict] = []
    for ref in params.others:
        ref = ref.strip()
        other = techs.find_one({"$or": [{"_id": ref}, {"name": ref.lower()}]})
        if other is None:
            raise HTTPException(status_code=404, detail=f"unknown technology {ref!r}")
        if other["_id"] == tech_id:
            raise HTTPException(status_code=422, detail="cannot merge a technology into itself")
        absorbed.append(other)
    aliases = sorted({a for o in absorbed for a in o.get("aliases", [])}
                     | {o["name"] for o in absorbed})
    techs.update_one({"_id": tech_id},
                     {"$addToSet": {"aliases": {"$each": aliases}},
                      "$set": {"updated_at": _now()}})
    techs.delete_many({"_id": {"$in": [o["_id"] for o in absorbed]}})
    restamp_all()
    return get_collection("technologies").find_one({"_id": tech_id})


class AliasMove(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


@router.post("/technologies/{tech_id}/claim_alias")
def claim_alias(tech_id: str, move: AliasMove) -> dict:
    """Move a raw alias string to this technology (from wherever it lives).
    The fix for a bad merge: claim the stray alias, documents restamp."""
    techs = get_collection("technologies")
    target = techs.find_one({"_id": tech_id}, {"_id": 1})
    if target is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    techs.update_many({"_id": {"$ne": tech_id}}, {"$pull": {"aliases": move.alias}})
    techs.update_one({"_id": tech_id},
                     {"$addToSet": {"aliases": move.alias},
                      "$set": {"updated_at": _now()}})
    restamp_all()
    return get_collection("technologies").find_one({"_id": tech_id})
