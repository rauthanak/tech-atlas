"""Startup bootstrap: verify MongoDB is reachable, create the database
(collections and indexes), and seed any empty collection from seeds/.
Runs on every app start-up and is idempotent."""

import json
import logging
from pathlib import Path

from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from app.services.db.mongo import COLLECTIONS, get_db, ping
from app.settings import get_settings

log = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parents[4] / "seeds"
# seed file <collection>.json holds {"<collection>": [...]}; this field becomes _id
ID_FIELDS = {
    "sources": "source_id",
    "prompts": "name",
    "fabrics": "fabric_id",
    "measures": "measure_id",
    "scoring_config": "name",
}


def ensure_database() -> None:
    """Create every known collection and its indexes if missing."""
    db = get_db()
    existing = db.list_collection_names()
    for name in COLLECTIONS:
        if name not in existing:
            db.create_collection(name)
    db["sources"].create_index([("horizon", ASCENDING)])
    db["runs"].create_index([("run_start_date_time", ASCENDING)])
    db["documents"].create_index([("run_id", ASCENDING)])
    db["documents"].create_index([("end_url", ASCENDING), ("scraped_at", ASCENDING)])
    db["documents"].create_index([("technologies_resolved", ASCENDING)])
    db["technologies"].create_index([("doc_count", ASCENDING)])
    db["scoring_runs"].create_index([("started_at", ASCENDING)])
    db["assessments"].create_index([("scoring_run_id", ASCENDING)])
    db["assessments"].create_index([("tech_id", ASCENDING)])
    db["povs"].create_index([("scoring_run_id", ASCENDING)])


def seed_if_empty(collection: str) -> None:
    coll = get_db()[collection]
    if coll.estimated_document_count() > 0:
        return
    docs = json.loads((SEEDS_DIR / f"{collection}.json").read_text())[collection]
    id_field = ID_FIELDS[collection]
    coll.insert_many([{"_id": d[id_field], **d} for d in docs])
    log.info("seeded %d %s", len(docs), collection)


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
    for collection in ID_FIELDS:
        seed_if_empty(collection)
    counts = {c: get_db()[c].estimated_document_count() for c in sorted(COLLECTIONS)}
    log.info("database %r ready (%s)", settings.mongo_db, counts)
