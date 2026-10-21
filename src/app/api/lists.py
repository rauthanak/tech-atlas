"""The seeded lists people edit in Setup: commercial availability, domains
and sub-domains, TRL levels, path-to-scale steps, value mechanisms and the
assumptions in force (shown on Frontier, each dated). Every write stamps
`updated_at` (so Changes lists it) and counts a version.

What an edit does to classified technologies (Classify reads these lists):
  add                applies from the next classification
  rename             applies at once, no model call
  definition change  marks the technologies classified under the old wording
                     for review: the next Classify run (or Re-classify) redoes them
  remove             moves its technologies to the catch-all, marked for review
"""

from collections import Counter

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.classifier.classify import slug, subdomain_id
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

router = APIRouter()
LISTS = {"availability": "availability_id", "domains": "domain_id", "subdomains": "subdomain_id",
         "trl_levels": "trl_id", "path_steps": "step_id", "mechanisms": "mechanism_id",
         "assumptions": "assumption_id"}
# where a technology's classification holds each list's id
CLASSIFIED_AS = {"availability": "classification.availability.value_id", "domains": "classification.domain.domain_id",
                 "subdomains": "classification.domain.subdomain_id", "trl_levels": "classification.trl.level"}
# where a technology's effective classification (services/radar_status) holds it: what the counts use
EFFECTIVE = {"availability": lambda c: c["availability"]["id"], "domains": lambda c: c["domain"]["id"],
             "subdomains": lambda c: c["domain"]["subdomain_id"], "trl_levels": lambda c: c["trl"]["level"]}
EDITABLE = {"name", "definition", "order", "emerging", "catch_all", "domain_id", "status", "evidence_needed",
            "decision", "date"}


def _list(name: str):
    if name not in LISTS:
        raise HTTPException(status_code=404, detail=f"unknown list {name!r}")
    return get_collection(name)


def _match(name: str, item: dict) -> dict:
    """The technologies classified under this item."""
    value = item.get("level") if name == "trl_levels" else item["_id"]
    return {CLASSIFIED_AS[name]: value} if name in CLASSIFIED_AS else {"_id": None}


class Item(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: str | None = Field(default=None, max_length=4000)
    order: int | None = None
    emerging: bool | None = None
    catch_all: bool | None = None
    domain_id: str | None = None          # sub-domains
    status: str | None = None             # sub-domains: seeded, new
    evidence_needed: str | None = Field(default=None, max_length=4000)  # path steps
    decision: str | None = Field(default=None, max_length=2000)
    date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # assumptions: the day it was stated


@router.get("/lists/{name}")
def read(name: str) -> dict:
    coll = _list(name)
    items = list(coll.find())
    counts: Counter = Counter()
    if name in CLASSIFIED_AS:  # as the Technologies list counts them: a person's or an import's choice, the assessment, the pages
        from app.services import radar_status
        counts = Counter(EFFECTIVE[name](c) for c in radar_status.classifications().values())
    for i in items:  # how many technologies are filed here
        i["technologies"] = counts.get(i.get("level") if name == "trl_levels" else i["_id"], 0)
    items.sort(key=lambda i: (i.get("order", 50), i.get("domain_id") or "", str(i.get("level") or ""), i.get("name", "")))
    return {"list": name, "items": items}


@router.post("/lists/{name}", status_code=201)
def add(name: str, item: Item) -> dict:
    coll = _list(name)
    if name == "subdomains" and not item.domain_id:
        raise HTTPException(status_code=422, detail="a sub-domain belongs to a domain: say which")
    if name == "assumptions" and not item.date:
        raise HTTPException(status_code=422, detail="an assumption needs the date it was stated")
    if name == "trl_levels":
        raise HTTPException(status_code=422, detail="the TRL scale is fixed at 1 to 9: edit a level's words instead")
    item_id = subdomain_id(item.domain_id, item.name) if name == "subdomains" else slug(item.name)
    if coll.find_one({"_id": item_id}):
        raise HTTPException(status_code=409, detail=f"{item.name!r} is already in this list")
    doc = {"_id": item_id, LISTS[name]: item_id, **item.model_dump(exclude_none=True), "updated_at": now_utc(), "version": 1}
    if name == "subdomains":
        doc.setdefault("status", "seeded")
    coll.insert_one(doc)
    return {"item": doc}


@router.put("/lists/{name}/{item_id}")
def edit(name: str, item_id: str, item: Item) -> dict:
    coll = _list(name)
    old = coll.find_one({"_id": item_id})
    if old is None:
        raise HTTPException(status_code=404, detail=f"no {item_id!r} in this list")
    changes = {k: v for k, v in item.model_dump(exclude_none=True).items() if k in EDITABLE}
    if name == "assumptions" and not changes.get("date", old.get("date")):
        raise HTTPException(status_code=422, detail="an assumption needs the date it was stated")
    coll.update_one({"_id": item_id}, {"$set": {**changes, "updated_at": now_utc()}, "$inc": {"version": 1}})
    marked = 0
    if name in CLASSIFIED_AS and changes.get("definition") not in (None, old.get("definition")):
        marked = get_collection("technologies").update_many(
            _match(name, old), {"$set": {"classification_stale": True}}).modified_count
    return {"item": coll.find_one({"_id": item_id}), "marked_for_review": marked}


@router.delete("/lists/{name}/{item_id}")
def remove(name: str, item_id: str) -> dict:
    coll = _list(name)
    old = coll.find_one({"_id": item_id})
    if old is None:
        raise HTTPException(status_code=404, detail=f"no {item_id!r} in this list")
    if old.get("catch_all"):
        raise HTTPException(status_code=422, detail="the catch-all stays: technologies that fit nothing else go there")
    if name == "trl_levels":
        raise HTTPException(status_code=422, detail="the TRL scale is fixed at 1 to 9")
    moved = 0
    if name in CLASSIFIED_AS:  # to the list's catch-all (none for a sub-domain); with none flagged, they show under it anyway
        catch = None if name == "subdomains" else (coll.find_one({"catch_all": True}, {"_id": 1}) or {}).get("_id")
        moved = get_collection("technologies").update_many(
            _match(name, old), {"$set": {CLASSIFIED_AS[name]: catch, "classification_stale": True}}).modified_count
    coll.delete_one({"_id": item_id})
    return {"removed": item_id, "moved_to_catch_all": moved}


class Merge(BaseModel):
    into: str = Field(min_length=1)


@router.post("/lists/subdomains/{item_id}/merge")
def merge(item_id: str, m: Merge) -> dict:
    """A proposed (or duplicate) sub-domain folded into another: its
    technologies move there, at no model cost, and it's removed."""
    coll = get_collection("subdomains")
    old, target = coll.find_one({"_id": item_id}), coll.find_one({"_id": m.into})
    if old is None or target is None:
        raise HTTPException(status_code=404, detail="both sub-domains must exist")
    moved = get_collection("technologies").update_many(
        {"classification.domain.subdomain_id": item_id},
        {"$set": {"classification.domain.subdomain_id": m.into, "classification.domain.domain_id": target["domain_id"]},
         "$unset": {"classification.domain.subdomain_new": ""}}).modified_count
    get_collection("decisions").update_many({"kind": "move", "field": "subdomain", "value": item_id, "active": True},
                                            {"$set": {"value": m.into}})
    coll.delete_one({"_id": item_id})
    return {"merged": item_id, "into": m.into, "technologies_moved": moved}
