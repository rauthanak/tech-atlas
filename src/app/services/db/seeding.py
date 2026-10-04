"""Seeding data — the configuration in the code (the files in seeds/) — and
the live configuration in MongoDB.

An edit in the app takes effect at once and never touches the seeding data.
The Changes tab lists the live items that differ from it; "Update seeding
data" writes the ones the user ticks into the seed files, so the next
deployment ships with them.

  load_if_new()          at start: load the seeding data into a fresh
                         database, or when the seed files changed since this
                         database last loaded or wrote them
  changes()              the Changes tab
  update_seeding_data()  write the ticked items into the seed files
"""

import errno
import hashlib
import json
import logging
import os
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
}
NOT_COMPARED = {"version"}  # the app's own counter: written with an item, never compared
STATE_ID = "state"


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


# ── load ─────────────────────────────────────────────────────────────

def load_if_new() -> bool:
    """Load the seeding data when this database is fresh, or when the seed
    files changed since it last loaded or wrote them. A restart loads nothing."""
    current = fingerprint()
    if _state().get("fingerprint") == current:
        return False
    load()
    get_collection("seeding").replace_one(
        {"_id": STATE_ID},
        {"_id": STATE_ID, "loaded_at": _now(), "fingerprint": current},
        upsert=True)
    return True


def load() -> None:
    """Make the configuration exactly match the seeding data: add missing
    items, replace the seeded fields of existing ones, and remove items the
    seeding data doesn't have. Fields it doesn't have (progress, counts,
    updated_at) are left alone."""
    for name, id_field in ID_FIELDS.items():
        items = read_list(name)
        fields = list_fields(items)
        ops = []
        for item in items:
            update: dict = {"$set": item}
            dropped = {f: "" for f in fields if f not in item}
            if dropped:
                update["$unset"] = dropped
            ops.append(UpdateOne({"_id": item[id_field]}, update, upsert=True))
        coll = get_collection(name)
        if ops:
            coll.bulk_write(ops)
        removed = coll.delete_many({"_id": {"$nin": [i[id_field] for i in items]}}).deleted_count
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


def _label(name: str, item: dict) -> str:
    if name == "measures" and item.get("code"):
        return f"{item['code']} {item.get('name', '')}".strip()
    return str(item.get("name") or item.get("_id"))


def changes() -> dict:
    """Live configuration items that differ from the seeding data:
    edited (after the seeding data was loaded), added, or deleted."""
    loaded_at = _state().get("loaded_at")
    rows: list[dict] = []

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
            if seed is None:
                row(name, item_id, doc, "added",
                    [{"field": f, "seeding_value": None, "live_value": doc[f]}
                     for f in fields if f in doc and f != id_field])
            elif _edited_after(doc, loaded_at):
                diffs = [{"field": f, "seeding_value": seed.get(f), "live_value": doc.get(f)}
                         for f in fields
                         if f not in NOT_COMPARED and doc.get(f) != seed.get(f)]
                if diffs:
                    row(name, item_id, doc, "edited", diffs)
        for item_id, seed in seeded.items():
            if item_id not in live:
                row(name, item_id, seed, "deleted",
                    [{"field": f, "seeding_value": seed[f], "live_value": None}
                     for f in fields if f in seed and f != id_field])
    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return {"count": len(rows), "loaded_at": loaded_at, "items": rows}


# ── Update seeding data ──────────────────────────────────────────────

def update_seeding_data(refs: list[dict]) -> dict:
    """Write the ticked items' live values into the seed files. Each file is
    written whole or not at all; the new fingerprint is recorded even when a
    later file fails, so a restart never reloads what the app itself wrote."""
    wanted: dict[str, list[str]] = {}
    for ref in refs:
        wanted.setdefault(ref["collection"], []).append(ref["id"])
    written, files = 0, []
    try:
        for name, ids in wanted.items():
            count = _write_list(name, ids)
            if count:
                written += count
                files.append(f"seeds/{name}.json")
    finally:
        get_collection("seeding").update_one(
            {"_id": STATE_ID}, {"$set": {"fingerprint": fingerprint()}}, upsert=True)
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
    return changed
