"""Setup › Finance: every technology and fabric with finance inputs, or whose
path to scale is set and whose finance card asks for something (from Proof
of concept on, or when the next rung needs a note or figure the card holds),
with what the next rung needs (services/finance)."""

from fastapi import APIRouter

from app.services import decisions, finance
from app.services.db.mongo import get_collection

router = APIRouter()


@router.get("/finance")
def table(missing: bool = False) -> dict:
    path = finance.steps()
    decs = decisions.active(kinds=["path_step", "finance", "bottlenecks"])
    pairs = {(d["tech_id"], d["fabric_id"]) for d in decs if d["kind"] in ("finance", "path_step")}
    techs = {t["_id"]: t for t in get_collection("technologies").find({"_id": {"$in": [t for t, _ in pairs]}},
                                                                      {"name": 1, "label": 1})}
    fabrics = {f["_id"]: f for f in get_collection("fabrics").find()}
    rows = []
    for tech_id, fabric_id in sorted(pairs):
        fig = finance.figures(tech_id, fabric_id, [d for d in decs if d["tech_id"] == tech_id], fabrics.get(fabric_id), path)
        nxt = fig["next_step"] or {}
        if not fig["asks"] or (missing and not (fig["missing"] or (nxt.get("needs") and not nxt["in_hand"]))):
            continue
        t = techs.get(tech_id, {})
        rows.append({"tech_id": tech_id, "name": t.get("label") or t.get("name") or tech_id, "fabric_id": fabric_id,
                     "fabric": (fabrics.get(fabric_id) or {}).get("name", fabric_id), **fig})
    return {"rows": rows, "path": sorted(path.values(), key=lambda s: s["order"]),
            "needs": {k: label for k, (label, _) in finance.NEEDS.items()}}


@router.get("/finance/{tech_id}/{fabric_id}")
def one(tech_id: str, fabric_id: str) -> dict:
    return finance.figures(tech_id, fabric_id)
