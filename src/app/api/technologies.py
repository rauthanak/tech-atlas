"""Technology endpoints (Phase B). The register is built by the resolver;
admin edits here (rename, alias moves, enable/disable) restamp documents
deterministically — no LLM involved — so corrections are cheap and safe."""

import json
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.analyzer.estimate import estimate
from agent.resolver import restamp, start_resolve
from app.services import decisions, evidence, jobs, latest_povs, pages, tech_status, watch
from app.services.db.mongo import get_collection
from app.services.settings_store import radar_settings
from app.services.timezone import now_utc, request_tz
from app.services.display import display_name

router = APIRouter()


STATES = Literal["new_evidence", "no_pov", "not_assessed", "stopped_partway", "assessing", "current", "off"]


# what each list filter reads in the stored answers (services/tech_status)
FILTER_FIELDS = {"availability": "f.availability", "domain": "f.domain", "subdomain": "f.subdomain",
                 "evidence": "f.evidence", "fabric": "f.fabrics", "catalog": "f.catalog"}


def _filter_match(f: dict, leave_out: tuple = ()) -> dict:
    """The list's filters as a query on the stored answers, without `leave_out`'s keys."""
    m: dict = {field: f[key] for key, field in FILTER_FIELDS.items() if f.get(key) and key not in leave_out}
    trl: dict = {}
    if f.get("trl_min") is not None and "trl_min" not in leave_out:
        trl["$gte"] = f["trl_min"]
    if f.get("trl_max") is not None and "trl_max" not in leave_out:
        trl["$lte"] = f["trl_max"]
    if trl:
        m["f.trl"] = {**trl, "$ne": None}
    return m


def _counts(asks: dict[str, tuple[dict, str, bool]]) -> dict[str, dict]:
    """For each ask (name: (match, field, unwind)), how many stored answers
    matching `match` hold each value of `field`. Asks with the same match are
    counted in one pass over the stored answers, not one pass each."""
    by_match: dict[str, dict] = {}
    for name, (match, field, unwind) in asks.items():
        key = json.dumps(match, sort_keys=True, default=str)
        by_match.setdefault(key, {"match": match, "facets": {}})["facets"][name] = [
            *([{"$unwind": f"${field}"}] if unwind else []), {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}]
    out: dict[str, dict] = {}
    for one in by_match.values():
        got = next(get_collection("tech_status").aggregate(
            [{"$match": one["match"]}, {"$facet": one["facets"]}], allowDiskUse=True))
        out.update({name: {r["_id"]: r["n"] for r in rows} for name, rows in got.items()})
    return out


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
    "select all in this view". Read from the answers kept ready for each
    technology (services/tech_status), so it costs the same at any size."""
    import re as _re
    from app.services import radar_status
    if view is not None and view not in radar_status.VIEWS:
        raise HTTPException(status_code=422, detail=f"unknown view {view!r}")
    tech_status.fresh()
    found = get_collection("tech_status")
    base: dict = {"search": _re.compile(_re.escape(q.strip().lower()))} if q.strip() else {}
    filters = {"availability": availability, "domain": domain, "subdomain": subdomain, "trl_min": trl_min,
               "trl_max": trl_max, "evidence": evidence_verdict, "fabric": fabric, "catalog": catalog}
    # the view, the Briefing's state and the status pill: everything but the filters
    scoped = {**base, **({"f.views": view} if view else {}), **({"f.state": state} if state else {})}
    shown = {**scoped, **({"f.status": status} if status else {})}
    filtered = {**shown, **_filter_match(filters)}
    order = ([("f.avail_order", 1), ("f.trl_sort", 1)] if view in radar_status.BY_AVAILABILITY
             else [("f.nascent_settled", 1)] if view == "nascent" else []) + [("doc_count", -1), ("_id", 1)]
    if ids_only:
        ids = [r["_id"] for r in found.find(filtered, {"_id": 1}).sort(order)]
        return {"ids": ids, "total": len(ids)}

    in_filters = {**base, **_filter_match(filters)}
    asks = {"views": (in_filters, "f.views", True), "status": ({**scoped, **_filter_match(filters)}, "f.status", False),
            "state": (base, "f.state", False), "no_priority": ({**base, "f.no_priority": True}, "f.state", False)}
    for facet, keys in radar_status.FACETS.items():
        if facet == "subdomain" and not domain:
            continue
        rest = {**shown, **_filter_match(filters, leave_out=keys)}
        asks[f"facet:{facet}"] = (rest, "f.trl" if facet == "trl" else FILTER_FIELDS[facet], facet == "fabric")
    counted_all = _counts(asks)
    views = counted_all["views"]
    view_counts = {"all": found.count_documents(in_filters), **{v: views.get(v, 0) for v in radar_status.VIEWS}}
    status_counts = counted_all["status"]
    facets: dict = {}
    for facet in radar_status.FACETS:
        if f"facet:{facet}" in counted_all:
            counted = counted_all[f"facet:{facet}"]
            facets[facet] = {("none" if k is None else k): n for k, n in counted.items()} if facet == "trl" else counted
    if "subdomain" in facets:
        counted = facets["subdomain"]
        if subdomain:
            counted.setdefault(subdomain, 0)  # the chosen one stays listed, even when nothing is left in it
        names = {r["f"]["subdomain"]: r["f"].get("subdomain_name")
                 for r in found.find({**shown, "f.subdomain": {"$in": list(counted)}}, {"f.subdomain": 1, "f.subdomain_name": 1})}
        facets["subdomain"] = sorted(({"id": i, "name": (names.get(i) or i) if i != "none" else "No sub-domain yet", "n": n}
                                      for i, n in counted.items()),
                                     key=lambda x: (x["id"] == "none", str(x["name"]).lower()))
    state_counts = counted_all["state"]
    no_priority = counted_all["no_priority"]

    total = found.count_documents(filtered)
    page = [r["_id"] for r in found.find(filtered, {"_id": 1}).sort(order).skip(max(0, skip)).limit(max(1, min(limit, 500)))]
    coll = get_collection("technologies")
    rows = {t["_id"]: t for t in coll.find({"_id": {"$in": page}}, {"classification": 0, "assessed_classification": 0,
                                                                    "pages_seen": 0, tech_status.DIRTY: 0})}
    st = {r["_id"]: r["row"] for r in get_collection("tech_status_rows").find({"_id": {"$in": page}}, {"row": 1})}
    povs = {i: {k: p.get(k) for k in ("scoring_run_id", "composed_at", "composed_tz")}
            for i, p in latest_povs.latest(page, ("scoring_run_id", "composed_at", "composed_tz")).items()}
    techs = [{**rows[i], **st[i], "pov": povs.get(i)} for i in page if i in rows and i in st]
    since = evidence.pages_since_off(techs)
    wake = radar_settings()["wake_after_pages"]
    for t in techs:
        if t["_id"] in since:
            t["pages_since_off"] = since[t["_id"]]
            t["wake"] = since[t["_id"]] >= wake
    last = get_collection("resolves").find_one(sort=[("started_at", -1)])
    flagged = {p for t in techs if (p := (t["classification"]["nascent"]["flag"] or {}).get("page"))}
    return {
        "technologies": techs,
        "total": total,
        "view_counts": view_counts,
        "status_counts": status_counts,
        "facets": facets,
        "cited_pages": _pages_of(flagged),  # the pages possible-nascent flags quote
        "state_counts": state_counts,
        "no_priority_counts": no_priority,
        # pages linked: the last merge's own count (last_resolve.docs_stamped), never a count over every page
        "summary": {"tech_count": coll.estimated_document_count()},
        "catalog": _catalog(),
        "last_resolve": last,
        "updating": tech_status.pending(),  # technologies whose answers are being worked out again
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
    pov = latest_povs.latest([tech_id], ("sections.headline", "scoring_run_id", "composed_tz", "version",
                                         "assessment_ids")).get(tech_id)
    since_pov = s["new_since_pov"]
    cost = estimate([tech_id])
    from app.services import editions, gates
    shown = editions.latest(full=False)  # leaders see only the latest edition
    return {
        "frontier": {"edition": editions.label(shown), "name": shown.get("name"), "published_at": shown["published_at"],
                     "tz": shown.get("tz"), "placed": bool(editions.rows(shown, "placed", tech_id=tech_id))} if shown else None,
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
        "technology": {"id": tech_id, "name": t["name"], "label": display_name(t)},
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
        "assessment": {**chosen, "watch_metrics": watch.apply(chosen.get("watch_metrics") or [], decs)},
        "measures": [{k: m.get(k) for k in ("_id", "code", "name", "axis", "scope", "definition", "required_evidence")}
                     for m in get_collection("measures").find()],
    }


@router.get("/technologies/{tech_id}/documents")
def technology_documents(tech_id: str, limit: int = 50, skip: int = 0,
                         sort: str = "scraped") -> dict:
    t = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1})
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown technology {tech_id!r}")
    # one row per page, its newest visit (services/pages), which says how many times the page was collected.
    # sort=published: newest published first; docs without a published date
    # sort below any dated ones (missing < value in Mongo), then by extraction
    order = [("published_date", -1), ("scraped_at", -1)] if sort == "published" else [("scraped_at", -1)]
    linked = {"technologies_resolved": t["name"], **pages.NEWEST}
    docs = [{**d, "copies": d.get("visits") or 1} for d in get_collection("documents").find(linked, {"content_hash": 0})
            .sort(order).skip(max(0, skip)).limit(max(1, min(limit, 500)))]
    total = get_collection("documents").count_documents(linked)  # counted in the index
    # not read by the latest assessment: worked out for the rows shown only
    new_versions = {evidence.version(d) for d in evidence.new_pages(t["name"], evidence.latest_reading(tech_id), docs)}
    for d in docs:
        d["new"] = evidence.version(d) in new_versions
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
    jobs.later(restamp, techs.find_one({"_id": tech_id}, {"aliases": 1})["aliases"])  # only the pages that name it
    tech_status.touch([tech_id], now=True)  # this one at once; the rest follow in the background
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
    names = _clean([display_name(t), *body.names])
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
    tech_status.touch(edit.ids, now=True)  # a few at once; many in the background
    return {"changed": done, "action": edit.action}


class MergeParams(BaseModel):
    others: list[str] = Field(min_length=1, max_length=50)


@router.post("/technologies/{tech_id}/merge")
def merge_technologies(tech_id: str, params: MergeParams) -> dict:
    """Merge whole technologies into this one — the user's judgment overriding
    the LLM's. Each entry in `others` is a tech id or exact name. The target's
    name survives; every alias of the absorbed technologies moves over, and so
    do the choices people made on them (where the target has its own choice on
    the same thing, the target's is kept and the merge says so) and catalog
    membership; the absorbed entries are deleted, and all documents restamp.
    History stays where it was: assessments, Points of View and editions keep
    the absorbed ids."""
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
    merged = _carry_over(tech_id, absorbed)  # before the delete, so running it again after a stop is safe
    aliases = sorted({a for o in absorbed for a in o.get("aliases", [])}
                     | {o["name"] for o in absorbed})
    techs.update_one({"_id": tech_id},
                     {"$addToSet": {"aliases": {"$each": aliases}},
                      "$set": {"updated_at": now_utc()}})
    techs.delete_many({"_id": {"$in": [o["_id"] for o in absorbed]}})
    jobs.later(restamp, techs.find_one({"_id": tech_id}, {"aliases": 1})["aliases"])  # the pages that name it or what it took in
    tech_status.touch([tech_id, *(o["_id"] for o in absorbed)], now=True)  # the absorbed lose their rows
    return {**get_collection("technologies").find_one({"_id": tech_id}), "merge": merged}


def _same_thing(d: dict) -> tuple:
    return d["kind"], d.get("fabric_id"), d.get("measure_id"), d.get("field"), d.get("key")


def _carry_over(tech_id: str, absorbed: list[dict]) -> dict:
    """The absorbed technologies' choices in force move to the target, one
    technology after another, unless the target already has one on the same
    thing: then the target's is kept and the other is replaced. Catalog
    membership moves when the target has none. What moved, in plain words."""
    from app.api.decisions import described
    coll, techs = get_collection("decisions"), get_collection("technologies")
    moved, conflicts, carried = 0, [], False
    for o in absorbed:
        theirs = {_same_thing(d): d for d in decisions.active([tech_id])}
        mine = decisions.active([o["_id"]])
        clash = [d for d in mine if _same_thing(d) in theirs]
        if clash:
            coll.update_many({"_id": {"$in": [d["_id"] for d in clash]}},
                             {"$set": {"active": False, "replaced_at": now_utc()}})
        coll.update_many({"_id": {"$in": [d["_id"] for d in mine]}}, {"$set": {"tech_id": tech_id, "merged_from": o["_id"]}})
        moved += len(mine) - len(clash)
        for d in clash:
            kept, dropped = described([theirs[_same_thing(d)], d])
            conflicts.append({"kept": kept["what"], "dropped": dropped["what"], "from": o["name"]})
        target = techs.find_one({"_id": tech_id}, {"imported": 1, "origin": 1}) or {}
        catalog = {f: o[f] for f in ("imported", "origin") if o.get(f) and not target.get(f)}
        if catalog:
            techs.update_one({"_id": tech_id}, {"$set": catalog})
            carried = True
    return {"absorbed": [{"id": o["_id"], "name": o["name"]} for o in absorbed], "choices_moved": moved,
            "catalog_carried": carried, "conflicts": conflicts}


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
    jobs.later(restamp, [move.alias])  # the pages that use that name: they move here from wherever they were
    tech_status.touch([tech_id], now=True)
    return get_collection("technologies").find_one({"_id": tech_id})
