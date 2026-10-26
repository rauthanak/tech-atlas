"""Technology resolver (Phase B).

Turns the raw `technologies` strings on documents into a canonical technology
register (`technologies` collection) and stamps every document with
`technologies_resolved` — the canonical names for its raw tags.

Passes, cheapest first:
  1. deterministic — normalize case/punctuation/whitespace; merges pure
     spelling variants for free
  2. LLM pass over the surviving names in large alphabetical chunks — returns
     ONLY merge groups (unmentioned names are declared unique), per the
     `technology_resolve` prompt
  3. LLM pass over the resulting canonical names, sorted by frequency, to
     catch merges split across chunk boundaries

Afterwards, technologies without a display label get one — the same name
with its usual capitals ("ml-kem" → "ML-KEM") — from the `technology_label`
prompt (label_missing).

Existing alias assignments are pinned: a raw string already claimed by a
technology (including admin moves) is never re-sent to the LLM, so admin
corrections and earlier resolves survive re-resolves. `replace=True` wipes the
register and starts over. Documents are never rewritten beyond the stamp.

An Organize works only on the visits waiting for it (`to_organize`: new page
versions, and pages Check again read anew), and on older pages naming a name
it claims; counts are of pages (services/pages), not visits. Starting over
reads every page."""

import json
import logging
import re
import threading
import uuid
from collections import Counter, defaultdict

from pymongo import UpdateOne

from app.services.llm.context import with_context
from app.services import auth
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM, parse_json
from app.services.prompts.store import PromptStore
from app.services.timezone import now_utc
from app.services.websearch import SOURCE as WEB_SEARCH_SOURCE
from app.settings import get_settings
from app.services import jobs

log = logging.getLogger(__name__)
WEB_SEARCH = WEB_SEARCH_SOURCE["source_id"]

_lock = threading.Lock()


def _busy() -> bool:
    """An Organize is under way (its record says so: it may run in the worker)."""
    return get_collection("resolves").find_one({"status": "running"}, {"_id": 1}) is not None


def reconcile_stale() -> None:
    """At the start of the process that runs jobs: an Organize still 'running' died with the one before."""
    done = get_collection("resolves").update_many(
        {"status": "running"}, {"$set": {"status": "failed", "error": "interrupted — the service restarted",
                                         "finished_at": now_utc()}})
    if done.modified_count:
        log.warning("resolver: %d interrupted organize(s) marked failed", done.modified_count)


def _norm(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "tech"


# ── public API ───────────────────────────────────────────────────────

def start_resolve(replace: bool = False) -> str:
    """Kick off a resolve in a background thread; returns the resolve id.
    Raises RuntimeError if one is already running."""
    with _lock:
        if _busy():
            raise RuntimeError("a resolve is already running")
        resolve_id = _create_resolve_doc(replace)
    jobs.start(_execute, resolve_id, replace)
    return resolve_id


def _create_resolve_doc(replace: bool) -> str:
    resolve_id = uuid.uuid4().hex[:12]
    get_collection("resolves").insert_one({
        "_id": resolve_id,
        "status": "running",
        "by": auth.by(),  # who started it (None: the radar's own work)
        "replace": replace,
        "phase": "starting",
        "phase_history": [{"phase": "starting", "at": now_utc()}],
        "llm_calls": 0,
        "started_at": now_utc(),
    })
    return resolve_id


def run_resolve_sync(replace: bool = False) -> str | None:
    """Run a resolve inline on the caller's thread — the scout runner's
    'resolving' stage. Skips (returns None) when one is already running."""
    with _lock:
        if _busy():
            return None
        resolve_id = _create_resolve_doc(replace)
    _execute(resolve_id, replace)
    return resolve_id


def _alias_map() -> dict[str, str]:
    """Every name a page may use, to the technology it means."""
    alias_map: dict[str, str] = {}
    for t in get_collection("technologies").find({}, {"name": 1, "aliases": 1}):
        for a in t.get("aliases", []):
            alias_map[a] = t["name"]
    return alias_map


def _names_on(query: dict) -> list[str]:
    """The raw names on the visits matching `query` (set-aside pages left out)."""
    return [r["_id"] for r in get_collection("documents").aggregate([
        {"$match": {**query, "ignored_by": None}}, {"$unwind": "$technologies"},
        {"$group": {"_id": "$technologies"}}], allowDiskUse=True)]


def _page_counts(match: dict, names: list[str] | None = None) -> Counter:
    """How many pages (services/pages), not visits, name each raw name among
    the visits matching `match`; set-aside pages left out. `names`: only these."""
    rows = get_collection("documents").aggregate([
        {"$match": {**match, "ignored_by": None}},
        {"$project": {"technologies": 1, "page": {"$ifNull": ["$page_key", "$end_url"]}}},
        {"$unwind": "$technologies"},
        *([{"$match": {"technologies": {"$in": names}}}] if names is not None else []),
        {"$group": {"_id": {"t": "$technologies", "p": "$page"}}},
        {"$group": {"_id": "$_id.t", "n": {"$sum": 1}}}], allowDiskUse=True)
    return Counter({r["_id"]: r["n"] for r in rows})


def restamp(names) -> int:
    """After a change to which technology a name means (a person's rename,
    merge or moved alias; an import; pages filed by Find evidence or by
    linking known names): re-link only the pages that name one of these names, and recount only the technologies
    they named before or name now. Costs what that technology's pages cost,
    not what every page costs."""
    names = sorted({n for n in names if n})
    if not names:
        return 0
    return _relink({"technologies": {"$in": names}}, _alias_map(), names)


def _relink(query: dict, alias_map: dict[str, str], also=()) -> int:
    """Link the pages matching `query` again, and recount the technologies
    they were linked to before or are now (and `also`)."""
    docs = get_collection("documents")
    before = set(docs.distinct("technologies_resolved", query))
    stamped = _stamp_documents(alias_map, query)
    after = set(docs.distinct("technologies_resolved", query))
    recompute_stats(sorted(before | after | set(also)))
    return stamped


# ── the resolve itself ───────────────────────────────────────────────

def _execute(resolve_id: str, replace: bool) -> None:
    resolves = get_collection("resolves")
    try:
        with with_context(run_kind="resolve", run_id=resolve_id):
            stats = _resolve(resolve_id, replace)
        resolves.update_one({"_id": resolve_id}, {"$set": {
            "status": "completed", "phase": "done",
            "finished_at": now_utc(), **stats},
            "$push": {"phase_history": {"phase": "done", "at": now_utc()}}})
        log.info("resolve %s completed: %s", resolve_id, stats)
    except Exception as exc:  # a failed resolve must never take the app down
        log.exception("resolve %s failed", resolve_id)
        resolves.update_one({"_id": resolve_id}, {"$set": {
            "status": "failed", "error": str(exc), "finished_at": now_utc()}})


def _progress(resolve_id: str, **fields) -> None:
    update: dict = {"$set": fields}
    if "phase" in fields:  # phase changes also land in the drill-down timeline
        update["$push"] = {"phase_history": {"phase": fields["phase"], "at": now_utc()}}
    get_collection("resolves").update_one({"_id": resolve_id}, update)


def _resolve(resolve_id: str, replace: bool) -> dict:
    settings = get_settings()
    techs = get_collection("technologies")

    # 1 · the visits this Organize works on, claimed so pages stored meanwhile wait for the next one
    docs = get_collection("documents")
    if not replace:
        docs.update_many({"to_organize": {"$exists": True}}, {"$set": {"to_organize": resolve_id}})
    waiting = {"to_organize": resolve_id}
    waiting_n = None if replace else docs.count_documents(waiting)

    # pinned assignments: raw string -> existing canonical name
    if replace:
        techs.delete_many({})
    pinned = _alias_map()
    pinned_norm = {_norm(a): name for a, name in pinned.items()}

    # 2 · gather raw strings and how many pages name each — pages set aside by
    # a Can ignore rule are left out (a missing ignored_by counts as null, so
    # old documents count). Starting over: every page's names; otherwise the
    # names on the waiting visits that no technology has claimed yet
    if replace:
        raw_counts = _page_counts({"technologies": {"$exists": True, "$ne": []}})
    else:
        new = [n for n in _names_on(waiting) if n not in pinned]
        raw_counts = _page_counts({"technologies": {"$in": new}}, new) if new else Counter()

    # 3 · deterministic pass: group by normalized key, keep the most common
    # spelling as the display name
    groups: dict[str, dict] = {}
    for raw, n in raw_counts.items():
        key = _norm(raw)
        if not key:
            continue
        g = groups.setdefault(key, {"raws": Counter(), "count": 0})
        g["raws"][raw] += n
        g["count"] += n
    for g in groups.values():
        g["display"] = g["raws"].most_common(1)[0][0]

    # 4 · frequency floor
    candidates = {k: g for k, g in groups.items()
                  if g["count"] >= settings.min_docs_per_tech}

    # canonical mapping we are building: display name -> canonical name
    canon: dict[str, str] = {}
    unassigned: list[tuple[str, int]] = []
    for key, g in candidates.items():
        # a new spelling of a claimed name ("ML KEM" for "ml-kem") joins it, with no model call
        hit = next((pinned[r] for r in g["raws"] if r in pinned), pinned_norm.get(key))
        if hit is not None:
            canon[g["display"]] = hit
        else:
            unassigned.append((g["display"], g["count"]))

    # the established register: fixed merge targets the LLM may fold new
    # names into, but never rename or merge with each other. Top names by
    # document volume, so the anchor is what the corpus actually talks about.
    known = known_register(settings.resolve_known_limit)

    # 5 · LLM pass 1 — alphabetical chunks put spelling-siblings together
    llm = LLM.initialize(settings.model_name)
    prompt = PromptStore.get("technology_resolve")
    llm_calls = 0
    names = sorted(n for n, _ in unassigned)
    _progress(resolve_id, phase="llm pass 1",
              raw_strings=len(raw_counts), candidates=len(candidates),
              to_resolve=len(names), known_context=len(known))
    for chunk in _chunks(names, settings.resolve_batch_size):
        for group in _llm_groups(llm, prompt, chunk, known):
            for member in group["members"]:
                canon[member] = group["name"]
        llm_calls += 1
        _progress(resolve_id, llm_calls=llm_calls)
    for n, _ in unassigned:
        canon.setdefault(n, n)

    # 6 · LLM pass 2 — canonical names by frequency, catches cross-chunk splits
    weight: Counter[str] = Counter()
    for g in candidates.values():
        weight[canon[g["display"]]] += g["count"]
    claimed_names = set(pinned.values())
    second = [n for n, _ in weight.most_common() if n not in claimed_names]
    _progress(resolve_id, phase="llm pass 2", canonical_after_pass1=len(weight))
    remap: dict[str, str] = {}
    for chunk in _chunks(second, settings.resolve_batch_size):
        for group in _llm_groups(llm, prompt, chunk, known):
            for member in group["members"]:
                remap[member] = group["name"]
        llm_calls += 1
        _progress(resolve_id, llm_calls=llm_calls)
    if remap:
        canon = {k: remap.get(v, v) for k, v in canon.items()}

    # 7 · upsert the register: canonical name -> all raw spellings behind it
    _progress(resolve_id, phase="writing register")
    buckets: dict[str, set[str]] = defaultdict(set)
    for g in candidates.values():
        buckets[canon[g["display"]]].update(g["raws"])
    # an existing name keeps its technology's id (a rename keeps the id it was
    # created with); a new name gets a slug id, numbered if that id is taken
    ids_by_name = {t["name"]: t["_id"] for t in techs.find({}, {"name": 1})}
    taken = set(ids_by_name.values())
    writes = []
    now = now_utc()
    for name, raws in buckets.items():
        tech_id = ids_by_name.get(name)
        if tech_id is None:
            tech_id = base = _slug(name)
            n = 2
            while tech_id in taken:
                tech_id, n = f"{base}-{n}", n + 1
            taken.add(tech_id)
            ids_by_name[name] = tech_id
        writes.append(UpdateOne(
            {"_id": tech_id},
            {"$set": {"name": name, "updated_at": now, "last_resolve": resolve_id},
             "$addToSet": {"aliases": {"$each": sorted(raws)}},
             "$setOnInsert": {"tech_id": tech_id, "enabled": True, "created_at": now}},
            upsert=True))
    if writes:
        techs.bulk_write(writes)

    # 8 · link the waiting visits and older pages naming a name claimed now, and
    # recount the technologies they touch (starting over: every page and technology)
    _progress(resolve_id, phase="stamping documents")
    alias_map = _alias_map()
    if replace:
        stamped = _stamp_documents(alias_map)
        recompute_stats()
    else:
        claimed = sorted({r for raws in buckets.values() for r in raws})
        stamped = _relink({"$or": [waiting, {"technologies": {"$in": claimed}}]} if claimed else waiting, alias_map)
    docs.update_many({"to_organize": {"$exists": True}} if replace else waiting, {"$unset": {"to_organize": ""}})

    # 9 · display labels for technologies that have none
    _progress(resolve_id, phase="labelling")
    label_calls = label_missing(llm)
    llm_calls += label_calls

    return {
        "new_pages": waiting_n,
        "raw_strings": len(raw_counts),
        "after_deterministic": len(groups),
        "candidates": len(candidates),
        "llm_calls": llm_calls,
        "technologies": techs.estimated_document_count(),
        "docs_stamped": stamped,
    }


LABEL_BATCH = 500  # names per technology_label call


# the skills' blanks: the Skills page's preview fills them with these same
# functions, so it shows exactly what an organize sends

def known_register(limit: int) -> list[str]:
    """The established register new names are folded into: the names with the
    most pages, and always every imported or hand-added name (they have no
    pages yet, so a page count alone would leave them out)."""
    top = [t["name"] for t in get_collection("technologies").find({}, {"name": 1})
           .sort("doc_count", -1).limit(limit)]
    kept = [t["name"] for t in get_collection("technologies").find({"origin": {"$in": ["imported", "added"]}}, {"name": 1})]
    return top + [n for n in kept if n not in set(top)]


def resolve_values(names: list[str], register: list[str]) -> dict:
    return {"tech_list": json.dumps(names, ensure_ascii=False),
            "known_list": json.dumps(register, ensure_ascii=False)}


def label_values(names: list[str]) -> dict:
    return {"names": json.dumps(names, ensure_ascii=False)}


def label_missing(llm: LLM | None = None) -> int:
    """Display labels for technologies without one: the same name with its
    usual capitals ("ml-kem" → "ML-KEM"), from the technology_label skill.
    A label that changes more than capitals is ignored, and a failed batch
    stays unlabelled until the next organize. Returns the model calls made."""
    techs = get_collection("technologies")
    names = sorted(t["name"] for t in techs.find({"label": {"$in": [None, ""]}}, {"name": 1}))
    if not names:
        return 0
    llm = llm or LLM.initialize(get_settings().model_name)
    prompt = PromptStore.get("technology_label")
    calls = 0
    for chunk in _chunks(names, LABEL_BATCH):
        calls += 1
        try:
            with with_context(skills=["technology_label"]):
                labels = parse_json(llm.ask(prompt.render(**label_values(chunk))))
            labels = labels.get("labels") if isinstance(labels, dict) else None
            if not isinstance(labels, dict):
                raise ValueError("no labels object in the reply")
        except Exception as exc:  # labels only change how names look: never fail the organize
            log.warning("technology labels skipped for %d names: %s", len(chunk), exc)
            continue
        writes = [UpdateOne({"name": n}, {"$set": {"label": labels[n].strip()}}) for n in chunk
                  if isinstance(labels.get(n), str) and labels[n].strip().lower() == n]
        if writes:
            techs.bulk_write(writes)
    return calls


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _llm_groups(llm: LLM, prompt, names: list[str], register: list[str]) -> list[dict]:
    """One resolver call. Returns validated merge groups; a chunk that fails
    twice is skipped (its names simply stay unique — the recoverable failure).
    `register` is the established-names context; members may only come from
    `names`, so established entries can attract new names but never move."""
    known = set(names)
    for attempt in (1, 2):
        try:
            with with_context(skills=["technology_resolve"]):
                out = llm.ask(prompt.render(**resolve_values(names, register)))
            data = parse_json(out)
            groups = []
            for g in data.get("groups", []):
                members = [m for m in g.get("members", []) if m in known]
                name = str(g.get("name", "")).strip().lower()
                if len(members) >= 1 and name:
                    groups.append({"name": name, "members": members})
            return groups
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning("resolver chunk parse failed (attempt %d): %s", attempt, exc)
    log.error("resolver chunk skipped after 2 failures (%d names stay unique)", len(names))
    return []


def _stamp_documents(alias_map: dict[str, str], query: dict | None = None) -> int:
    """technologies_resolved per document, and per finding that names its own
    technologies (signals.N.technologies_resolved). A set-aside page gets
    none, so the evidence for scoring, the counts and the Technologies page
    never include it; its own `technologies` field stays, so the decision can
    be audited. A finding none of whose names resolve has none of its own,
    and readers fall back to the page's. Only pages whose links change are
    written; returns how many were."""
    docs = get_collection("documents")
    writes, stamped = [], 0
    for d in docs.find({"technologies": {"$exists": True}, **(query or {})},
                       {"technologies": 1, "ignored_by": 1, "technologies_resolved": 1,
                        "signals.technologies": 1, "signals.technologies_resolved": 1}):
        resolved = [] if d.get("ignored_by") else \
            sorted({alias_map[t] for t in d.get("technologies", []) if t in alias_map})
        sets: dict = {} if d.get("technologies_resolved") == resolved else {"technologies_resolved": resolved}
        unsets: dict = {}
        for i, hit in enumerate(d.get("signals") or []):
            if "technologies" not in hit:
                continue
            own = sorted({alias_map[t] for t in hit["technologies"] if t in alias_map})
            if own and hit.get("technologies_resolved") != own:
                sets[f"signals.{i}.technologies_resolved"] = own
            elif not own and "technologies_resolved" in hit:
                unsets[f"signals.{i}.technologies_resolved"] = ""
        if not sets and not unsets:
            continue  # its links haven't changed: nothing to write
        writes.append(UpdateOne({"_id": d["_id"]}, {**({"$set": sets} if sets else {}), **({"$unset": unsets} if unsets else {})}))
        stamped += 1
        if len(writes) >= 1000:
            docs.bulk_write(writes)
            writes = []
    if writes:
        docs.bulk_write(writes)
    return stamped


# a page found by web search counts as its own site (services/websearch.source_of), worked out in the database:
# the address's host, without a leading "www."
_HOST = {"$ifNull": [{"$arrayElemAt": [{"$getField": {"field": "captures", "input": {
    "$regexFind": {"input": {"$ifNull": ["$end_url", ""]}, "regex": r"^[^:/?#]+://([^/?#]*)"}}}}, 0]}, ""]}
_SITE = {"$let": {"vars": {"h": _HOST}, "in": {"$cond": [
    {"$eq": [{"$substrBytes": ["$$h", 0, 4]}, "www."]}, {"$substrBytes": ["$$h", 4, -1]}, "$$h"]}}}
_SOURCE = {"$cond": [{"$eq": ["$source_id", WEB_SEARCH]},
                     {"$let": {"vars": {"s": _SITE}, "in": {"$cond": [{"$eq": ["$$s", ""]}, WEB_SEARCH, "$$s"]}}},
                     "$source_id"]}


def recompute_stats(names: list[str] | None = None) -> None:
    """Per-technology counts from the stamped documents (document records,
    distinct pages, sources, H-categories, kinds), counted in the database,
    so memory stays flat however many pages there are. `names`: only these
    technologies (a person's edit); otherwise every one."""
    match: dict = {"technologies_resolved": {"$exists": True, "$ne": []}}
    if names is not None:
        match["technologies_resolved"] = {"$in": names}
    docs = get_collection("documents")

    def grouped(extra: list[dict]) -> list[dict]:
        return list(docs.aggregate([{"$match": match}, {"$unwind": "$technologies_resolved"},
                                    *([{"$match": {"technologies_resolved": {"$in": names}}}] if names is not None else []),
                                    *extra], allowDiskUse=True))

    totals = {r["_id"]: r for r in grouped([
        {"$group": {"_id": "$technologies_resolved", "doc_count": {"$sum": 1},
                    "pages": {"$addToSet": {"$ifNull": ["$page_key", "$end_url"]}}, "sources": {"$addToSet": _SOURCE}}},
        {"$project": {"doc_count": 1, "page_count": {"$size": "$pages"}, "source_count": {"$size": "$sources"}}}])}
    spread: dict[str, dict] = defaultdict(lambda: {"horizons": {}, "kinds": {}})
    for field, key, empty in (("category", "horizons", "?"), ("kind", "kinds", "article")):
        for r in grouped([{"$group": {"_id": {"t": "$technologies_resolved", "v": {"$ifNull": [f"${field}", empty]}},
                                      "n": {"$sum": 1}}}]):
            counts = spread[r["_id"]["t"]][key]  # "" and a missing value both count as `empty`
            counts[r["_id"]["v"] or empty] = counts.get(r["_id"]["v"] or empty, 0) + r["n"]
    techs = get_collection("technologies")
    writes = []
    for t in techs.find({} if names is None else {"name": {"$in": names}}, {"name": 1}):
        a = totals.get(t["name"])
        writes.append(UpdateOne({"_id": t["_id"]}, {"$set": {
            "doc_count": a["doc_count"] if a else 0,
            "page_count": a["page_count"] if a else 0,
            "source_count": a["source_count"] if a else 0,
            "horizons": spread[t["name"]]["horizons"] if a else {},
            "kinds": spread[t["name"]]["kinds"] if a else {},
        }}))
        if len(writes) >= 1000:
            techs.bulk_write(writes)
            writes = []
    if writes:
        techs.bulk_write(writes)
    # pages were linked again (a resolve, a rename, Find evidence, linking known names):
    # these technologies' stored answers may have moved (any of them, after a full recount)
    from app.services import tech_status
    if names is None:
        tech_status.touch_all()
    else:
        tech_status.touch_names(names)
