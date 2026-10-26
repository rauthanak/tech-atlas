"""Run + document storage. Owns the two-collection schema:

runs       — one small doc per run: status, timings, per-source stats, and
             the snapshot it used (signal list + hash, crawl settings).
documents  — one doc per visit of a page: summary, signals, cross-run
             references. Which page it is of: `page_key` (services/pages);
             its full text is kept apart (services/page_texts).

Dedupe: a page whose extracted text hash matches its latest stored version is
saved as a stub referencing that document instead of storing the text again.
Retention: superseded raw text older than the last KEEP_FULL_TEXT_RUNS runs is
pruned; the latest full text per page and every summary are kept forever.
"""

import hashlib
import logging
import re
import uuid

from app.services.db.mongo import get_collection
from app.services.timezone import now_utc
from app.settings import get_settings
from app.services import briefing_days, page_texts, pages

log = logging.getLogger(__name__)

RUNNING_STATES = ("running", "terminating")

# A Find evidence job stores its pages under a run too, but it isn't a
# collection: every "latest collection" lookup filters with this.
COLLECTIONS = {"params.kind": {"$ne": "find_evidence"}}


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
        "run_start_date_time": now_utc(),
        "run_end_date_time": None,
        "heartbeat_at": now_utc(),
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
         "$push": {"stage_history": {"stage": stage, "at": now_utc()}}})


def set_substage(run_id: str, stage: str, substage: str) -> None:
    """Record a sub-stage event under a flow stage — feeds the portal's
    drill-down timeline. Append-only; the parent stage stays in `stage`."""
    get_collection("runs").update_one(
        {"_id": run_id},
        {"$push": {"substage_history": {"stage": stage, "substage": substage, "at": now_utc()}}})


def heartbeat(run_id: str) -> None:
    get_collection("runs").update_one({"_id": run_id}, {"$set": {"heartbeat_at": now_utc()}})


def run_status(run_id: str) -> str | None:
    doc = get_collection("runs").find_one({"_id": run_id}, {"status": 1})
    return doc["status"] if doc else None


def cancelled(run_id: str) -> bool:
    return run_status(run_id) not in ("running",)


def finish_run(run_id: str, status: str, error: str | None = None) -> None:
    get_collection("runs").update_one(
        {"_id": run_id},
        {"$set": {"status": status, "error": error, "run_end_date_time": now_utc()}},
    )


def start_source(run_id: str, category: str, source: dict) -> None:
    get_collection("runs").update_one({"_id": run_id}, {
        "$push": {"sources": {
            "category": category,
            "source_id": source["source_id"],
            "source_url": source["url"],
            "source_name": source["name"],
            "source_start_date_time": now_utc(),
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
         "$set": {"heartbeat_at": now_utc()}},
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
                  error: str | None = None, incomplete_note: str | None = None,
                  skipped: list[dict] | None = None) -> None:
    """Close a source's row. Counters accumulated live via bump_source; the
    scout's absolute counts reconcile the per-source row (totals keep the
    live-accumulated values — any drift there would mean a missed bump).
    `incomplete_note` says what was left for lack of budget, e.g. "didn't
    finish: 120 links left" or "25 still to collect". `skipped`: pages and
    links left out because they couldn't be read, by reason (Outcome.skip)."""
    get_collection("runs").update_one(
        {"_id": run_id, "sources.source_id": source_id},
        {"$set": {
            "sources.$.source_end_date_time": now_utc(),
            "sources.$.pages_visited": pages,
            "sources.$.documents": docs,
            "sources.$.new_documents": new_docs,
            "sources.$.error": error,
            "sources.$.incomplete": bool(incomplete_note),
            "sources.$.incomplete_note": incomplete_note,
            "sources.$.skipped": skipped or [],
        }},
    )


def reconcile_stale_runs(keep=()) -> None:
    """Startup: only this process runs runs, so anything still 'running' at
    boot died with a previous process — mark it terminated, unless it's still
    waiting in the queue (`keep`)."""
    result = get_collection("runs").update_many(
        {"status": {"$in": list(RUNNING_STATES)}, "_id": {"$nin": list(keep)}},
        {"$set": {"status": "terminated", "error": "interrupted — service restarted",
                  "run_end_date_time": now_utc()}},
    )
    if result.modified_count:
        log.warning("reconciled %d stale running run(s) to terminated", result.modified_count)


# ── documents ────────────────────────────────────────────────────────

ANALYSIS_FIELDS = ("signals", "ignored_by", "signals_hash", "partial", "analysis_error")
SURROGATES = re.compile(r"[\ud800-\udfff]")


def clean_text(text: str | None) -> str | None:
    """Text as it can be stored: lone surrogates (left by broken entities such
    as &#xD83D; on a page) can't be encoded, so each becomes \ufffd."""
    return SURROGATES.sub("\ufffd", text) if text else text


def save_document(run_id: str, category: str, source: dict, end_url: str,
                  extracted_text: str, summarize, depth: int = 0,
                  meta: dict | None = None) -> dict | None:
    """Store one collected page. Returns its analysis when it carried new
    content, None when it was unchanged (stored as a stub, with no model
    call). `summarize(url, text)` returns the summarizing step's dict."""
    docs = get_collection("documents")
    meta = {**(meta or {}), "title": clean_text((meta or {}).get("title"))}
    extracted_text = clean_text(extracted_text)
    content_hash = hashlib.sha256(extracted_text.encode()).hexdigest()
    page_key = pages.key_for(end_url, meta.get("title"), content_hash)
    previous = docs.find_one(
        {"page_key": page_key, "is_stub": False},
        sort=[("scraped_at", -1)],
    )

    base = {
        "_id": uuid.uuid4().hex,
        "run_id": run_id,
        "category": category,
        "source_id": source["source_id"],
        "source_url": source["url"],
        "end_url": end_url,
        "page_key": page_key,
        "latest": True,
        "visits": pages.visits(page_key) + 1,
        "depth": depth,
        "kind": meta.get("kind", "article"),
        "title": meta.get("title"),
        "published_date": meta.get("published_date"),
        "content_hash": content_hash,
        "scraped_at": now_utc(),
        "summary_from_previous_runs": previous.get("summary_text") if previous else None,
    }

    if previous and previous["content_hash"] == content_hash:
        # unchanged since last time — store a stub, not the text again
        # (an unchanged page is never paid for twice, but still shows its signals),
        # linked as the version it repeats is
        docs.insert_one({**base, "is_stub": True, "ref_doc_id": previous["_id"],
                         "has_text": False, "text_pruned": False,
                         "summary_text": previous.get("summary_text"),
                         "technologies": previous.get("technologies", []),
                         "technologies_resolved": previous.get("technologies_resolved", []),
                         **({"to_organize": True} if previous.get("to_organize") else {}),  # linked with it
                         "scout_take": previous.get("scout_take"),
                         **{f: previous.get(f) for f in ANALYSIS_FIELDS}})
        pages.mark_newest(base)
        return None

    analysis = summarize(end_url, extracted_text)
    page_texts.put(base["_id"], extracted_text, page_key, run_id)
    docs.insert_one({**base, "is_stub": False, "ref_doc_id": None, "to_organize": True,  # for the next Organize
                     "has_text": True, "text_pruned": False,
                     "summary_text": analysis["summary"],
                     "technologies": analysis["technologies"],
                     "scout_take": analysis["scout_take"],
                     "signals": analysis["signals"],
                     "ignored_by": analysis["ignored_by"],
                     "signals_hash": analysis["signals_hash"],
                     "parts": analysis["parts"],
                     "partial": analysis["partial"],
                     "analysis_error": analysis.get("analysis_error")})
    pages.mark_newest(base)
    briefing_days.touch(base["scraped_at"])  # the Briefing works its day out again when next read
    return analysis


def prune_old_text() -> None:
    """Retention: delete the text of superseded versions outside the last
    KEEP_FULL_TEXT_RUNS runs. The latest full text per page survives."""
    recent = [r["_id"] for r in get_collection("runs").find({}, {"_id": 1})
              .sort("run_start_date_time", -1).limit(get_settings().keep_full_text_runs)]
    pruned = page_texts.prune(recent)
    if pruned:
        get_collection("documents").update_many({"_id": {"$in": pruned}},
                                                {"$set": {"has_text": False, "text_pruned": True}})
        log.info("retention: pruned text from %d superseded document(s)", len(pruned))
