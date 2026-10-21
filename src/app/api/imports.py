"""Import a list of emerging technologies (services/imports), and add one by
hand. Nothing from a file is saved until the import is confirmed."""

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services import imports
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc, request_tz

router = APIRouter()
MAX_BYTES = 10 * 1024 * 1024


def _get(import_id: str) -> dict:
    imp = get_collection("imports").find_one({"_id": import_id})
    if imp is None:
        raise HTTPException(status_code=404, detail="no such import")
    return imp


def _editable(import_id: str) -> dict:
    imp = _get(import_id)
    if imp["status"] == "confirmed":
        raise HTTPException(status_code=409, detail="this import is already confirmed: reopen it to review it again")
    return imp


@router.get("/imports/template")
def template() -> Response:
    return Response(imports.template(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="emerging-technologies-template.xlsx"'})


@router.post("/imports", status_code=201)
async def upload(file: UploadFile = File(...), tz: str = Depends(request_tz)) -> dict:
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="the file is over 10 MB")
    try:
        return imports.view(imports.create(content, file.filename or "upload.xlsx", tz))
    except imports.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/imports")
def list_imports() -> dict:
    return {"imports": list(get_collection("imports").find({}, {"items": 0, "unknown_values": 0}).sort("at", -1).limit(20))}


@router.get("/imports/{import_id}")
def get_import(import_id: str) -> dict:
    return imports.view(_get(import_id))


@router.get("/imports/{import_id}/match/preview")
def match_preview(import_id: str) -> dict:
    imp = _get(import_id)
    return imports.match_cost([it["name"].lower() for it in imp["items"] if it["group"] == "unmatched"])


@router.post("/imports/{import_id}/match")
def match(import_id: str) -> dict:
    _editable(import_id)
    return imports.view(imports.match(import_id))


class ItemsDecision(BaseModel):
    rows: list[int] = Field(min_length=1)
    decision: Literal["accept", "reject"]


@router.put("/imports/{import_id}/items")
def decide_items(import_id: str, body: ItemsDecision) -> dict:
    imp = _editable(import_id)
    for it in imp["items"]:
        if it["row"] in body.rows and it["group"] == "proposed":
            it["decision"] = body.decision
    imp["counts"] = imports.counts(imp)
    get_collection("imports").replace_one({"_id": import_id}, imp)
    return imports.view(imp)


class ValueMap(BaseModel):
    field: str
    value: str
    domain_id: str | None = None  # a sub-domain's domain: the same name can sit under two
    map_to: str | int | None = None
    keep: bool | None = None


@router.put("/imports/{import_id}/values")
def map_values(import_id: str, body: list[ValueMap]) -> dict:
    """A person's choice for values not in our lists: one of ours (map_to),
    kept as written (keep, a sub-domain only), or left out. A domain mapped
    here brings in its sub-domains that aren't in our lists."""
    imp = _editable(import_id)
    for m in body:
        for u in imp["unknown_values"]:
            if u["field"] == m.field and u["value"] == m.value and (m.field != "subdomain" or u.get("domain_id") == m.domain_id):
                u["map_to"], u["keep"] = m.map_to, bool(m.keep)
    imp["unknown_values"] = imports.map_values(imp["items"], imp["unknown_values"])
    imp["counts"] = imports.counts(imp)
    get_collection("imports").replace_one({"_id": import_id}, imp)
    return imports.view(imp)


@router.post("/imports/{import_id}/confirm")
def confirm(import_id: str, tz: str = Depends(request_tz)) -> dict:
    imp = _editable(import_id)
    if imp["status"] == "discarded":
        raise HTTPException(status_code=409, detail="this import was discarded: upload the file again to start over")
    if any(it["group"] == "unmatched" for it in imp["items"]):
        raise HTTPException(status_code=409, detail="match the names first: some aren't checked against the register yet")
    if any(it["group"] == "proposed" and it["decision"] is None for it in imp["items"]):
        raise HTTPException(status_code=409, detail="accept or reject every proposed match first")
    waiting = imports.counts(imp)["values_waiting"]
    if waiting:
        raise HTTPException(status_code=409, detail=f"choose what to do with every sub-domain not in our lists first: "
                                                    f"{waiting} still {'waits' if waiting == 1 else 'wait'}")
    return imports.confirm(import_id, tz)


class Reopen(BaseModel):
    rows: list[int] | None = None


@router.post("/imports/{import_id}/reopen")
def reopen(import_id: str, body: Reopen | None = None, tz: str = Depends(request_tz)) -> dict:
    """Undo what confirm did for rows that joined a technology (by default
    every accepted proposed match) and put them back to review."""
    _get(import_id)
    try:
        return imports.reopen(import_id, body.rows if body else None, tz)
    except imports.Refused as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/imports/{import_id}")
def discard(import_id: str) -> dict:
    if _get(import_id)["status"] == "confirmed":
        raise HTTPException(status_code=409, detail="a confirmed import stays on record")
    get_collection("imports").update_one({"_id": import_id}, {"$set": {"status": "discarded"}})
    return {"discarded": import_id}


# ── one technology by hand: a one-row import ─────────────────────────

class AddOne(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    confirm: Literal["join", "new"] | None = None
    into: str | None = None
    availability: str | None = None
    domain: str | None = None
    subdomain: str | None = None
    trl: int | None = None


@router.get("/technologies/add/preview")
def add_preview(name: str) -> dict:
    """What adding this name would do, and what it costs, before it's done."""
    if not name.strip():
        raise HTTPException(status_code=422, detail="type a name")
    return imports.add_preview(name.strip())


@router.post("/technologies")
def add_technology(body: AddOne, tz: str = Depends(request_tz)) -> dict:
    """One technology by hand, matched like an import: an exact name or alias
    joins it; a close name (from its brackets, or from the organize skill) is
    offered to confirm; else it's added with no pages. The values given are
    recorded as a person's choices on the technology it joins or adds."""
    name = body.name.strip()
    try:
        values = imports.chosen_values(body.availability, body.domain, body.subdomain, body.trl)
    except imports.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    techs = get_collection("technologies")

    def done(outcome: str, tech_id: str, shown: str, **extra) -> dict:
        n = imports.set_values(tech_id, values, imports.ADDED_BY_HAND, tz)
        return {"outcome": outcome, "tech_id": tech_id, "name": shown, "values_set": n, **extra}

    group, hit, why = imports.free_match(name)
    if group == "matched":
        return done("matched", hit["_id"], hit.get("label") or hit["name"])
    if body.confirm == "join" and body.into:
        target = techs.find_one({"_id": body.into})
        if target is None:
            raise HTTPException(status_code=404, detail="that technology is gone")
        techs.update_one({"_id": body.into}, {"$addToSet": {"aliases": name.lower()}})
        from agent.resolver import restamp_all
        restamp_all()
        return done("matched", target["_id"], target.get("label") or target["name"])
    kept_apart = None
    if body.confirm != "new":
        if group != "proposed":
            found, kept, _ = imports.propose([name.lower()], "add-by-hand")
            hit, why = found.get(name.lower()), "The organize skill reads it as this technology in other words"
            kept_apart = kept.get(name.lower())
        if hit:
            return {"outcome": "proposed", "tech_id": "", "name": name, "why": why,
                    "proposed": {"tech_id": hit["_id"], **imports.target_info([hit["_id"]]).get(hit["_id"], {})}}
    tech_id = imports.new_technology(name, "added", {"added": {"at": now_utc(), "tz": tz}})
    return done("added", tech_id, name, kept_apart={"tech_id": kept_apart["_id"], "name": kept_apart.get("label")
                                                     or kept_apart["name"]} if kept_apart else None)
