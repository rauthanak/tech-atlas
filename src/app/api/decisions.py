"""People's choices (services/decisions) and the two to-do lists (services/gates)."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services import classify_effective, decisions, gates
from app.services.db.mongo import get_collection
from app.services.timezone import request_tz

router = APIRouter()

Kind = Literal["move", "override", "hand_score", "accept_gap", "tata_entry", "nascent", "catalog", "use_case",
               "path_step", "finance", "bottlenecks", "commitment"]


class DecisionIn(BaseModel):
    kind: Kind
    tech_id: str = Field(min_length=1, max_length=200)
    fabric_id: str | None = None
    measure_id: str | None = None
    field: str | None = None
    key: str | None = Field(default=None, max_length=300)
    value: Any = None
    reason: str | None = Field(default=None, max_length=2000)


def _applied(tech_id: str, fabric_id: str | None) -> dict | None:
    if not fabric_id:
        return None
    return next((a for a in gates.latest_applied([tech_id]).get(tech_id, []) if a["fabric_id"] == fabric_id), None)


@router.post("/decisions", status_code=201)
def create(d: DecisionIn, tz: str = Depends(request_tz)) -> dict:
    computed = None
    if d.kind == "override":  # the priority it overrides, so a later move can be flagged
        current = _applied(d.tech_id, d.fabric_id)
        if current is None:
            raise HTTPException(status_code=422, detail="there's no assessment in this fabric to override")
        computed = current["effective"]["computed_priority"]
    extra = None
    if d.kind == "nascent" and d.value == "no":  # dismissed until a page it hasn't seen flags it again
        t = get_collection("technologies").find_one({"_id": d.tech_id}, {"pages_seen": 1}) or {}
        extra = {"pages_known": t.get("pages_seen") or []}
    try:
        doc = decisions.create(d.kind, d.tech_id, value=d.value, fabric_id=d.fabric_id, measure_id=d.measure_id,
                               field=d.field, key=d.key, reason=d.reason, tz=tz, computed=computed, extra=extra)
    except decisions.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if d.kind == "nascent" and d.value == "yes":
        decisions.create("move", d.tech_id, field="availability", value=_nascent_availability(d.tech_id),
                         reason="Confirmed as possibly nascent", tz=tz)
    return {"decision": doc}


TRIAL = ("trial", "pilot", "deploy", "field test", "rollout")


def _nascent_availability(tech_id: str) -> str:
    """Pilot when the flagging page shows a trial or deployment; else Research."""
    t = get_collection("technologies").find_one({"_id": tech_id}, {"classification.nascent": 1, "name": 1}) or {}
    page = ((t.get("classification") or {}).get("nascent") or {}).get("page")
    doc = get_collection("documents").find_one({"_id": page}, {"signals": 1}) if page else None
    words = " ".join(f"{s.get('signal_id', '')} {s.get('label', '')} {s.get('name', '')}".lower()
                     for s in (doc or {}).get("signals") or [] if t.get("name") in (s.get("technologies_resolved") or []))
    return "pilot" if any(w in words for w in TRIAL) else "research"


@router.delete("/decisions/{decision_id}")
def undo(decision_id: str, tz: str = Depends(request_tz)) -> dict:
    doc = decisions.deactivate(decision_id, tz)
    if doc is None:
        raise HTTPException(status_code=404, detail="no such choice in force: it may have been undone or replaced")
    return {"decision": doc}


@router.get("/decisions/leader")
def leader_record(tech_id: str, fabric_id: str) -> dict:
    """What a leader has recorded for a technology in a fabric, and its state."""
    return decisions.leader_state(decisions.active([tech_id], ["commitment", "path_step", "bottlenecks"]),
                                  tech_id, fabric_id)


@router.get("/decisions")
def list_decisions(tech_id: str, include_inactive: bool = False) -> dict:
    query: dict = {"tech_id": tech_id} if include_inactive else {"tech_id": tech_id, "active": True}
    return {"decisions": described(list(get_collection("decisions").find(query).sort("at", -1)))}


FIELD_WORDS = {"availability": "Commercial availability", "domain": "Domain", "subdomain": "Sub-domain",
               "trl": "Readiness (TRL)"}
LIST_OF = {"availability": "availability", "domain": "domains", "subdomain": "subdomains", "trl": "trl"}


def described(decs: list[dict]) -> list[dict]:
    """Each choice with `what` it set, in plain words, and the catalog file
    when an import recorded it (`from_file`): a technology's History."""
    from app.services import finance
    names = classify_effective.names()
    measures = {m["_id"]: m for m in get_collection("measures").find({}, {"name": 1, "scope": 1})}
    fabrics = {f["_id"]: f["name"] for f in get_collection("fabrics").find({}, {"name": 1})}
    steps = {k: s["name"] for k, s in finance.steps().items()}
    for d in decs:
        k, v = d["kind"], d.get("value")
        where = f" in {fabrics.get(d['fabric_id'], d['fabric_id'])}" if d.get("fabric_id") else ""
        m = measures.get(d.get("measure_id")) or {"name": d.get("measure_id")}
        if k == "move":
            item = names[LIST_OF[d["field"]]].get(v) if d.get("field") in LIST_OF else None
            what = f"{FIELD_WORDS.get(d.get('field'), d.get('field'))} set to " + (
                f"TRL {v}" if d.get("field") == "trl" else (item or {}).get("name", str(v)))
        elif k == "override":
            what = f"Priority{where} set to {v}" + (f" (it was computed {d['computed']})" if d.get("computed") else "")
        elif k == "hand_score":
            what = f"{m['name']}{where} scored {v} by hand"
        elif k == "accept_gap":
            what = f"{m['name']}{where} left out" if m.get("scope") == "tata" else f"{m['name']}{where}: gap accepted"
        elif k == "tata_entry":
            what = f"{m['name']}{where} entered as {v}"
        elif k == "nascent":
            what = "Confirmed as possibly nascent" if v == "yes" else "Answered: not nascent"
        elif k == "catalog":
            what = "Added to the catalog" if v == "yes" else "Taken out of the catalog"
        elif k == "use_case":
            what = f"A suggested use case{where} {'accepted' if v == 'accept' else 'rejected'}"
        elif k == "path_step":
            what = f"Step reached{where}: {steps.get(v, v)}"
        elif k == "finance":
            what = f"Finance figures entered{where}"
        elif k == "bottlenecks":
            n = len((v or {}).get("picked") or []) + (1 if (v or {}).get("other") else 0)
            what = f"Blockers picked{where}: {n}"
        elif k == "commitment":
            what = f"Owner and next action recorded{where}" + (f": {v['owner']}" if (v or {}).get("owner") else "")
        else:
            what = k
        d["what"] = what
        d["from_file"] = classify_effective.imported_from(d)
    return decs


@router.get("/gates")
def the_gates() -> dict:
    """Before scoring (Gate 1) and before publishing (Gate 2), from one read of the states."""
    from app.services import evidence, radar_status
    all_states = evidence.states()
    gate1 = radar_status.gate1(all_states)
    for item in gate1:
        if item["kind"] == "nascent":  # each row answers Yes or No in place: say what a Yes would replace
            ids = [t["tech_id"] for t in item["technologies"]]
            chosen, lists = decisions.active(ids, ["move"]), classify_effective.names()
            replaces = {t["_id"]: classify_effective.effective(t, chosen, lists)["nascent"]["yes_replaces"]
                        for t in get_collection("technologies").find({"_id": {"$in": ids}},
                                                                      {"classification": 1, "assessed_classification": 1})}
            for t in item["technologies"]:
                t["replaces"] = replaces.get(t["tech_id"])
    return {"gate1": gate1, "gate2": gates.gate2(all_states)}
