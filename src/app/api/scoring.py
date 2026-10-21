"""Scoring configuration endpoints: fabrics, measures, scoring_config —
the editable method behind the assessment stage. Reads feed the portal's
Scoring tab; PUTs are admin edits (version bumped, timestamped)."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

router = APIRouter()

Axis = Literal["market_potential", "strategic_fit", "adoption_readiness", "extra"]


def _list(collection: str) -> list[dict]:
    return list(get_collection(collection).find().sort("_id", 1))


def _apply_edit(collection: str, doc_id: str, changes: dict) -> dict:
    updated = get_collection(collection).find_one_and_update(
        {"_id": doc_id},
        {"$set": {**changes, "updated_at": now_utc()}, "$inc": {"version": 1}},
        return_document=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown {collection} entry {doc_id!r}")
    return updated


# ── overview ─────────────────────────────────────────────────────────

@router.get("/scoring/overview")
def overview() -> dict:
    fabrics = _list("fabrics")
    measures = _list("measures")
    config = _list("scoring_config")
    # An item is pending while its open_question is non-empty; blanking the
    # question settles it.
    pending = []
    for kind, docs, label_key in (("fabric", fabrics, "name"),
                                  ("measure", measures, "name"),
                                  ("config", config, "name")):
        for doc in docs:
            question = (doc.get("open_question") or "").strip()
            if question:
                pending.append({
                    "kind": kind,
                    "id": doc["_id"],
                    "label": doc.get(label_key) or doc["_id"],
                    "open_question": question,
                })
    axes: dict[str, list] = {}
    for measure in measures:
        axes.setdefault(measure["axis"], []).append(
            {"id": measure["_id"], "code": measure["code"],
             "name": measure["name"], "weight": measure.get("weight")})
    return {
        "fabrics": {"total": len(fabrics), "enabled": sum(f.get("enabled", False) for f in fabrics)},
        "measures": {"total": len(measures), "by_axis": axes},
        "config": {c["_id"]: {k: v for k, v in c.items()
                              if k not in ("_id", "name")} for c in config},
        "pending": pending,
        "total_items": len(fabrics) + len(measures) + len(config),
    }


# ── fabrics ──────────────────────────────────────────────────────────

class Lever(BaseModel):
    lever_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    mechanism_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)


class FinanceDefaults(BaseModel):
    margin_low: float | None = Field(default=None, ge=0, le=1)
    margin_high: float | None = Field(default=None, ge=0, le=1)
    loss_without: float | None = Field(default=None, ge=0, le=1)
    loss_with: float | None = Field(default=None, ge=0, le=1)


class FabricEdit(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=4000)
    tcl_today: str | None = Field(default=None, max_length=4000)  # what TCL runs in it, with its source pages
    enabled: bool
    open_question: str | None = Field(default=None, max_length=1000)
    # where the value lands (Nick's note, corrected by Tata); left as they are when not sent
    levers: list[Lever] | None = Field(default=None, max_length=6)
    key_metrics: str | None = Field(default=None, max_length=2000)
    bottlenecks: list[str] | None = Field(default=None, max_length=20)
    cautions: str | None = Field(default=None, max_length=2000)
    finance_defaults: FinanceDefaults | None = None


@router.get("/scoring/fabrics")
def list_fabrics() -> dict:
    return {"fabrics": _list("fabrics")}


@router.put("/scoring/fabrics/{fabric_id}")
def update_fabric(fabric_id: str, edit: FabricEdit) -> dict:
    changes = edit.model_dump()
    for key in ("levers", "key_metrics", "bottlenecks", "cautions", "finance_defaults"):
        if changes[key] is None:
            del changes[key]
    return _apply_edit("fabrics", fabric_id, changes)


# ── measures ─────────────────────────────────────────────────────────

class Anchors(BaseModel):
    low: str = Field(min_length=1, max_length=1000)
    mid: str = Field(min_length=1, max_length=1000)
    high: str = Field(min_length=1, max_length=1000)


class MeasureEdit(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    axis: Axis
    weight: float | None = Field(default=None, ge=0, le=1)
    definition: str = Field(min_length=1, max_length=4000)
    anchors: Anchors
    required_evidence: str = Field(min_length=1, max_length=2000)
    open_question: str | None = Field(default=None, max_length=1000)
    # technology: judged once for the technology as a whole · fabric: judged in
    # each fabric · tata: entered by Tata Communications, never asked of the model
    scope: Literal["technology", "fabric", "tata"] | None = None


@router.get("/scoring/measures")
def list_measures() -> dict:
    return {"measures": _list("measures")}


@router.put("/scoring/measures/{measure_id}")
def update_measure(measure_id: str, edit: MeasureEdit) -> dict:
    changes = edit.model_dump()
    if changes["scope"] is None:  # not sent: left as it is
        del changes["scope"]
    return _apply_edit("measures", measure_id, changes)


# ── scoring config ───────────────────────────────────────────────────

PROTECTED_KEYS = {"_id", "name", "version", "updated_at", "status"}


@router.get("/scoring/config")
def list_config() -> dict:
    return {"config": _list("scoring_config")}


@router.put("/scoring/config/{name}")
def update_config(name: str, body: dict) -> dict:
    changes = {k: v for k, v in body.items() if k not in PROTECTED_KEYS}
    if not changes:
        raise HTTPException(status_code=422, detail="no editable fields in body")
    return _apply_edit("scoring_config", name, changes)
