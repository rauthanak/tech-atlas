"""Jobs that must not overlap. A re-check rewrites stored summaries, so it
never runs alongside a collection run or a scoring run, which read or write
them. Collection and scoring may still overlap, as before, because
collecting only adds pages.

Each start checks the others' recorded status and starts under one lock, so
two starts can't slip past each other."""

import threading

from app.services.db.mongo import get_collection

start_lock = threading.Lock()

_ACTIVE = {
    "collection": ("runs", {"status": {"$in": ["running", "terminating"]}},
                   "A collection run is in progress."),
    "scoring": ("scoring_runs", {"status": {"$in": ["running", "terminating"]}},
                "An assessment run is in progress."),
    "recheck": ("recheck_jobs", {"status": "running"},
                "A check of stored pages is in progress."),
}


class Busy(Exception):
    """A job can't start now; the message says why, in plain words."""


def reason(*kinds: str) -> str | None:
    """The first of `kinds` that is active, as a sentence; None when free."""
    for kind in kinds:
        collection, query, sentence = _ACTIVE[kind]
        if get_collection(collection).find_one(query, {"_id": 1}):
            return sentence
    return None
