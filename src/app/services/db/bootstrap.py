"""Startup bootstrap: verify MongoDB is reachable, create the database's
collections, and load the seeding data when it is new to this database (see
seeding.py). Runs on every app start-up and is idempotent. The indexes listed
in seeds/indexes.json are built in the background by the process that runs
the jobs (services/jobs.upkeep), so the API answers at once even when one is
missing on a big database (MongoDB builds it without blocking reads and
writes; none is unique, so a missing one only makes some reads slower)."""

import json
import logging
import time

from pymongo.errors import PyMongoError

from app.services.db import seeding, upgrade_pages
from app.services.db.mongo import COLLECTIONS, get_db, ping
from app.settings import get_settings

log = logging.getLogger(__name__)


INDEXES_FILE = seeding.SEEDS_DIR / "indexes.json"


def declared_indexes() -> list[dict]:
    """The indexes in seeds/indexes.json: collection, keys [[field, 1|-1]], options."""
    return json.loads(INDEXES_FILE.read_text())["indexes"]


def ensure_indexes(db=None) -> None:
    """Create each declared index that is missing, saying how long each took.
    Never drops one: an index the file doesn't list is only reported, and one
    that can't be created is logged with its reason."""
    db = db if db is not None else get_db()
    wanted: dict[str, set] = {}
    for ix in declared_indexes():
        keys = [(field, direction) for field, direction in ix["keys"]]
        wanted.setdefault(ix["collection"], set()).add(tuple(keys))
        if tuple(keys) in {tuple(tuple(k) for k in i["key"]) for i in db[ix["collection"]].index_information().values()}:
            continue
        log.info("building index %s %s", ix["collection"], keys)
        started = time.monotonic()
        try:
            db[ix["collection"]].create_index(keys, **(ix.get("options") or {}))
            log.info("index %s %s built in %.0f s", ix["collection"], keys, time.monotonic() - started)
        except PyMongoError as exc:
            log.error("index %s %s couldn't be created: %s", ix["collection"], keys, exc)
    for name, keysets in wanted.items():
        for index_name, info in db[name].index_information().items():
            if index_name != "_id_" and tuple(tuple(k) for k in info["key"]) not in keysets:
                log.warning("index %s.%s isn't in seeds/indexes.json (kept)", name, index_name)


def ensure_database() -> None:
    """Create every known collection if missing (indexes: ensure_indexes)."""
    db = get_db()
    existing = db.list_collection_names()
    for name in COLLECTIONS:
        if name not in existing:
            db.create_collection(name)


def backfill() -> None:
    """Fill fields that older records lack, once (idempotent): Points of View
    written before their time zone was recorded show in the radar's default."""
    from app.services.settings_store import radar_settings

    zone = radar_settings()["default_time_zone"]
    done = get_db()["povs"].update_many({"composed_tz": {"$exists": False}},
                                        {"$set": {"composed_tz": zone}}).modified_count
    if done:
        log.info("backfill: %d Points of View marked as written in %s", done, zone)
    dedupe_decisions()


def dedupe_decisions() -> None:
    """One choice in force per thing chosen: where two are (saved at the same
    moment before 25 Oct 2026), the newest stays and the others are replaced."""
    from app.services.timezone import now_utc
    coll = get_db()["decisions"]
    key = {f: {"$ifNull": [f"${f}", None]} for f in ("kind", "tech_id", "fabric_id", "measure_id", "field", "key")}
    groups = coll.aggregate([{"$match": {"active": True}}, {"$sort": {"at": -1, "_id": -1}},
                             {"$group": {"_id": key, "ids": {"$push": "$_id"}, "n": {"$sum": 1}}},
                             {"$match": {"n": {"$gt": 1}}}])
    extra = [i for g in groups for i in g["ids"][1:]]
    if extra:
        coll.update_many({"_id": {"$in": extra}}, {"$set": {"active": False, "replaced_at": now_utc()}})
        log.info("backfill: %d choices replaced by a newer one on the same thing", len(extra))


def run() -> None:
    settings = get_settings()
    try:
        ping()
    except PyMongoError as exc:
        log.error(
            "MongoDB is not reachable at %s — aborting start-up. Start MongoDB and retry. (%s)",
            settings.mongo_uri,
            exc,
        )
        raise RuntimeError(f"MongoDB connection failed at {settings.mongo_uri}") from exc

    ensure_database()
    upgrade_pages.run()  # once, for page records stored before 24 Oct 2026
    if seeding.load_if_new():
        log.info("seeding data loaded into %r", settings.mongo_db)
    from app.services import accounts
    if made := accounts.seed_if_empty():  # the first accounts, once (seeds/accounts.json)
        log.info("%d accounts created from seeds/accounts.json: each chooses a new password at first sign-in", made)
    backfill()
    counts = {c: get_db()[c].estimated_document_count() for c in sorted(COLLECTIONS)}
    log.info("database %r ready (%s)", settings.mongo_db, counts)
