"""Each technology's answers, kept ready (plan 10, §11 rule 1): its status,
state, classification, priorities, what waits on it, and the few values the
lists filter and count by, in one record per technology (`tech_status`).
Screens read these records through indexes, 50 at a time, so they stay fast
however many technologies and pages there are; nothing works out every
technology while someone waits. Two collections, so counting stays light:
`tech_status`, small, with what the lists filter, count and sort by; and
`tech_status_rows`, with the full row and what waits on it, read only for
the rows shown.

The answers come from the same rules as before (services/radar_status,
evidence, gates), applied to a few hundred technologies at a time. They are
kept up to date three ways:

  - a person's own action (a move, Undo, switching one off) updates that
    technology at once (`touch(..., now=True)`), so the screen is right on reload;
  - writes elsewhere mark what they changed (`touch`, `touch_all`), and a
    background updater, every few seconds, also picks up what changed by
    time: new pages, assessments, Points of View, choices, assessment runs;
  - as a safety net, when nothing waits, the records not worked out for 30
    minutes are, oldest first, a batch at a time (nothing is marked all at
    once, so at any size this only fills the quiet time).

A record says when it was worked out (`at`); `pending()` says how many wait."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from pymongo import ReplaceOne

from app.services import latest_povs, pages
from app.services.db.mongo import get_collection
from app.services.display import display_name

log = logging.getLogger(__name__)

VERSION = 4            # bump when a record's shape changes: start-up then rebuilds them all
BATCH = 500            # technologies worked out together, at most
BATCH_PAGES = 50_000   # and their newest pages, at most: a batch of big technologies is split, so memory stays small
LOOP_S = 3             # the updater's pace
SWEEP_S = 30 * 60      # the safety net: a record not worked out this long is, when nothing waits
INLINE_MAX = 50        # a person's action on up to this many is updated at once
DIRTY = "status_dirty_at"  # on a technology: its record waits to be worked out again

_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()   # one batch at a time


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── marking what changed ─────────────────────────────────────────────

def touch(tech_ids, now: bool = False) -> None:
    """These technologies' answers changed. `now`: a person is waiting on
    the screen, so a few are worked out at once; otherwise the updater does."""
    ids = sorted({i for i in tech_ids if i})
    if not ids:
        return
    if now and len(ids) <= INLINE_MAX:
        try:
            refresh(ids)
            return
        except Exception:  # the updater tries again; the action itself stands
            log.exception("tech status: couldn't update %s at once", ids[:5])
    get_collection("technologies").update_many({"_id": {"$in": ids}}, {"$set": {DIRTY: _now()}})


def touch_names(names) -> None:
    """The technologies with these names (pages store names, not ids)."""
    names = sorted({n for n in names if n})
    if names:
        touch(get_collection("technologies").distinct("_id", {"name": {"$in": names}}))


def touch_all() -> None:
    """Every technology: a change that can move any of them (a setting, a
    list, pages linked again). The updater works through them in batches."""
    get_collection("technologies").update_many({}, {"$set": {DIRTY: _now()}})


RUN_MAX = 2000  # technologies in one assessment run: its record stays well inside MongoDB's 16 MB (about 150 bytes each)
SETS = {  # what the lists offer to assess, in the order a run takes them
    "new_evidence": ({"f.state": "new_evidence"}, [("f.new_pages", -1), ("_id", 1)]),
    "ready": ({"f.status": "ready"}, [("doc_count", -1), ("_id", 1)]),
}


def chosen(kind: str) -> list[str]:
    """The technologies of an offered set (SETS), in the order a run takes them: most pages first."""
    match, order = SETS[kind]
    return [r["_id"] for r in get_collection("tech_status").find(match, {"_id": 1}).sort(order)]


def offer(kind: str) -> dict | None:
    """What assessing an offered set costs, for the lists (never its ids: a set grows with the radar).
    Over RUN_MAX, `run` says what one run takes: the first RUN_MAX, and their model calls."""
    from agent.analyzer.estimate import estimate
    ids = chosen(kind)
    if not ids:
        return None
    cost = estimate(ids)
    return {"count": len(ids), "calls": cost["calls"], "calls_max": cost["calls_max"],
            **({"run": {"count": RUN_MAX, "calls": estimate(ids[:RUN_MAX])["calls"]}} if len(ids) > RUN_MAX else {})}


def latest_assessments() -> list[str]:
    """The rows of every technology's latest assessment (their ids), read off the
    answers kept ready: what a publish freezes, without reading any page."""
    fresh()
    by_run: dict[str, list[str]] = {}
    for r in get_collection("tech_status_rows").find({"target": {"$ne": None}}, {"target.scoring_run_id": 1}):
        by_run.setdefault(r["target"]["scoring_run_id"], []).append(r["_id"])
    return [a["_id"] for run, ids in by_run.items()
            for a in get_collection("assessments").find({"scoring_run_id": run, "tech_id": {"$in": ids}}, {"_id": 1})]


def pending() -> int:
    """How many technologies wait to be worked out again."""
    return get_collection("technologies").count_documents({DIRTY: {"$exists": True}})


ALWAYS_FRESH = False   # work out every technology on each read: the tests' mode, where nothing runs in the background
FRESH_MAX = 200        # a reader works out at most this many waiting ones itself; more are left to the updater


def fresh() -> None:
    """Before a screen reads the stored answers: the few still waiting (a
    person's action, a job that just ended) are worked out first, so small
    changes show at once; a large recount stays with the updater."""
    if ALWAYS_FRESH:
        refresh(get_collection("technologies").distinct("_id"))
        return
    if 0 < pending() <= FRESH_MAX:
        step()


# ── working the answers out ──────────────────────────────────────────

TECH_FIELDS = {"name": 1, "label": 1, "aliases": 1, "doc_count": 1, "page_count": 1, "enabled": 1,
               "classification.at": 1, "classification_stale": 1, "pages_seen": 1, "imported": 1, "origin": 1}


def _classify_waiting(techs: list[dict], catalog: dict) -> dict[str, tuple]:
    """Which of these technologies Classify would judge (agent/classifier
    pending(): switched on, with pages, and a page version its last
    classification didn't know, or marked for review), with its place in
    Classify's order: catalog first, then most pages."""
    from app.services import decisions
    names = [t["name"] for t in techs]
    versions: dict[str, set] = {}
    version = {"$cond": [{"$and": ["$is_stub", "$ref_doc_id"]}, "$ref_doc_id", "$_id"]}  # evidence.version
    for row in get_collection("documents").aggregate([  # each page's newest version, as Classify reads them
            {"$match": {"technologies_resolved": {"$in": names}, **pages.NEWEST, "ignored_by": None}},
            {"$unwind": "$technologies_resolved"},
            {"$match": {"technologies_resolved": {"$in": names}}},
            {"$group": {"_id": "$technologies_resolved", "v": {"$addToSet": version}}}]):
        versions[row["_id"]] = set(row["v"])
    out = {}
    for t in techs:
        have = versions.get(t["name"])
        if t.get("enabled") is False or not have:
            continue
        if not t.get("classification") or t.get("classification_stale") or have - set(t.get("pages_seen") or []):
            out[t["_id"]] = (int(not decisions.in_catalog(t, catalog.get(t["_id"]))["in"]), -len(have))
    return out


def _pov_fields(t: dict, pov: dict | None) -> dict:
    """What the Points of View list filters and sorts a technology's newest one by."""
    if not pov:
        return {"pov_at": None}
    prios = [pl["priority"] or "none" for pl in pov["placements"]]
    label = (t.get("label") or t["name"]).lower()
    return {"pov_at": pov["composed_at"], "pov_label": label,
            "pov_search": f"{label} {((pov.get('sections') or {}).get('headline') or '').lower()}",
            "pov_fabrics": sorted({pl["fabric_id"] for pl in pov["placements"]}),
            "pov_prios": sorted(set(prios)), "pov_prio": sorted({f"{pl['fabric_id']}:{p}" for pl, p in zip(pov["placements"], prios)}),
            "pov_best": min((p for p in prios if p != "none"), default="P9")}


def _record(t: dict, s: dict, state: dict | None, waiting, gate2: list, order: dict,
            pov: dict | None = None) -> tuple[dict, dict]:
    """(the small record the lists count by, the full row and what waits on it)."""
    from app.services import radar_status
    cls = s["classification"]
    views = [v for v in radar_status.VIEWS if radar_status.in_view(v, s)]
    a = (state or {}).get("assessment")
    small = {
        "_id": t["_id"], "v": VERSION, "at": _now(),
        "name": t["name"], "label": t.get("label"), "doc_count": t.get("doc_count") or 0,
        # name, other names and label, one per line: a search never matches across two
        "search": "\n".join([t["name"], *(t.get("aliases") or []), (t.get("label") or "").lower()]),
        "f": {  # what the lists filter, count and sort by
            "status": s["status"], "state": s["state"], "views": views,
            "availability": cls["availability"]["id"], "domain": cls["domain"]["id"],
            "subdomain": cls["domain"]["subdomain_id"] or "none",
            "subdomain_name": cls["domain"]["subdomain"],
            "trl": cls["trl"]["level"], "evidence": (cls["evidence"] or {}).get("verdict") or "none",
            "fabrics": sorted({p["fabric_id"] for p in s["priorities"]}),
            "catalog": "yes" if s["catalog"]["in"] else "no",
            "no_priority": bool(s["priorities"]) and not any(p["priority"] for p in s["priorities"]),
            "new_pages": s["new_pages"],
            "new_since_pov": (state or {}).get("new_since_pov"),  # pages new since its newest Point of View
            **_pov_fields(t, pov),
            "avail_order": order.get(cls["availability"]["id"], 99), "trl_sort": cls["trl"]["level"] or 10,
            "nascent_settled": cls["nascent"]["decision"] is not None,
            "nascent_open": s["status"] != "off" and bool(cls["nascent"]["flag"]) and cls["nascent"]["decision"] is None,
            "classify_waiting": waiting is not None,
            "classify_order": list(waiting) if waiting else None,
        },
    }
    return small, {
        "_id": t["_id"],
        "row": s,  # the Technologies list's row, as services/radar_status.statuses gives it
        "nascent_note": (cls["nascent"]["flag"] or {}).get("reason"),
        # what the status pill, Points of View and Write need
        "unfinished": (state or {}).get("unfinished"),
        "target": {"scoring_run_id": a["scoring_run_id"], "tech_id": t["_id"], "technology": t["name"],
                   "assessed_at": a["assessed_at"]} if a else None,
        "gate2": gate2,
        "pov": pov,  # its row in the Points of View list (services/latest_povs.list_rows)
    }


def _batches(tech_ids: list[str]):
    """These technologies in batches of at most BATCH, holding at most BATCH_PAGES pages between them."""
    pages = {t["_id"]: t.get("page_count") or 0
             for t in get_collection("technologies").find({"_id": {"$in": tech_ids}}, {"page_count": 1})}
    batch, held = [], 0
    for i in tech_ids:
        if batch and (len(batch) == BATCH or held + pages.get(i, 0) > BATCH_PAGES):
            yield batch
            batch, held = [], 0
        batch.append(i)
        held += pages.get(i, 0)
    if batch:
        yield batch


def refresh(tech_ids: list[str]) -> int:
    """Work out and store these technologies' answers; a technology no
    longer in the register loses its record. Returns how many were stored."""
    from app.services import decisions, evidence, gates, radar_status
    stored = 0
    with _lock:
        for ids in _batches(tech_ids):
            techs = list(get_collection("technologies").find({"_id": {"$in": ids}}, TECH_FIELDS))
            found = [t["_id"] for t in techs]
            gone = sorted(set(ids) - set(found))
            if gone:
                get_collection("tech_status").delete_many({"_id": {"$in": gone}})
                get_collection("tech_status_rows").delete_many({"_id": {"$in": gone}})
            if not techs:
                continue
            included = set().union(*(r["tech_ids"] for r in evidence.runs()))
            full = evidence.states([t for t in found if t in included])
            st = radar_status.statuses(found, full)
            by_kind: dict[str, list] = {}
            for item in gates.gate2(all_states=full):
                for row in item["technologies"]:
                    by_kind.setdefault(row["tech_id"], []).append({"kind": item["kind"], "row": row})
            catalog = {d["tech_id"]: d for d in decisions.active(found, ["catalog"])}
            waiting = _classify_waiting(techs, catalog)
            order = {a["_id"]: a.get("order", 50) for a in get_collection("availability").find({}, {"order": 1})}
            povs = latest_povs.list_rows(found, {i: (full.get(i) or {}).get("new_since_pov") for i in found})
            records = [_record(t, st[t["_id"]], full.get(t["_id"]), waiting.get(t["_id"]),
                               by_kind.get(t["_id"], []), order, povs.get(t["_id"])) for t in techs if t["_id"] in st]
            if records:
                # the full row first: a small record is never there without its row
                get_collection("tech_status_rows").bulk_write(
                    [ReplaceOne({"_id": big["_id"]}, big, upsert=True) for _, big in records], ordered=False)
                get_collection("tech_status").bulk_write(
                    [ReplaceOne({"_id": small["_id"]}, small, upsert=True) for small, _ in records], ordered=False)
                stored += len(records)
    return stored


# ── the updater ──────────────────────────────────────────────────────

def _changed_since(since: str) -> set[str]:
    """Technologies whose answers changed after `since`, by the times the
    records themselves carry: new pages, assessments, Points of View, people's
    choices (made, replaced or undone) and assessment runs started or ended."""
    ids: set[str] = set()
    after = {"$gt": since}
    names = get_collection("documents").distinct(
        "technologies_resolved", {"is_stub": {"$in": [True, False]}, "scraped_at": after})
    if names:
        ids |= set(get_collection("technologies").distinct("_id", {"name": {"$in": names}}))
    ids |= set(get_collection("assessments").distinct("tech_id", {"created_at": after}))
    ids |= set(get_collection("povs").distinct("tech_id", {"composed_at": after}))
    ids |= set(get_collection("decisions").distinct(
        "tech_id", {"$or": [{"at": after}, {"undone_at": after}, {"replaced_at": after}]}))
    for run in get_collection("scoring_runs").find(
            {"$or": [{"started_at": after}, {"finished_at": after}]}, {"technologies.tech_id": 1}):
        ids |= {t["tech_id"] for t in run.get("technologies") or []}
    return ids


def step() -> int:
    """One pass of the updater: mark what changed by time, then work out one
    batch of what waits. Returns how many were worked out."""
    started = _now()
    claimed = [t["_id"] for t in get_collection("technologies").find({DIRTY: {"$exists": True}}, {"_id": 1})
               .sort(DIRTY, 1).limit(BATCH)]
    if not claimed:
        return 0
    done = refresh(claimed)
    # marked again while it was worked out: leave it marked for the next pass
    get_collection("technologies").update_many({"_id": {"$in": claimed}, DIRTY: {"$lte": started}},
                                               {"$unset": {DIRTY: ""}})
    return done


def sweep() -> int:
    """The safety net, when nothing waits: one batch of the records not worked out for SWEEP_S, oldest first."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=SWEEP_S)).isoformat()
    return refresh([r["_id"] for r in get_collection("tech_status").find({"at": {"$lt": old}}, {"_id": 1})
                    .sort("at", 1).limit(BATCH)])


def _run() -> None:
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    while not _stop.wait(LOOP_S):
        try:
            mark = _now()
            touch(_changed_since(since))
            since = mark
            while step() and not _stop.is_set():
                pass
            sweep()  # one batch, then back to what changed
        except Exception:  # the next pass tries again; screens keep the answers they have
            log.exception("tech status: the updater's pass failed")


def start() -> None:
    """Start the updater (start-up). A database with no records, or records of
    an older shape, has every technology worked out again, in the background."""
    global _thread
    first = get_collection("tech_status").find_one({}, {"v": 1})
    if first is None or first.get("v") != VERSION:
        touch_all()
    _stop.clear()
    _thread = threading.Thread(target=_run, name="tech-status", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


# ── the To do lists, read from the stored answers ───────────────────

LISTED = 50  # names a To do item carries; it says how many in all, and links to the full list
GATE2_KINDS = ("unscored", "waiting_for_tata", "override_moved", "maturity_mismatch", "suggested_use_cases",
               "finance_missing", "ready_next_step")


def _name(r: dict) -> str:
    return display_name(r)


def gate1() -> list[dict]:
    """Before scoring (services/radar_status.gate1), from the stored answers:
    possibly nascent to confirm, an import's matches and proposed sub-domains,
    pages Classify hasn't judged, ready to assess, switched-off ones with new pages."""
    from app.services import evidence, imports_gate
    from app.services.radar_status import _pages
    from app.services.settings_store import radar_settings
    status, rows = get_collection("tech_status"), get_collection("tech_status_rows")
    items = []
    nascent_count = status.count_documents({"f.nascent_open": True})
    nascent = list(status.find({"f.nascent_open": True}, {"name": 1, "label": 1}).sort("_id", 1).limit(LISTED))
    if nascent:
        extra = {r["_id"]: r for r in rows.find({"_id": {"$in": [n["_id"] for n in nascent]}},
                                                {"nascent_note": 1, "row.classification.nascent.yes_replaces": 1})}
        items.append({"kind": "nascent", "count": nascent_count,
                      "sentence": f"{nascent_count:,} possibly nascent {'technology' if nascent_count == 1 else 'technologies'} to confirm",
                      "sub": "A strong early sign; a person says yes or no. Yes lets it be assessed and moves it to Research or Pilot; No sets it aside until a new page flags it.",
                      "href": "/admin/technologies?view=nascent",
                      "technologies": [{"tech_id": n["_id"], "name": _name(n), "note": extra.get(n["_id"], {}).get("nascent_note"),
                                        # each row answers Yes or No in place: what a Yes would replace
                                        "replaces": ((extra.get(n["_id"], {}).get("row") or {}).get("classification") or {})
                                        .get("nascent", {}).get("yes_replaces")} for n in nascent]})
    items.extend(imports_gate.items())
    waiting = status.count_documents({"f.classify_waiting": True})
    if waiting:
        items.append({"kind": "classify", "count": waiting,
                      "sentence": f"{waiting:,} {'technology has' if waiting == 1 else 'technologies have'} new pages not judged yet",
                      "sub": "The Classify step on Operations judges how solid each one's evidence is and sets its domain, "
                             "commercial availability and maturity (TRL): one model call each.",
                      "href": "/admin/operations#classify", "calls": waiting})
    ready = offer("ready")
    if ready:
        n = ready["count"]
        items.append({"kind": "ready_to_assess", **ready,
                      "sentence": f"{n:,} {'technology is' if n == 1 else 'technologies are'} ready to assess",
                      "sub": f"Their evidence was judged enough. About {ready['calls']:,} model calls.",
                      "href": "/admin/technologies?view=not_assessed&status=ready"})
    off = list(get_collection("technologies").find(
        {"_id": {"$in": status.distinct("_id", {"f.status": "off"})}},
        {"name": 1, "label": 1, "enabled": 1, "switched_off_at": 1}))
    since = evidence.pages_since_off(off)
    wake = int(radar_settings()["wake_after_pages"])
    woke = [t for t in off if since.get(t["_id"], 0) >= wake]
    if woke:
        items.append({"kind": "switched_off_with_pages", "count": len(woke),
                      "sentence": f"{len(woke):,} switched-off {'technology has' if len(woke) == 1 else 'technologies have'} new pages",
                      "sub": f"{wake} or more pages since each was switched off: have a look.",
                      "href": "/admin/technologies?view=off",
                      "technologies": [{"tech_id": t["_id"], "name": _name(t), "note": _pages(since[t["_id"]], "new ")}
                                       for t in woke]})
    for item in items:  # the first names only: the count says how many, and the item links to all of them
        if len(item.get("technologies") or []) > LISTED:
            item["technologies"] = item["technologies"][:LISTED]
    return items


def gate2() -> list[dict]:
    """Before publishing (services/gates.gate2), from each technology's stored items."""
    by_kind: dict[str, list] = {k: [] for k in GATE2_KINDS}
    for r in get_collection("tech_status_rows").find({"gate2.0": {"$exists": True}}, {"gate2": 1}):
        for item in r["gate2"]:
            by_kind.setdefault(item["kind"], []).append(item["row"])
    by_kind["unscored"].sort(key=lambda r: (not r["blocking"], r["best"], r["name"]))
    for kind in GATE2_KINDS[1:]:
        by_kind[kind].sort(key=lambda r: (r["best"], r["name"]))
    return [{"kind": kind, "count": len(rows), "technologies": rows[:LISTED]} for kind, rows in by_kind.items() if rows]


# ── what waits, for the status pill (api/pipeline) ──────────────────

def waiting_lists() -> dict:
    """The waiting lists (services/evidence) read from the stored answers:
    with new evidence, stopped partway (by run), ready for a Point of View."""
    status, rows = get_collection("tech_status"), get_collection("tech_status_rows")
    new = [{"tech_id": r["_id"], "name": r["name"], "new_pages": r["f"]["new_pages"]}
           for r in status.find({"f.state": "new_evidence"}, {"name": 1, "f.new_pages": 1})]
    targets = {r["_id"]: r["target"] for r in rows.find({"_id": {"$in": [n["tech_id"] for n in new]}}, {"target": 1})}
    for n in new:
        n["assessed_at"] = (targets.get(n["tech_id"]) or {}).get("assessed_at")
    new.sort(key=lambda t: (-t["new_pages"], t["name"]))
    by_run: dict[str, dict] = {}
    stopped_ids = status.distinct("_id", {"f.state": "stopped_partway"})
    for r in rows.find({"_id": {"$in": stopped_ids}}, {"unfinished": 1}):
        run = r.get("unfinished")
        if run:
            by_run.setdefault(run["scoring_run_id"], {**run, "tech_ids": []})["tech_ids"].append(r["_id"])
    stopped = sorted(by_run.values(), key=lambda x: x["started_at"], reverse=True)
    write_ids = status.distinct("_id", {"f.state": "no_pov"})
    to_write = sorted((r["target"] for r in rows.find({"_id": {"$in": write_ids}}, {"target": 1}) if r.get("target")),
                      key=lambda t: t["technology"])
    return {"with_new_evidence": new, "stopped_runs": stopped, "pov_targets": to_write}


def written_povs() -> int:
    """Technologies switched on and still in the register with a Point of View written."""
    ids = get_collection("povs").distinct("tech_id")
    return get_collection("tech_status").count_documents({"_id": {"$in": ids}, "f.status": {"$ne": "off"}})


def rewrite_count() -> int:
    """How many Points of View "Rewrite all" writes (rewrite_targets), counted
    from indexes: switched-on technologies with a latest assessment."""
    rows = get_collection("tech_status_rows")
    off = get_collection("tech_status").distinct("_id", {"f.status": "off"})
    return (rows.count_documents({"target.scoring_run_id": {"$exists": True}})
            - rows.count_documents({"_id": {"$in": off}, "target.scoring_run_id": {"$exists": True}}))


def rewrite_targets() -> list[dict]:
    """What "Rewrite all" covers (api/scoring_runs): every switched-on
    technology with a latest assessment, each written from it."""
    on = set(get_collection("tech_status").distinct("_id", {"f.status": {"$ne": "off"}}))
    return sorted((r["target"] for r in get_collection("tech_status_rows").find({"target": {"$ne": None}}, {"target": 1})
                   if r["_id"] in on), key=lambda t: t["technology"])
