"""Once, for a database stored before 24 Oct 2026 (scale plan, spec §11): each
visit gets its page key and newest-visit mark (services/pages), and its text
moves to page_texts, by the same steps storing uses; then every technology's
pages are counted again. The API runs it at start-up, before it answers,
while visits without a page key exist (the worker waits for it); a restart
carries on with those, oldest first."""

import logging
import time

from app.services import page_texts, pages
from app.services.db.mongo import get_collection

log = logging.getLogger(__name__)

BATCH = 2_000
OLD = {"page_key": {"$exists": False}}
KEYED = [("page_key", 1), ("scraped_at", -1)]


def _one(d: dict) -> None:
    docs = get_collection("documents")
    key = pages.key_for(d["end_url"], d.get("title"), d.get("content_hash") or "")
    newest = not docs.count_documents({"page_key": key, "scraped_at": {"$gt": d["scraped_at"]}})
    text = d.get("extracted_text")
    if text and not d.get("is_stub"):
        page_texts.put(d["_id"], text, key, d.get("run_id"))
    docs.update_one({"_id": d["_id"]}, {"$set": {"page_key": key, "latest": newest, "visits": pages.visits(key) + 1,
                                                 "has_text": bool(text) and not d.get("is_stub")},
                                        "$unset": {"extracted_text": ""}})
    if newest:
        pages.mark_newest({"page_key": key, "scraped_at": d["scraped_at"]})


def pending() -> bool:
    """Visits stored before the upgrade are still there (quick: in an old database the first one found is)."""
    return get_collection("documents").find_one(OLD, {"_id": 1}) is not None


def run() -> int:
    """Upgrade every visit still without a page key; returns how many."""
    from agent.resolver.resolver import recompute_stats
    if not pending():
        return 0
    docs = get_collection("documents")
    docs.create_index(KEYED)  # the lookups each step makes (seeds/indexes.json)
    docs.create_index([("content_hash", 1)])
    get_collection("page_texts").create_index([("page_key", 1)])
    total = docs.count_documents(OLD)
    log.info("upgrading %d page records (once): page keys, newest visits, text kept apart", total)
    done, started = 0, time.monotonic()
    while batch := list(docs.find(OLD, {"end_url": 1, "title": 1, "content_hash": 1, "scraped_at": 1, "run_id": 1,
                                        "is_stub": 1, "extracted_text": 1})
                        .sort("scraped_at", 1).hint(KEYED).limit(BATCH)):  # visits without a key sit together in it
        for d in batch:
            _one(d)
        done += len(batch)
        log.info("upgraded %d of %d page records (%.0f s)", done, total, time.monotonic() - started)
    recompute_stats()  # pages are counted by page now: every technology's counts, and its stored answers after them
    log.info("page counts worked out again (%.0f s)", time.monotonic() - started)
    return done
