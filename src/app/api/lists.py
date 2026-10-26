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
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.classifier.classify import slug, subdomain_id
from app.services import tech_status
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

router = APIRouter()
LISTS = {"availability": "availability_id", "domains": "domain_id", "subdomains": "subdomain_id",
         "trl_levels": "trl_id", "path_steps": "step_id", "mechanisms": "mechanism_id",
         "assumptions": "assumption_id"}
# where a technology's classification holds each list's id
CLASSIFIED_AS = {"availability": "classification.availability.value_id", "domains": "classification.domain.domain_id",
                 "subdomains": "classification.domain.subdomain_id", "trl_levels": "classification.trl.level"}
# where people's moves (their `field`) and the assessment's answer hold each list's id
MOVED_AS = {"availability": "availability", "domains": "domain", "subdomains": "subdomain"}
ASSESSED_AS = {"availability": "assessed_classification.availability.value_id",
               "domains": "assessed_classification.domain.domain_id",
               "subdomains": "assessed_classification.domain.subdomain_id"}
# where a technology's stored answers (services/tech_status) hold its effective classification: what the counts use
EFFECTIVE = {"availability": "f.availability", "domains": "f.domain", "subdomains": "f.subdomain", "trl_levels": "f.trl"}
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
        tech_status.fresh()
        counts = Counter({r["_id"]: r["n"] for r in get_collection("tech_status").aggregate(
            [{"$group": {"_id": f"${EFFECTIVE[name]}", "n": {"$sum": 1}}}])})
    for i in items:  # how many technologies are filed here
        i["technologies"] = counts.get(i.get("level") if name == "trl_levels" else i["_id"], 0)
    items.sort(key=lambda i: (i.get("order", 50), i.get("domain_id") or "", str(i.get("level") or ""), i.get("name", "")))
    # technologies with no value from this list (a TRL not judged yet): counted, so the counts add up
    listed = {i.get("level") if name == "trl_levels" else i["_id"] for i in items}
    unset = sum(n for k, n in counts.items() if k not in listed)
    return {"list": name, "items": items, **({"unset": unset} if name in CLASSIFIED_AS else {})}


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


def repair(name: str, item_id: str) -> dict:
    """Before an item leaves its list: the choices people (or an import) made
    for it are withdrawn (History keeps them), the assessment's answer for it is
    cleared, and those technologies are marked to be classified again, so none
    points at a value that's gone."""
    if name not in MOVED_AS:
        return {"choices_withdrawn": 0, "assessments_cleared": 0}
    decs, techs = get_collection("decisions"), get_collection("technologies")
    moves = {"kind": "move", "field": MOVED_AS[name], "value": item_id, "active": True}
    tech_ids = set(decs.distinct("tech_id", moves))
    withdrawn = decs.update_many(moves, {"$set": {"active": False, "replaced_at": now_utc(),
                                                  "removed_from_list": item_id}}).modified_count
    assessed = techs.distinct("_id", {ASSESSED_AS[name]: item_id})
    clear = ({"$set": {ASSESSED_AS[name]: None}} if name == "subdomains"
             else {"$unset": {ASSESSED_AS[name].rsplit(".", 1)[0]: ""}})
    if assessed:
        techs.update_many({"_id": {"$in": assessed}}, clear)
    techs.update_many({"_id": {"$in": list(tech_ids | set(assessed))}}, {"$set": {"classification_stale": True}})
    return {"choices_withdrawn": withdrawn, "assessments_cleared": len(assessed)}


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
    repaired = repair(name, item_id)
    coll.delete_one({"_id": item_id})
    return {"removed": item_id, "moved_to_catch_all": moved, **repaired}


class Merge(BaseModel):
    into: str = Field(min_length=1)


class BulkMerge(Merge):
    ids: list[str] = Field(min_length=1, max_length=5000)


class BulkStatus(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)
    status: Literal["seeded", "new"]  # Accept, or its Undo


class Unmerge(BaseModel):
    """What a merge returned as `undo`: the sub-domains it removed, the
    technologies it moved and the people's choices it pointed elsewhere."""
    into: str
    subdomains: list[dict] = Field(max_length=5000)
    moves: list[dict] = Field(max_length=100_000)
    decisions: list[dict] = Field(max_length=100_000)


def _merge(ids: list[str], into: str) -> dict:
    """Proposed (or duplicate) sub-domains folded into another: their
    technologies move there, at no model cost, and they're removed. Returns
    what Undo needs to put them back."""
    coll = get_collection("subdomains")
    target = coll.find_one({"_id": into})
    olds = list(coll.find({"_id": {"$in": [i for i in ids if i != into]}}))
    if target is None or not olds:
        raise HTTPException(status_code=404, detail="both sub-domains must exist")
    gone = [o["_id"] for o in olds]
    techs, decisions = get_collection("technologies"), get_collection("decisions")
    moves = [{"tech_id": t["_id"], "subdomain_id": t["classification"]["domain"]["subdomain_id"],
              "domain_id": t["classification"]["domain"].get("domain_id"),
              "new": bool(t["classification"]["domain"].get("subdomain_new"))}
             for t in techs.find({"classification.domain.subdomain_id": {"$in": gone}},
                                 {"classification.domain": 1})]
    chosen = [{"id": d["_id"], "value": d["value"]} for d in decisions.find(
        {"kind": "move", "field": "subdomain", "value": {"$in": gone}, "active": True}, {"value": 1})]
    techs.update_many({"classification.domain.subdomain_id": {"$in": gone}},
                      {"$set": {"classification.domain.subdomain_id": into,
                                "classification.domain.domain_id": target["domain_id"]},
                       "$unset": {"classification.domain.subdomain_new": ""}})
    decisions.update_many({"_id": {"$in": [d["id"] for d in chosen]}}, {"$set": {"value": into}})
    coll.delete_many({"_id": {"$in": gone}})
    tech_status.touch([m["tech_id"] for m in moves], now=True)  # the counts and lists show where they went
    return {"merged": len(gone), "into": into, "technologies_moved": len(moves),
            "undo": {"into": into, "subdomains": olds, "moves": moves, "decisions": chosen}}


@router.post("/lists/subdomains/merge")
def merge_many(m: BulkMerge) -> dict:
    return _merge(m.ids, m.into)


@router.post("/lists/subdomains/unmerge")
def unmerge(u: Unmerge) -> dict:
    """Undo a merge: the sub-domains come back and their technologies (still
    where the merge put them) and people's choices return to them."""
    coll, techs = get_collection("subdomains"), get_collection("technologies")
    for doc in u.subdomains:
        coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    back = []
    for mv in u.moves:
        done = techs.update_one(
            {"_id": mv["tech_id"], "classification.domain.subdomain_id": u.into},
            {"$set": {"classification.domain.subdomain_id": mv["subdomain_id"],
                      "classification.domain.domain_id": mv["domain_id"],
                      **({"classification.domain.subdomain_new": True} if mv.get("new") else {})}}).modified_count
        if done:
            back.append(mv["tech_id"])
    for d in u.decisions:
        get_collection("decisions").update_one({"_id": d["id"], "value": u.into}, {"$set": {"value": d["value"]}})
    tech_status.touch(back, now=True)
    return {"put_back": len(u.subdomains), "technologies_moved_back": len(back)}


@router.post("/lists/subdomains/status")
def set_status(b: BulkStatus) -> dict:
    """Accept many proposed sub-domains at once (status seeded), or undo that (new)."""
    n = get_collection("subdomains").update_many(
        {"_id": {"$in": b.ids}}, {"$set": {"status": b.status, "updated_at": now_utc()}, "$inc": {"version": 1}}).modified_count
    return {"changed": n}


@router.post("/lists/subdomains/{item_id}/merge")
def merge(item_id: str, m: Merge) -> dict:
    return _merge([item_id], m.into)
