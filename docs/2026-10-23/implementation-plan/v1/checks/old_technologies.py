"""Technology endpoints (Phase B). The register is built by the resolver;
admin edits here (rename, alias moves, enable/disable) restamp documents
deterministically — no LLM involved — so corrections are cheap and safe."""

from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.analyzer.estimate import estimate
from agent.resolver import restamp_all, start_resolve
from app.services import decisions, evidence
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import now_utc, request_tz

router = APIRouter()


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
def list_technologies(q: str = "", state: STATES | None = None, view: str | None = None,
                      status: str | None = None, availability: str | None = None, domain: str | None = None,
                      subdomain: str | None = None, trl_min: int | None = None, trl_max: int | None = None,
                      evidence_verdict: str | None = None, fabric: str | None = None,
                      catalog: Literal["yes", "no"] | None = None, ids_only: bool = False,
                      limit: int = 100, skip: int = 0) -> dict:
    """The register, most pages first (a view over commercial availability:
    earliest values first). Each row has one status with its reason
    (services/radar_status), its notes, its classification (each answer with
    where it came from), what its assessment came to and its newest Point of
    View. Filters and the view apply before paging. Each set of counts leaves
    out only its own choice: `view_counts` cover the search and filters;
    `status_counts` the view and filters too; `facets` (per filter value)
    everything but that filter. `ids_only` answers with every row's id, for
    "select all in this view"."""
    import re as _re
    from app.services import radar_status
    coll = get_collection("technologies")
    query: dict = {}
    if q.strip():
        rx = _re.compile(_re.escape(q.strip().lower()))
        query = {"$or": [{"name": rx}, {"aliases": rx}, {"label": _re.compile(_re.escape(q.strip()), _re.I)}]}
    if view is not None and view not in radar_status.VIEWS:
        raise HTTPException(status_code=422, detail=f"unknown view {view!r}")
    ids = [t["_id"] for t in coll.find(query, {"_id": 1}).sort([("doc_count", -1), ("_id", 1)])]
    st = radar_status.statuses(ids)
    ids = [i for i in ids if i in st]
    filters = {"availability": availability, "domain": domain, "subdomain": subdomain, "trl_min": trl_min,
               "trl_max": trl_max, "evidence": evidence_verdict, "fabric": fabric, "catalog": catalog}
    # the view, the Briefing's state and the status pill: everything but the filters
    scoped = [i for i in ids if (not view or radar_status.in_view(view, st[i])) and (not state or st[i]["state"] == state)]
    shown = [i for i in scoped if not status or st[i]["status"] == status]
    filtered = [i for i in shown if radar_status.matches(st[i], filters)]
    filtered = radar_status.ordered(view, filtered, st)
    if ids_only:
        return {"ids": filtered, "total": len(filtered)}
    in_filters = [i for i in ids if radar_status.matches(st[i], filters)]
    view_counts = {"all": len(in_filters), **{v: sum(radar_status.in_view(v, st[i]) for i in in_filters)
                                              for v in radar_status.VIEWS}}
    status_counts = Counter(st[i]["status"] for i in scoped if radar_status.matches(st[i], filters))
    facets = radar_status.facets([st[i] for i in shown], filters)
    state_counts = Counter(st[i]["state"] for i in ids)
    no_priority = Counter(st[i]["state"] for i in ids
                          if st[i]["priorities"] and not any(p["priority"] for p in st[i]["priorities"]))
    over_floor = _over_floor(ids, {i: {"state": st[i]["state"], "new_pages": st[i]["new_pages"]} for i in st})
    start = max(0, skip)
    page = filtered[start:start + max(1, min(limit, 500))]
    rows = {t["_id"]: t for t in coll.find({"_id": {"$in": page}}, {"classification": 0, "assessed_classification": 0,
                                                                    "pages_seen": 0})}
    povs = {p["_id"]: {"scoring_run_id": p["scoring_run_id"], "composed_at": p["composed_at"],
                       "composed_tz": p.get("composed_tz")}
            for p in get_collection("povs").aggregate([
                {"$match": {"tech_id": {"$in": page}}}, {"$sort": {"composed_at": -1}},
                {"$group": {"_id": "$tech_id", "scoring_run_id": {"$first": "$scoring_run_id"},
                            "composed_at": {"$first": "$composed_at"},
                            "composed_tz": {"$first": "$composed_tz"}}}])}
    techs = [{**rows[i], **st[i], "pov": povs.get(i)} for i in page if i in rows]
    since = evidence.pages_since_off(techs)
    wake = radar_settings()["wake_after_pages"]
    for t in techs:
        if t["_id"] in since:
            t["pages_since_off"] = since[t["_id"]]
            t["wake"] = since[t["_id"]] >= wake
    total = len(filtered)
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
    flagged = {p for t in techs if (p := (t["classification"]["nascent"]["flag"] or {}).get("page"))}
    return {
        "technologies": techs,
        "total": total,
        "view_counts": view_counts,
        "status_counts": dict(status_counts),
        "facets": facets,
        "cited_pages": _pages_of(flagged),  # the pages possible-nascent flags quote
        "state_counts": dict(state_counts),
        "no_priority_counts": dict(no_priority),
        "over_floor": over_floor,
        "summary": {"tech_count": coll.estimated_document_count(),
                    "tagged_docs": tagged,
                    "kinds": kinds, "horizons": horizons},
        "catalog": _catalog(),
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
        {"tech_id": tech_id}, {"sections.headline": 1, "scoring_run_id": 1, "composed_at": 1, "composed_tz": 1,
                               "version": 1, "assessment_ids": 1}, sort=[("composed_at", -1)])
    since_pov = None
    if pov:
        read = evidence.reading(list(get_collection("assessments").find(
            {"_id": {"$in": pov.get("assessment_ids") or []}}, {"measures": 0, "watch_metrics": 0})))
        since_pov = len(evidence.new_pages(t["name"], read)) if read else None
    cost = estimate([tech_id])
    from app.services import editions, gates
    shown = editions.latest(full=False)  # leaders see only the latest edition
    return {
        "frontier": {"edition": editions.label(shown), "name": shown.get("name"), "published_at": shown["published_at"],
                     "tz": shown.get("tz"), "placed": get_collection("editions").count_documents(
            {"_id": shown["_id"], "placed.tech_id": tech_id}) > 0} if shown else None,
        "technology": {"id": t["_id"], "name": t["name"], "aliases": t.get("aliases", []),
                       "enabled": t.get("enabled", True), "page_count": t.get("page_count", 0),
                       "source_count": t.get("source_count", 0),
                       "switched_off_at": t.get("switched_off_at"), "switched_off_tz": t.get("switched_off_tz"),
                       # in Tata's catalog by an import: the file, when it was imported, and the row's description
                       "imported": {"file": imp.get("file"), "at": imp.get("at"), "tz": imp.get("tz"),
                                    "description": (imp.get("row") or {}).get("description")}
                       if (imp := t.get("imported")) else None,
                       "catalog": decisions.in_catalog(t, decisions.pick(decisions.active([tech_id], ["catalog"]), "catalog")),
                       # the names it's looked for by on pages (agent/tagger), who set them, and what came of it
                       "look_for": t.get("look_for") or [], "look_for_by": t.get("look_for_by"),
                       "not_a_technology": t.get("not_a_technology"),
                       "mentions": get_collection("documents").count_documents({"mentions": t["name"], "ignored_by": None}),
                       **({"pages_since_off": n, "wake": n >= radar_settings()["wake_after_pages"]}
                          if (n := evidence.pages_since_off([t]).get(t["_id"])) is not None else {})},
        "state": s["state"],
        "assessment": {k: a[k] for k in ("scoring_run_id", "run_status", "assessed_at", "pages_read",
                                         "evidence_runs", "measures", "fabrics", "not_assessed_in")} if a else None,
        "unfinished": s["unfinished"],
        "pov": {"id": pov["_id"], "scoring_run_id": pov["scoring_run_id"],
                "composed_at": pov["composed_at"], "composed_tz": pov.get("composed_tz"),
                "version": pov.get("version"),
                "headline": (pov.get("sections") or {}).get("headline"),
                "from_latest_assessment": bool(a) and pov["scoring_run_id"] == a["scoring_run_id"]}
        if pov else None,
        "new_pages": {"since_assessment": len(s["new"]), "since_pov": since_pov,
                      "recent": [evidence.page(d) for d in s["new"][:5]]},
        "estimate": {"assess_calls": cost["calls"], "assess_calls_max": cost["calls_max"],
                     "write_calls": 1},
        # what's still open in each fabric, for "Waiting on you" (services/gates)
        "open": gates.open_for(tech_id) if a else [],
        **_classification(tech_id),
    }


def _catalog() -> dict:
    """Where Tata's catalog came from, for the list's note: each confirmed
    import's file that still holds technologies, when, and how many (a
    reopened row no longer counts); how many earlier imports hold none now;
    and how many a person added or took out."""
    techs = get_collection("technologies")
    files = [{"file": i.get("file"), "at": i["confirmed_at"], "tz": i.get("tz"),
              "technologies": techs.count_documents({"imported.import_id": i["_id"]})}
             for i in get_collection("imports").find({"confirmed_at": {"$exists": True}, "status": {"$ne": "discarded"}},
                                                     {"file": 1, "confirmed_at": 1, "tz": 1}).sort("confirmed_at", -1)]
    by_person = Counter(d["value"] for d in decisions.active(kinds=["catalog"]))
    # an import whose rows all moved to a later one (the same file imported again) holds none now
    return {"files": [f for f in files if f["technologies"]], "emptied": sum(1 for f in files if not f["technologies"]),
            "added": by_person["yes"], "taken_out": by_person["no"]}


def _pages_of(ids: set[str]) -> dict:
    """Page details for "Why?" links: title, address, source and date."""
    names = evidence.source_names()
    return {d["_id"]: {"title": d.get("title"), "url": d.get("end_url"),
                       "source": d.get("source_name") or names.get(d.get("source_id"), d.get("source_id")),
                       "date": d.get("published_date") or str(d.get("scraped_at") or "")[:10]}
            for d in get_collection("documents").find({"_id": {"$in": list(ids)}},
                                                      {"title": 1, "end_url": 1, "source_name": 1, "source_id": 1,
                                                       "published_date": 1, "scraped_at": 1})}


def _classification(tech_id: str) -> dict:
    """Its status and classification (services/radar_status), and the pages
    the answers cite, so "Why?" can link them."""
    from app.services import radar_status
    s = radar_status.statuses([tech_id]).get(tech_id)
    if s is None:
        return {}
    cls = s["classification"]
    ids = {p for k in ("availability", "domain", "trl")
           for p in [*(cls[k].get("pages") or []), *((cls[k].get("radar") or {}).get("pages") or [])]}
    ids |= set((cls["evidence"] or {}).get("pages") or [])
    if (cls["nascent"]["flag"] or {}).get("page"):
        ids.add(cls["nascent"]["flag"]["page"])
    return {"status": {k: s[k] for k in ("status", "reason", "notes")}, "classification": cls, "cited_pages": _pages_of(ids)}


@router.get("/technologies/{tech_id}/assessment")
def technology_assessment(tech_id: str, fabric: str | None = None) -> dict:
    """The technology's latest assessment in one fabric (default: its best
    placed), with people's choices applied (services/effective): each
    measure's state, the priority with any override, and the other fabrics
    to switch to."""
    from app.services import gates
    t = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1, "label": 1})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    fabrics = gates.latest_applied([tech_id]).get(tech_id, [])
    if not fabrics:
        raise HTTPException(status_code=404, detail=f"{t.get('label') or t['name']} hasn't been assessed yet")
    order = sorted(fabrics, key=lambda f: (f["effective"]["priority"] or "P9", f["fabric_id"]))
    chosen = next((f for f in fabrics if f["fabric_id"] == fabric), order[0])
    from app.services import decisions as decision_store
    from app.services import effective as eff
    from app.services import finance
    decs = decision_store.active([tech_id])
    path = finance.steps()
    return {
        "technology": {"id": tech_id, "name": t["name"], "label": t.get("label") or t["name"]},
        "fabric": chosen["fabric_id"],
        "finance": finance.figures(tech_id, chosen["fabric_id"], decs, None, path),
        "path": sorted(path.values(), key=lambda p: p["order"]),
        "use_case_decisions": {d["key"]: {k: d.get(k) for k in ("_id", "value", "at", "tz")}
                               for d in decs if d["kind"] == "use_case" and d.get("fabric_id") == chosen["fabric_id"]},
        "cited_pages": _pages_of({p for uc in chosen.get("use_cases") or []
                                  for p in [*(uc.get("pages") or []), *(q for lv in uc.get("levers") or [] for q in lv.get("pages") or [])]}
                                 | {b["page"] for b in chosen.get("suggested_bottlenecks") or []}),
        "fabrics": [{"fabric_id": f["fabric_id"], "fabric": f["fabric"], "priority": f["effective"]["priority"],
                     "computed_priority": f["effective"]["computed_priority"],
                     "override": bool(f["effective"]["override"]), "states": eff.counts(f)} for f in fabrics],
        "assessment": chosen,
        "measures": [{k: m.get(k) for k in ("_id", "code", "name", "axis", "scope", "definition", "required_evidence")}
                     for m in get_collection("measures").find()],
    }


@router.get("/technologies/{tech_id}/documents")
def technology_documents(tech_id: str, limit: int = 50, skip: int = 0,
                         sort: str = "scraped") -> dict:
    t = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    match = {"technologies_resolved": t["name"]}
    docs_coll = get_collection("documents")
    # one row per page, its newest copy: a page collected again (it changed)
    # counts once, as page_count does, and says how many times it was collected
    total = len(docs_coll.distinct("end_url", match))
    # sort=published: newest published first; docs without a published date
    # sort below any dated ones (missing < value in Mongo), then by extraction
    order = {"published_date": -1, "scraped_at": -1} if sort == "published" else {"scraped_at": -1}
    docs = [{**g["doc"], "copies": g["copies"]} for g in docs_coll.aggregate([
        {"$match": match}, {"$project": {"extracted_text": 0}}, {"$sort": {"scraped_at": -1}},
        {"$group": {"_id": "$end_url", "doc": {"$first": "$$ROOT"}, "copies": {"$sum": 1}}},
        {"$sort": {f"doc.{k}": v for k, v in order.items()}},
        {"$skip": max(0, skip)}, {"$limit": max(1, min(limit, 500))}])]
    new_versions = {evidence.version(d) for d in evidence.state(tech_id)["new"]}
    for d in docs:
        d["new"] = evidence.version(d) in new_versions  # not read by the latest assessment
        d["id"] = str(d.pop("_id"))
    return {"name": t["name"], "documents": docs, "total": total}


class TechEdit(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool


def _switch(enabled: bool, tz: str) -> dict:
    """The update that switches technologies on or off: switching off records
    when and in which zone; switching on clears it."""
    if enabled:
        return {"$set": {"enabled": True, "updated_at": now_utc()},
                "$unset": {"switched_off_at": "", "switched_off_tz": ""}}
    return {"$set": {"enabled": False, "switched_off_at": now_utc(), "switched_off_tz": tz, "updated_at": now_utc()}}


@router.put("/technologies/{tech_id}")
def update_technology(tech_id: str, edit: TechEdit, tz: str = Depends(request_tz)) -> dict:
    techs = get_collection("technologies")
    name = edit.name.strip().lower()
    clash = techs.find_one({"name": name, "_id": {"$ne": tech_id}}, {"_id": 1})
    if clash:
        raise HTTPException(status_code=422,
                            detail=f"another technology already uses the name {name!r}"
                                   " — move its aliases instead")
    current = techs.find_one({"_id": tech_id}, {"name": 1, "enabled": 1})
    if current is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    if edit.enabled != current.get("enabled", True):
        techs.update_one({"_id": tech_id}, _switch(edit.enabled, tz))
    update: dict = {"$set": {"name": name, "updated_at": now_utc()},
                    "$addToSet": {"aliases": name}}
    typed = edit.name.strip()
    if typed != name:                 # typed with capitals: that's how it's shown
        update["$set"]["label"] = typed
    elif name != current["name"]:     # renamed in lowercase: the next organize labels it
        update["$unset"] = {"label": ""}
    techs.update_one({"_id": tech_id}, update)
    restamp_all()
    return get_collection("technologies").find_one({"_id": tech_id})


class LookFor(BaseModel):
    names: list[str] = Field(max_length=12)


@router.put("/technologies/{tech_id}/look-for")
def set_look_for(tech_id: str, body: LookFor, tz: str = Depends(request_tz)) -> dict:
    """The names a person wants it looked for by on pages: the next collection
    (or a catch-up on Operations) looks for them."""
    from agent.tagger.tagger import _clean
    t = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1, "label": 1})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    names = _clean([t.get("label") or t["name"], *body.names])
    get_collection("technologies").update_one({"_id": tech_id}, {"$set": {
        "look_for": names, "look_for_by": "person", "look_for_at": now_utc(), "look_for_tz": tz}})
    return {"look_for": names}


class BulkEdit(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["switch_off", "switch_on"]


@router.post("/technologies/bulk")
def bulk_edit(edit: BulkEdit, tz: str = Depends(request_tz)) -> dict:
    """Switch many technologies off or on at once, from the list. Only those
    not already in that state change, so an earlier switch-off keeps its time."""
    on = edit.action == "switch_on"
    done = get_collection("technologies").update_many(
        {"_id": {"$in": edit.ids}, "enabled": {"$ne": on}}, _switch(on, tz)).modified_count
    return {"changed": done, "action": edit.action}


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
                      "$set": {"updated_at": now_utc()}})
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
                      "$set": {"updated_at": now_utc()}})
    restamp_all()
    return get_collection("technologies").find_one({"_id": tech_id})
