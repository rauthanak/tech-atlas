"""Scoring configuration endpoints: fabrics, measures, scoring_config —
the editable method behind the assessment stage. Reads feed the portal's
Scoring tab; PUTs are admin edits (version bumped, timestamped)."""

import math
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


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _reasons(name: str, current: dict, changes: dict) -> list[str]:
    """Why a scoring setting can't be saved as sent, in plain words (none: it can)."""
    from agent.analyzer.placement import POTENTIAL_BANDS, TIMELINE_BANDS
    from app.services.decisions import PRIORITIES
    why = [f"{k!r} isn't a setting of {name}" for k in changes if k not in current and k not in ("open_question", "note")]
    q = changes.get("open_question")
    if "open_question" in changes and not (q is None or (isinstance(q, str) and len(q) <= 1000)):
        why.append("the open question is text of at most 1,000 characters, or empty")
    for key, label in (("timeline_cutpoints", "How soon"), ("potential_cutpoints", "How big")):
        if key in changes:
            v = changes[key]
            if not (isinstance(v, list) and len(v) == 2 and all(_number(x) for x in v) and 0 <= v[0] < v[1] <= 10):
                why.append(f"the {label} band edges are two numbers from 0 to 10, the lower first")
    for key, label in (("timeline_from", "How soon"), ("potential_from", "How big")):
        if key in changes:
            v = changes[key]
            known = set(get_collection("measures").distinct("_id"))
            if not (isinstance(v, list) and v):
                why.append(f"{label} is worked out from at least one measure")
            else:
                why += [f"unknown measure {m!r} in {label}" for m in v if m not in known]
    if "grid" in changes:
        cells = {f"{t}_{p}" for t in TIMELINE_BANDS for p in POTENTIAL_BANDS}
        g = changes["grid"]
        if not (isinstance(g, dict) and set(g) == cells and all(v in PRIORITIES for v in g.values())):
            why.append("the grid has one cell for each How soon and How big band, each a priority from P1 to P6")
    if "max_dossier_tokens" in changes:
        v = changes["max_dossier_tokens"]
        if not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
            why.append("the evidence limit is a whole number of tokens above 0, such as 500,000")
    if "mode" in changes and changes["mode"] not in ("stacked", "per_measure"):
        why.append("an assessment calls the model one of two ways: stacked or per_measure")
    if "map" in changes:
        m = changes["map"]
        if not (isinstance(m, dict) and set(m) == {"near", "mid", "far"} and all(isinstance(v, str) and v.strip()
                                                                                for v in m.values())):
            why.append("the horizons name near, mid and far, each with a label")
    return why


@router.put("/scoring/config/{name}")
def update_config(name: str, body: dict) -> dict:
    changes = {k: v for k, v in body.items() if k not in PROTECTED_KEYS}
    if not changes:
        raise HTTPException(status_code=422, detail="no editable fields in body")
    current = get_collection("scoring_config").find_one({"_id": name})
    if current is None:
        raise HTTPException(status_code=404, detail=f"unknown scoring_config entry {name!r}")
    if why := _reasons(name, current, changes):  # checked before anything is saved
        raise HTTPException(status_code=422, detail="; ".join(why))
    return _apply_edit("scoring_config", name, changes)


class Edges(BaseModel):
    timeline_cutpoints: list[float] = Field(min_length=2, max_length=2)
    potential_cutpoints: list[float] = Field(min_length=2, max_length=2)


@router.post("/scoring/edges/preview")
def edges_preview(e: Edges) -> dict:
    """What new band edges would do, before they're saved: each technology's
    latest assessment in each fabric placed with today's edges and with these,
    from its stored how-soon and how-big scores. Arithmetic only, no model call."""
    from agent.analyzer.placement import POTENTIAL_BANDS, TIMELINE_BANDS, _band
    grid_doc = get_collection("scoring_config").find_one({"_id": "priority_grid"}) or {}
    grid = grid_doc.get("grid", {})

    def place(t, p, t_cuts, p_cuts):
        tb, pb = _band(t, t_cuts, TIMELINE_BANDS), _band(p, p_cuts, POTENTIAL_BANDS)
        return grid.get(f"{tb}_{pb}") if tb and pb else None

    moves: dict[tuple, int] = {}
    total = 0
    for a in get_collection("assessments").aggregate([
            {"$sort": {"tech_id": 1, "fabric_id": 1, "created_at": -1}},
            {"$group": {"_id": {"t": "$tech_id", "f": "$fabric_id"},
                        "soon": {"$first": "$placement.timeline.score"}, "big": {"$first": "$placement.potential.score"}}}],
            allowDiskUse=True):
        if a["soon"] is None or a["big"] is None:
            continue
        total += 1
        now = place(a["soon"], a["big"], grid_doc.get("timeline_cutpoints", [4, 7]), grid_doc.get("potential_cutpoints", [4, 7]))
        new = place(a["soon"], a["big"], e.timeline_cutpoints, e.potential_cutpoints)
        if now != new:
            moves[(now, new)] = moves.get((now, new), 0) + 1
    return {"placed": total,
            "moves": [{"from": f, "to": t, "count": n}
                      for (f, t), n in sorted(moves.items(), key=lambda m: (-m[1], str(m[0])))]}
