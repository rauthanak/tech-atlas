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
register and starts over. Documents are never rewritten beyond the stamp."""

import json
import logging
import re
import threading
import uuid
from collections import Counter, defaultdict

from pymongo import UpdateOne

from app.services.llm.context import with_context
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM, parse_json
from app.services.prompts.store import PromptStore
from app.services.timezone import now_utc
from app.services.websearch import source_of
from app.settings import get_settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_active_thread: threading.Thread | None = None
_sync_active = False


def _busy() -> bool:
    return _sync_active or (_active_thread is not None and _active_thread.is_alive())


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
        "phase_history": [{"phase": "starting", "at": now_utc()}],
        "llm_calls": 0,
        "started_at": now_utc(),
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

    # 1 · gather raw strings — pages set aside by a Can ignore rule are
    # left out (a missing ignored_by counts as null, so old documents count)
    _progress(resolve_id, phase="gathering")
    raw_counts: Counter[str] = Counter()
    for d in get_collection("documents").find(
            {"technologies": {"$exists": True, "$ne": []}, "ignored_by": None},
            {"technologies": 1}):
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

    # 8 · stamp documents and compute per-technology stats
    _progress(resolve_id, phase="stamping documents")
    alias_map: dict[str, str] = {}
    for t in techs.find({}, {"name": 1, "aliases": 1}):
        for a in t.get("aliases", []):
            alias_map[a] = t["name"]
    stamped = _stamp_documents(alias_map)
    _recompute_stats()

    # 9 · display labels for technologies that have none
    _progress(resolve_id, phase="labelling")
    label_calls = label_missing(llm)
    llm_calls += label_calls

    return {
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


def _stamp_documents(alias_map: dict[str, str]) -> int:
    """technologies_resolved per document, and per finding that names its own
    technologies (signals.N.technologies_resolved). A set-aside page gets
    none, so the evidence for scoring, the counts and the Technologies page
    never include it; its own `technologies` field stays, so the decision can
    be audited. A finding none of whose names resolve has none of its own,
    and readers fall back to the page's."""
    docs = get_collection("documents")
    writes, stamped = [], 0
    for d in docs.find({"technologies": {"$exists": True}},
                       {"technologies": 1, "ignored_by": 1, "signals.technologies": 1}):
        resolved = [] if d.get("ignored_by") else \
            sorted({alias_map[t] for t in d.get("technologies", []) if t in alias_map})
        update: dict = {"$set": {"technologies_resolved": resolved}}
        for i, hit in enumerate(d.get("signals") or []):
            if "technologies" not in hit:
                continue
            own = sorted({alias_map[t] for t in hit["technologies"] if t in alias_map})
            if own:
                update["$set"][f"signals.{i}.technologies_resolved"] = own
            else:
                update.setdefault("$unset", {})[f"signals.{i}.technologies_resolved"] = ""
        writes.append(UpdateOne({"_id": d["_id"]}, update))
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
            a["sources"].add(source_of(d))  # a page found by web search counts as its own site
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
