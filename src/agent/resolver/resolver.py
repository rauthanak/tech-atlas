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

Existing alias assignments are pinned: a raw string already claimed by a
technology (including admin moves) is never re-sent to the LLM, so admin
corrections and earlier resolves survive re-resolves. `replace=True` wipes the
register and starts over. Documents are never rewritten beyond the stamp."""

import json
import logging
import re
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pymongo import UpdateOne

from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM
from app.services.prompts.store import PromptStore
from app.settings import get_settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_active_thread: threading.Thread | None = None
_sync_active = False


def _busy() -> bool:
    return _sync_active or (_active_thread is not None and _active_thread.is_alive())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "tech"


# ── public API ───────────────────────────────────────────────────────

def start_resolve(replace: bool = False) -> str:
    """Kick off a resolve in a background thread; returns the resolve id.
    Raises RuntimeError if one is already running."""
    global _active_thread
    with _lock:
        if _busy():
            raise RuntimeError("a resolve is already running")
        resolve_id = _create_resolve_doc(replace)
        _active_thread = threading.Thread(
            target=_execute, args=(resolve_id, replace), daemon=True,
            name=f"resolve-{resolve_id}")
        _active_thread.start()
        return resolve_id


def _create_resolve_doc(replace: bool) -> str:
    resolve_id = uuid.uuid4().hex[:12]
    get_collection("resolves").insert_one({
        "_id": resolve_id,
        "status": "running",
        "replace": replace,
        "phase": "starting",
        "phase_history": [{"phase": "starting", "at": _now()}],
        "llm_calls": 0,
        "started_at": _now(),
    })
    return resolve_id


def run_resolve_sync(replace: bool = False) -> str | None:
    """Run a resolve inline on the caller's thread — the scout runner's
    'resolving' stage. Skips (returns None) when one is already running."""
    global _sync_active
    with _lock:
        if _busy():
            return None
        _sync_active = True
        resolve_id = _create_resolve_doc(replace)
    try:
        _execute(resolve_id, replace)
    finally:
        _sync_active = False
    return resolve_id


def restamp_all() -> int:
    """Re-derive technologies_resolved on every document from the current
    register, and recompute per-technology stats. Deterministic, no LLM.
    Used after admin edits (rename, alias move)."""
    alias_map: dict[str, str] = {}
    for t in get_collection("technologies").find({}, {"name": 1, "aliases": 1}):
        for a in t.get("aliases", []):
            alias_map[a] = t["name"]
    stamped = _stamp_documents(alias_map)
    _recompute_stats()
    return stamped


# ── the resolve itself ───────────────────────────────────────────────

def _execute(resolve_id: str, replace: bool) -> None:
    resolves = get_collection("resolves")
    try:
        stats = _resolve(resolve_id, replace)
        resolves.update_one({"_id": resolve_id}, {"$set": {
            "status": "completed", "phase": "done",
            "finished_at": _now(), **stats},
            "$push": {"phase_history": {"phase": "done", "at": _now()}}})
        log.info("resolve %s completed: %s", resolve_id, stats)
    except Exception as exc:  # a failed resolve must never take the app down
        log.exception("resolve %s failed", resolve_id)
        resolves.update_one({"_id": resolve_id}, {"$set": {
            "status": "failed", "error": str(exc), "finished_at": _now()}})


def _progress(resolve_id: str, **fields) -> None:
    update: dict = {"$set": fields}
    if "phase" in fields:  # phase changes also land in the drill-down timeline
        update["$push"] = {"phase_history": {"phase": fields["phase"], "at": _now()}}
    get_collection("resolves").update_one({"_id": resolve_id}, update)


def _resolve(resolve_id: str, replace: bool) -> dict:
    settings = get_settings()
    techs = get_collection("technologies")

    # 1 · gather raw strings (stubs carry no technologies field — excluded)
    _progress(resolve_id, phase="gathering")
    raw_counts: Counter[str] = Counter()
    for d in get_collection("documents").find(
            {"technologies": {"$exists": True, "$ne": []}}, {"technologies": 1}):
        raw_counts.update(d["technologies"])

    # 2 · deterministic pass: group by normalized key, keep the most common
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

    # 3 · frequency floor
    candidates = {k: g for k, g in groups.items()
                  if g["count"] >= settings.min_docs_per_tech}

    # 4 · pinned assignments: raw string -> existing canonical name
    if replace:
        techs.delete_many({})
    pinned: dict[str, str] = {}
    for t in techs.find({}, {"name": 1, "aliases": 1}):
        for a in t.get("aliases", []):
            pinned[a] = t["name"]

    # canonical mapping we are building: display name -> canonical name
    canon: dict[str, str] = {}
    unassigned: list[tuple[str, int]] = []
    for g in candidates.values():
        hit = next((pinned[r] for r in g["raws"] if r in pinned), None)
        if hit is not None:
            canon[g["display"]] = hit
        else:
            unassigned.append((g["display"], g["count"]))

    # the established register: fixed merge targets the LLM may fold new
    # names into, but never rename or merge with each other. Top names by
    # document volume, so the anchor is what the corpus actually talks about.
    known = [t["name"] for t in techs.find({}, {"name": 1})
             .sort("doc_count", -1).limit(settings.resolve_known_limit)]

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
    second = [n for n, _ in weight.most_common() if n not in pinned.values()]
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
    writes = []
    now = _now()
    for name, raws in buckets.items():
        tech_id = _slug(name)
        writes.append(UpdateOne(
            {"_id": tech_id},
            {"$set": {"name": name, "updated_at": now, "last_resolve": resolve_id},
             "$addToSet": {"aliases": {"$each": sorted(raws)}},
             "$setOnInsert": {"tech_id": tech_id, "enabled": True, "created_at": now}},
            upsert=True))
    if writes:
        techs.bulk_write(writes)

    # 8 · stamp documents and compute per-technology stats
    _progress(resolve_id, phase="stamping documents")
    alias_map: dict[str, str] = {}
    for t in techs.find({}, {"name": 1, "aliases": 1}):
        for a in t.get("aliases", []):
            alias_map[a] = t["name"]
    stamped = _stamp_documents(alias_map)
    _recompute_stats()

    return {
        "raw_strings": len(raw_counts),
        "after_deterministic": len(groups),
        "candidates": len(candidates),
        "llm_calls": llm_calls,
        "technologies": techs.estimated_document_count(),
        "docs_stamped": stamped,
    }


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _llm_groups(llm: LLM, prompt, names: list[str], register: list[str]) -> list[dict]:
    """One resolver call. Returns validated merge groups; a chunk that fails
    twice is skipped (its names simply stay unique — the recoverable failure).
    `register` is the established-names context; members may only come from
    `names`, so established entries can attract new names but never move."""
    known = set(names)
    payload = json.dumps(names, ensure_ascii=False)
    known_payload = json.dumps(register, ensure_ascii=False)
    for attempt in (1, 2):
        try:
            out = llm.ask(prompt.render(tech_list=payload, known_list=known_payload))
            data = json.loads(out)
            groups = []
            for g in data.get("groups", []):
                members = [m for m in g.get("members", []) if m in known]
                name = str(g.get("name", "")).strip().lower()
                if len(members) >= 1 and name:
                    groups.append({"name": name, "members": members})
            return groups
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            log.warning("resolver chunk parse failed (attempt %d): %s", attempt, exc)
    log.error("resolver chunk skipped after 2 failures (%d names stay unique)", len(names))
    return []


def _stamp_documents(alias_map: dict[str, str]) -> int:
    docs = get_collection("documents")
    writes, stamped = [], 0
    for d in docs.find({"technologies": {"$exists": True}}, {"technologies": 1}):
        resolved = sorted({alias_map[t] for t in d.get("technologies", []) if t in alias_map})
        writes.append(UpdateOne({"_id": d["_id"]},
                                {"$set": {"technologies_resolved": resolved}}))
        stamped += 1
        if len(writes) >= 1000:
            docs.bulk_write(writes)
            writes = []
    if writes:
        docs.bulk_write(writes)
    return stamped


def _recompute_stats() -> None:
    """Per-technology counts from the stamped documents: document records,
    distinct pages, sources, H-categories, kinds."""
    acc: dict[str, dict] = defaultdict(lambda: {
        "doc_count": 0, "pages": set(), "sources": set(),
        "horizons": Counter(), "kinds": Counter()})
    for d in get_collection("documents").find(
            {"technologies_resolved": {"$exists": True, "$ne": []}},
            {"technologies_resolved": 1, "end_url": 1, "source_id": 1,
             "category": 1, "kind": 1}):
        for name in d["technologies_resolved"]:
            a = acc[name]
            a["doc_count"] += 1
            a["pages"].add(d.get("end_url"))
            a["sources"].add(d.get("source_id"))
            a["horizons"][d.get("category") or "?"] += 1
            a["kinds"][d.get("kind") or "article"] += 1
    techs = get_collection("technologies")
    writes = []
    for t in techs.find({}, {"name": 1}):
        a = acc.get(t["name"])
        writes.append(UpdateOne({"_id": t["_id"]}, {"$set": {
            "doc_count": a["doc_count"] if a else 0,
            "page_count": len(a["pages"]) if a else 0,
            "source_count": len(a["sources"]) if a else 0,
            "horizons": dict(a["horizons"]) if a else {},
            "kinds": dict(a["kinds"]) if a else {},
        }}))
    if writes:
        techs.bulk_write(writes)
