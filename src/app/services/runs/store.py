"""Run + document storage. Owns the two-collection schema:

runs       — one small doc per run: status, timings, per-source stats, and
             the snapshot it used (signal list + hash, crawl settings).
documents  — one doc per collected page: text, summary, signals, cross-run
             references.

Dedupe: a page whose extracted text hash matches its latest stored version is
saved as a stub referencing that document instead of storing the text again.
Retention: superseded raw text older than the last KEEP_FULL_TEXT_RUNS runs is
pruned; the latest full text per end_url and every summary are kept forever.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from app.services.db.mongo import get_collection
from app.settings import get_settings

log = logging.getLogger(__name__)

RUNNING_STATES = ("running", "terminating")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── runs ─────────────────────────────────────────────────────────────

def create_run(params: dict, snapshot: dict) -> str:
    """`snapshot` is what the run uses throughout: signal_list,
    signals_hash and crawl_settings (services/signals/snapshot.build)."""
    run_id = uuid.uuid4().hex[:12]
    get_collection("runs").insert_one({
        "_id": run_id,
        "status": "running",
        "stage": "starting",
        "stage_history": [],
        "substage_history": [],
        "params": params,
        "run_start_date_time": now(),
        "run_end_date_time": None,
        "heartbeat_at": now(),
        "error": None,
        "totals": {"sources": 0, "pages_visited": 0, "documents": 0, "new_documents": 0,
                   "signals": 0, "other_signals": 0, "set_aside": 0},
        "sources": [],  # per-source stats only — the bulk lives in `documents`
        **snapshot,
    })
    return run_id


def set_stage(run_id: str, stage: str) -> None:
    """Move the run to a flow stage (status stays the lifecycle field)."""
    get_collection("runs").update_one(
        {"_id": run_id},
        {"$set": {"stage": stage},
         "$push": {"stage_history": {"stage": stage, "at": now()}}})


def set_substage(run_id: str, stage: str, substage: str) -> None:
    """Record a sub-stage event under a flow stage — feeds the portal's
    drill-down timeline. Append-only; the parent stage stays in `stage`."""
    get_collection("runs").update_one(
        {"_id": run_id},
        {"$push": {"substage_history": {"stage": stage, "substage": substage, "at": now()}}})


def heartbeat(run_id: str) -> None:
    get_collection("runs").update_one({"_id": run_id}, {"$set": {"heartbeat_at": now()}})


def run_status(run_id: str) -> str | None:
    doc = get_collection("runs").find_one({"_id": run_id}, {"status": 1})
    return doc["status"] if doc else None


def cancelled(run_id: str) -> bool:
    return run_status(run_id) not in ("running",)


def finish_run(run_id: str, status: str, error: str | None = None) -> None:
    get_collection("runs").update_one(
        {"_id": run_id},
        {"$set": {"status": status, "error": error, "run_end_date_time": now()}},
    )


def start_source(run_id: str, category: str, source: dict) -> None:
    get_collection("runs").update_one({"_id": run_id}, {
        "$push": {"sources": {
            "category": category,
            "source_id": source["source_id"],
            "source_url": source["url"],
            "source_name": source["name"],
            "source_start_date_time": now(),
            "source_end_date_time": None,
            "pages_visited": 0,
            "documents": 0,
            "new_documents": 0,
            "error": None,
            "incomplete": False,
            "incomplete_note": None,
        }},
        "$inc": {"totals.sources": 1},
    })


def bump_source(run_id: str, source_id: str, pages: int = 0, docs: int = 0,
                new_docs: int = 0, signals: int = 0, other_signals: int = 0,
                set_aside: int = 0) -> None:
    """Live per-page increment of a source's counters (and the run totals),
    so the portal ticks while the crawl works. Doubles as a heartbeat. The
    signal counts cover new or changed pages only: "signals in this run"
    means signals that are new in this run."""
    get_collection("runs").update_one(
        {"_id": run_id, "sources.source_id": source_id},
        {"$inc": {
            "sources.$.pages_visited": pages,
            "sources.$.documents": docs,
            "sources.$.new_documents": new_docs,
            "totals.pages_visited": pages,
            "totals.documents": docs,
            "totals.new_documents": new_docs,
            "totals.signals": signals,
            "totals.other_signals": other_signals,
            "totals.set_aside": set_aside,
        },
         "$set": {"heartbeat_at": now()}},
    )


def signal_counts(analysis: dict | None) -> dict:
    """bump_source's signal counters for one page's analysis (None: a stub)."""
    if not analysis:
        return {}
    hits = analysis.get("signals") or []
    other = sum(1 for h in hits if h.get("signal_id") == "other")
    return {"signals": len(hits) - other, "other_signals": other,
            "set_aside": int(bool(analysis.get("ignored_by")))}


def finish_source(run_id: str, source_id: str, pages: int, docs: int, new_docs: int,
                  error: str | None = None, incomplete_note: str | None = None) -> None:
    """Close a source's row. Counters accumulated live via bump_source; the
    scout's absolute counts reconcile the per-source row (totals keep the
    live-accumulated values — any drift there would mean a missed bump).
    `incomplete_note` says what was left for lack of budget, e.g. "didn't
    finish: 120 links left" or "25 still to collect"."""
    get_collection("runs").update_one(
        {"_id": run_id, "sources.source_id": source_id},
        {"$set": {
            "sources.$.source_end_date_time": now(),
            "sources.$.pages_visited": pages,
            "sources.$.documents": docs,
            "sources.$.new_documents": new_docs,
            "sources.$.error": error,
            "sources.$.incomplete": bool(incomplete_note),
            "sources.$.incomplete_note": incomplete_note,
        }},
    )


def reconcile_stale_runs() -> None:
    """Startup: only this process runs runs, so anything still 'running' at
    boot died with a previous process — mark it terminated."""
    result = get_collection("runs").update_many(
        {"status": {"$in": list(RUNNING_STATES)}},
        {"$set": {"status": "terminated", "error": "interrupted — service restarted",
                  "run_end_date_time": now()}},
    )
    if result.modified_count:
        log.warning("reconciled %d stale running run(s) to terminated", result.modified_count)


# ── documents ────────────────────────────────────────────────────────

ANALYSIS_FIELDS = ("signals", "ignored_by", "signals_hash", "partial", "analysis_error")


def save_document(run_id: str, category: str, source: dict, end_url: str,
                  extracted_text: str, summarize, depth: int = 0,
                  meta: dict | None = None) -> dict | None:
    """Store one collected page. Returns its analysis when it carried new
    content, None when it was unchanged (stored as a stub, with no model
    call). `summarize(url, text)` returns the summarizing step's dict."""
    docs = get_collection("documents")
    meta = meta or {}
    content_hash = hashlib.sha256(extracted_text.encode()).hexdigest()
    previous = docs.find_one(
        {"end_url": end_url, "is_stub": False},
        sort=[("scraped_at", -1)],
    )

    base = {
        "_id": uuid.uuid4().hex,
        "run_id": run_id,
        "category": category,
        "source_id": source["source_id"],
        "source_url": source["url"],
        "end_url": end_url,
        "depth": depth,
        "kind": meta.get("kind", "article"),
        "title": meta.get("title"),
        "published_date": meta.get("published_date"),
        "content_hash": content_hash,
        "scraped_at": now(),
        "summary_from_previous_runs": previous.get("summary_text") if previous else None,
    }

    if previous and previous["content_hash"] == content_hash:
        # unchanged since last time — store a stub, not the text again
        # (an unchanged page is never paid for twice, but still shows its signals)
        docs.insert_one({**base, "is_stub": True, "ref_doc_id": previous["_id"],
                         "extracted_text": None, "text_pruned": False,
                         "summary_text": previous.get("summary_text"),
                         "technologies": previous.get("technologies", []),
                         "scout_take": previous.get("scout_take"),
                         **{f: previous.get(f) for f in ANALYSIS_FIELDS}})
        return None

    analysis = summarize(end_url, extracted_text)
    docs.insert_one({**base, "is_stub": False, "ref_doc_id": None,
                     "extracted_text": extracted_text, "text_pruned": False,
                     "summary_text": analysis["summary"],
                     "technologies": analysis["technologies"],
                     "scout_take": analysis["scout_take"],
                     "signals": analysis["signals"],
                     "ignored_by": analysis["ignored_by"],
                     "signals_hash": analysis["signals_hash"],
                     "parts": analysis["parts"],
                     "partial": analysis["partial"],
                     "analysis_error": analysis.get("analysis_error")})
    return analysis


def prune_old_text() -> None:
    """Retention: strip extracted_text from superseded documents outside the
    last KEEP_FULL_TEXT_RUNS runs. The latest full text per end_url survives."""
    runs = get_collection("runs")
    docs = get_collection("documents")
    keep = get_settings().keep_full_text_runs
    recent = [r["_id"] for r in runs.find({}, {"_id": 1})
              .sort("run_start_date_time", -1).limit(keep)]

    candidates = docs.find(
        {"run_id": {"$nin": recent}, "is_stub": False,
         "text_pruned": False, "extracted_text": {"$ne": None}},
        {"end_url": 1, "scraped_at": 1},
    )
    pruned = 0
    for doc in candidates:
        superseded = docs.find_one({
            "end_url": doc["end_url"], "is_stub": False,
            "scraped_at": {"$gt": doc["scraped_at"]},
        }, {"_id": 1})
        if superseded:  # a newer full version exists — this text has no remaining use
            docs.update_one({"_id": doc["_id"]},
                            {"$set": {"extracted_text": None, "text_pruned": True}})
            pruned += 1
    if pruned:
        log.info("retention: pruned text from %d superseded document(s)", pruned)
