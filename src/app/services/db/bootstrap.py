"""Startup bootstrap: verify MongoDB is reachable, create the database
(collections and indexes), and load the seeding data when it is new to this
database (see seeding.py). Runs on every app start-up and is idempotent."""

import logging

from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from app.services.db import seeding
from app.services.db.mongo import COLLECTIONS, get_db, ping
from app.settings import get_settings

log = logging.getLogger(__name__)


def ensure_database() -> None:
    """Create every known collection and its indexes if missing."""
    db = get_db()
    existing = db.list_collection_names()
    for name in COLLECTIONS:
        if name not in existing:
            db.create_collection(name)
    db["sources"].create_index([("horizon", ASCENDING)])
    db["sources"].create_index([("access", ASCENDING)])
    db["runs"].create_index([("run_start_date_time", ASCENDING)])
    db["documents"].create_index([("run_id", ASCENDING)])
    db["documents"].create_index([("end_url", ASCENDING), ("scraped_at", ASCENDING)])
    db["documents"].create_index([("technologies_resolved", ASCENDING)])
    db["documents"].create_index([("signals.signal_id", ASCENDING)])
    db["documents"].create_index([("ignored_by", ASCENDING)])
    db["documents"].create_index([("signals_hash", ASCENDING)])
    db["documents"].create_index([("is_stub", ASCENDING), ("scraped_at", ASCENDING)])  # time windows
    db["technologies"].create_index([("doc_count", ASCENDING)])
    db["scoring_runs"].create_index([("started_at", ASCENDING)])
    db["assessments"].create_index([("scoring_run_id", ASCENDING)])
    db["assessments"].create_index([("tech_id", ASCENDING)])
    db["assessments"].create_index([("evidence_runs", ASCENDING)])
    db["povs"].create_index([("scoring_run_id", ASCENDING)])
    db["llm_calls"].create_index([("run_id", ASCENDING)])
    db["llm_calls"].create_index([("at", ASCENDING)])
    db["decisions"].create_index([("tech_id", ASCENDING), ("kind", ASCENDING), ("active", ASCENDING)])
    db["classify_runs"].create_index([("started_at", ASCENDING)])
    db["imports"].create_index([("at", ASCENDING)])
    db["find_evidence_jobs"].create_index([("at", ASCENDING)])


def backfill() -> None:
    """Fill fields that older records lack, once (idempotent): Points of View
    written before their time zone was recorded show in the radar's default."""
    from app.services.settings_store import radar_settings

    zone = radar_settings()["default_time_zone"]
    done = get_db()["povs"].update_many({"composed_tz": {"$exists": False}},
                                        {"$set": {"composed_tz": zone}}).modified_count
    if done:
        log.info("backfill: %d Points of View marked as written in %s", done, zone)


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
    if seeding.load_if_new():
        log.info("seeding data loaded into %r", settings.mongo_db)
    backfill()
    counts = {c: get_db()[c].estimated_document_count() for c in sorted(COLLECTIONS)}
    log.info("database %r ready (%s)", settings.mongo_db, counts)
