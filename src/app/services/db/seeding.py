"""Seeding data — the configuration in the code (the files in seeds/) — and
the live configuration in MongoDB.

An edit in the app takes effect at once and never touches the seeding data.
The Changes tab lists the live items that differ from it; "Update seeding
data" writes the ones the user ticks into the seed files, so the next
deployment ships with them.

When the seed files change (a new version of the code), their changes load
into every item not edited in the app since it was last made equal to the
files (by a load, Update seeding data or Put back the default: `seeded_at`).
Items edited in the app keep their live values and stay on the Changes tab
(`kept`). An item removed from the code is removed live, unless it was edited
in the app; items added in the app, items deleted in the app and proposals
awaiting review are left as they are. The state document remembers the seed
ids last loaded or written (`ids`), which tells "removed from the code" apart
from "added in the app". A database from before these were kept removes
nothing, and at its first start marks the items equal to the files.

  load_if_new()          at start: load the seeding data into a fresh
                         database, or the code's changes when the seed files
                         changed since this database last loaded or wrote them
  changes()              the Changes tab
  update_seeding_data()  write the ticked items into the seed files
"""

import errno
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from pymongo import UpdateOne

from app.services.db.mongo import get_collection

log = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parents[4] / "seeds"

# seed file <list>.json holds {"<list>": [...]}; this field becomes _id
ID_FIELDS = {
    "sources": "source_id",
    "prompts": "name",
    "signals": "signal_id",
    "settings": "name",
    "fabrics": "fabric_id",
    "measures": "measure_id",
    "scoring_config": "name",
    "recipes": "recipe_id",
    "availability": "availability_id",
    "domains": "domain_id",
    "subdomains": "subdomain_id",
    "trl_levels": "trl_id",
    "path_steps": "step_id",
    "mechanisms": "mechanism_id",
    "assumptions": "assumption_id",
}
NOT_COMPARED = {"version"}
# items the model proposed that no person has reviewed yet: listed where they're
# reviewed (Setup › Classification › Domains), not as setup edits
AWAITING_REVIEW = {"subdomains": {"status": "new"}}  # the app's own counter: written with an item, never compared
STATE_ID = "state"
_lock = threading.Lock()  # one load or export at a time: they share the seed files


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(name: str) -> Path:
    return SEEDS_DIR / f"{name}.json"


def read_list(name: str) -> list[dict]:
    return json.loads(_path(name).read_text())[name]


def list_fields(items: list[dict]) -> list[str]:
    """A list's seeded fields: every key its items use, in first-seen order."""
    fields: list[str] = []
    for item in items:
        for key in item:
            if key not in fields:
                fields.append(key)
    return fields


def fingerprint() -> str:
    digest = hashlib.sha256()
    for name in sorted(ID_FIELDS):
        digest.update(name.encode())
        digest.update(_path(name).read_bytes())
    return digest.hexdigest()


def _state() -> dict:
    return get_collection("seeding").find_one({"_id": STATE_ID}) or {}


def _seed_ids() -> dict[str, list[str]]:
    return {name: [i[id_field] for i in read_list(name)] for name, id_field in ID_FIELDS.items()}


# ── load ─────────────────────────────────────────────────────────────

def load_if_new() -> bool:
    """Load the seeding data when this database is fresh; when the seed files
    changed since it last loaded or wrote them, load the code's changes into
    everything not edited in the app. A restart loads nothing."""
    with _lock:
        state = _state()
        current = fingerprint()
        store = get_collection("seeding")
        if state.get("fingerprint") == current:
            if "ids" not in state:  # first start on this version
                _mark_equal()
                store.update_one({"_id": STATE_ID}, {"$set": {"ids": _seed_ids()}})
            return False
        new_ids = _seed_ids()
        if "loaded_at" not in state:  # a fresh database
            kept: list[dict] = []
            load()
        else:
            old_ids = state.get("ids")
            kept = _edited_in_app(state["loaded_at"], old_ids or {})
            load(kept, old_ids)
            if kept:
                names = ", ".join(f"{r['collection']}/{r['id']}" for r in kept)
                one = len(kept) == 1
                log.info("seeding data: loaded the code's changes; kept %d edit%s made in the app (%s); "
                         "Setup › Changes lists %s", len(kept), "" if one else "s", names, "it" if one else "them")
            else:
                log.info("seeding data: loaded the code's changes; no edits made in the app to keep")
        store.replace_one(
            {"_id": STATE_ID},
            {"_id": STATE_ID, "loaded_at": _now(), "fingerprint": current, "ids": new_ids, "kept": kept},
            upsert=True)
        return True


def _edited_in_app(loaded_at: str, old_ids: dict[str, list[str]]) -> list[dict]:
    """The live items the load would change or remove that were edited in the
    app since the seeding data was loaded and since they were last made equal
    to the seed files, and that differ from the seed files now."""
    refs = []
    for name, id_field in ID_FIELDS.items():
        seeded = {i[id_field]: i for i in read_list(name)}
        fields = list_fields(list(seeded.values()))
        for doc in get_collection(name).find({"_id": {"$in": sorted({*seeded, *old_ids.get(name, [])})}}):
            seed = seeded.get(doc["_id"])
            # no seeded_at (a database from before it was kept): loaded_at alone decides
            if (_edited_after(doc, loaded_at) and _edited_after(doc, doc.get("seeded_at"))
                    and (seed is None or _differs(fields, seed, doc))):
                refs.append({"collection": name, "id": doc["_id"]})
    return refs


def _mark_equal() -> None:
    """Stamp seeded_at on the live items equal to the seed files: a database
    from before seeded_at was kept, at its first start on this version."""
    now = _now()
    for name, id_field in ID_FIELDS.items():
        seeded = {i[id_field]: i for i in read_list(name)}
        fields = list_fields(list(seeded.values()))
        coll = get_collection(name)
        same = [d["_id"] for d in coll.find({"_id": {"$in": list(seeded)}})
                if not _differs(fields, seeded[d["_id"]], d)]
        coll.update_many({"_id": {"$in": same}}, {"$set": {"seeded_at": now}})


def load(keep=(), old_ids: dict[str, list[str]] | None = None) -> None:
    """Make the configuration match the seeding data: add missing items and
    replace the seeded fields of existing ones, except the items in `keep`
    (edited in the app) and items deleted in the app (in `old_ids`, missing
    live). Remove only items in `old_ids` the seeding data no longer has, not
    kept and not awaiting review; with no `old_ids` remove nothing. Fields it
    doesn't have (progress, counts, updated_at) are left alone."""
    keep = {(r["collection"], r["id"]) for r in keep}
    now = _now()
    for name, id_field in ID_FIELDS.items():
        items = read_list(name)
        fields = list_fields(items)
        coll = get_collection(name)
        was = set((old_ids or {}).get(name, []))
        live = set(coll.distinct("_id", {"_id": {"$in": sorted(was)}})) if was else set()
        ops = []
        for item in items:
            item_id = item[id_field]
            if (name, item_id) in keep or (item_id in was and item_id not in live):
                continue
            update: dict = {"$set": {**item, "seeded_at": now}}
            dropped = {f: "" for f in fields if f not in item}
            if dropped:
                update["$unset"] = dropped
            ops.append(UpdateOne({"_id": item_id}, update, upsert=True))
        if ops:
            coll.bulk_write(ops)
        gone = sorted(was - {i[id_field] for i in items} - {i for n, i in keep if n == name})
        removed = 0
        if gone:
            query: dict = {"_id": {"$in": gone}}
            if name in AWAITING_REVIEW:
                query["$nor"] = [AWAITING_REVIEW[name]]
            removed = coll.delete_many(query).deleted_count
        log.info("seeding data: %s loaded (%d items, %d removed)", name, len(items), removed)


# ── the Changes tab ──────────────────────────────────────────────────

def _edited_after(doc: dict, loaded_at: str | None) -> bool:
    if not loaded_at:
        return True
    stamp = doc.get("updated_at")
    if not stamp:
        return False
    try:
        return datetime.fromisoformat(str(stamp)) > datetime.fromisoformat(loaded_at)
    except ValueError:
        return False


def _differs(fields: list[str], seed: dict, doc: dict) -> list[str]:
    return [f for f in fields if f not in NOT_COMPARED and doc.get(f) != seed.get(f)]


def _label(name: str, item: dict) -> str:
    if name == "measures" and item.get("code"):
        return f"{item['code']} {item.get('name', '')}".strip()
    return str(item.get("name") or item.get("_id"))


def _awaiting(name: str, doc: dict) -> bool:
    wanted = AWAITING_REVIEW.get(name)
    return bool(wanted) and all(doc.get(k) == v for k, v in wanted.items())


def changes() -> dict:
    """Live configuration items that differ from the seeding data:
    edited (after the seeding data was loaded, or kept at that load), added,
    or deleted. Items the
    model proposed and no one has reviewed yet are counted apart
    (`awaiting_review`), never offered as defaults."""
    state = _state()
    loaded_at = state.get("loaded_at")
    kept = {(r["collection"], r["id"]) for r in state.get("kept", [])}
    rows: list[dict] = []
    awaiting: dict[str, int] = {}

    def row(name, item_id, item, kind, fields):
        rows.append({"collection": name, "id": item_id, "label": _label(name, item),
                     "kind": kind, "updated_at": item.get("updated_at") if kind != "deleted" else None,
                     "fields": fields})

    for name, id_field in ID_FIELDS.items():
        seeded = {i[id_field]: i for i in read_list(name)}
        fields = list_fields(list(seeded.values()))
        live = {d["_id"]: d for d in get_collection(name).find()}
        for item_id, doc in live.items():
            seed = seeded.get(item_id)
            if seed is None and _awaiting(name, doc):
                awaiting[name] = awaiting.get(name, 0) + 1
                continue
            if seed is None:
                row(name, item_id, doc, "added",
                    [{"field": f, "seeding_value": None, "live_value": doc[f]}
                     for f in fields if f in doc and f != id_field])
            elif _edited_after(doc, loaded_at) or (name, item_id) in kept:
                diffs = [{"field": f, "seeding_value": seed.get(f), "live_value": doc.get(f)}
                         for f in _differs(fields, seed, doc)]
                if diffs:
                    row(name, item_id, doc, "edited", diffs)
        for item_id, seed in seeded.items():
            if item_id not in live:
                row(name, item_id, seed, "deleted",
                    [{"field": f, "seeding_value": seed[f], "live_value": None}
                     for f in fields if f in seed and f != id_field])
    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return {"count": len(rows), "loaded_at": loaded_at, "items": rows, "awaiting_review": awaiting}


# ── Put back the default ─────────────────────────────────────────────

def revert(refs: list[dict]) -> dict:
    """Put the ticked items back to their seeding data: an edited one gets its
    seeded fields back, an added one is removed, a deleted one comes back. The
    opposite of Update seeding data; the item then leaves the Changes tab."""
    put_back = 0
    for ref in refs:
        name, item_id = ref["collection"], ref["id"]
        id_field = ID_FIELDS[name]
        items = read_list(name)
        seed = next((i for i in items if i.get(id_field) == item_id), None)
        coll = get_collection(name)
        if seed is None:
            put_back += coll.delete_one({"_id": item_id}).deleted_count
            continue
        now = _now()
        update: dict = {"$set": {**seed, "updated_at": now, "seeded_at": now}}
        dropped = {f: "" for f in list_fields(items) if f not in seed}
        if dropped:
            update["$unset"] = dropped
        coll.update_one({"_id": item_id}, update, upsert=True)
        put_back += 1
    return {"put_back": put_back}


# ── Update seeding data ──────────────────────────────────────────────

def update_seeding_data(refs: list[dict]) -> dict:
    """Write the ticked items' live values into the seed files. Each file is
    written whole or not at all; the new fingerprint is recorded even when a
    later file fails, so a restart never reloads what the app itself wrote."""
    wanted: dict[str, list[str]] = {}
    for ref in refs:
        wanted.setdefault(ref["collection"], []).append(ref["id"])
    written, files = 0, []
    with _lock:
        try:
            for name, ids in wanted.items():
                count = _write_list(name, ids)
                if count:
                    written += count
                    files.append(f"seeds/{name}.json")
        finally:
            get_collection("seeding").update_one(
                {"_id": STATE_ID}, {"$set": {"fingerprint": fingerprint(), "ids": _seed_ids()}}, upsert=True)
    return {"written": written, "files": files}


def _write_list(name: str, ids: list[str]) -> int:
    id_field = ID_FIELDS[name]
    path = _path(name)
    data = json.loads(path.read_text())
    items: list[dict | None] = data[name]
    fields = list_fields([i for i in items if i])
    position = {item[id_field]: n for n, item in enumerate(items)}
    live = {d["_id"]: d for d in get_collection(name).find({"_id": {"$in": ids}})}
    changed = 0
    for item_id in ids:
        doc = live.get(item_id)
        if doc is None:  # deleted in the app
            if item_id in position and items[position[item_id]] is not None:
                items[position[item_id]] = None
                changed += 1
            continue
        new = {id_field: item_id, **{f: doc[f] for f in fields if f in doc and f != id_field}}
        if item_id in position:
            old = items[position[item_id]] or {}
            merged = {k: new[k] for k in old if k in new} | {k: v for k, v in new.items() if k not in old}
            if merged != old:
                items[position[item_id]] = merged
                changed += 1
        else:  # added in the app
            items.append(new)
            changed += 1
    if changed:
        if not os.access(path, os.W_OK):
            raise PermissionError(errno.EACCES, "seed file is read-only", str(path))
        data[name] = [i for i in items if i is not None]
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")
        os.replace(tmp, path)
        log.info("seeding data: wrote %d item(s) into %s", changed, path.name)
    # these live items now equal the file
    get_collection(name).update_many({"_id": {"$in": list(live)}}, {"$set": {"seeded_at": _now()}})
    return changed
