"""Technology endpoints (Phase B). The register is built by the resolver;
admin edits here (rename, alias moves, enable/disable) restamp documents
deterministically — no LLM involved — so corrections are cheap and safe."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.resolver import restamp_all, start_resolve
from app.services.db.mongo import get_collection

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/technologies")
def list_technologies(q: str = "", limit: int = 100, skip: int = 0) -> dict:
    import re as _re
    coll = get_collection("technologies")
    query: dict = {}
    if q.strip():
        rx = _re.compile(_re.escape(q.strip().lower()))
        query = {"$or": [{"name": rx}, {"aliases": rx}]}
    total = coll.count_documents(query)
    techs = list(coll.find(query).sort("doc_count", -1)
                 .skip(max(0, skip)).limit(max(1, min(limit, 500))))
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


@router.get("/technologies/{tech_id}")
def get_technology(tech_id: str) -> dict:
    t = get_collection("technologies").find_one({"_id": tech_id})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    return t


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
    for d in docs:
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
    updated = techs.find_one_and_update(
        {"_id": tech_id},
        {"$set": {"name": name, "enabled": edit.enabled, "updated_at": _now()},
         "$addToSet": {"aliases": name}},
        return_document=True)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
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
