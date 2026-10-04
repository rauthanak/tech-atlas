"""The analyzer's deterministic engine (Phase C).

A scoring run is decoupled from scout runs: it works on whatever the latest
resolve stamped, under a config snapshot frozen at start — admin edits made
mid-run cannot tear it. Per technology: build the evidence dossier (every
stamped document's summary, no doc cap, token guard only), gate which fabrics
apply (one call, fail-open), then score every enabled measure per relevant
fabric — the measure list comes from the snapshot, so the "12" is data, not
code. TORA axes are weighted means over the scored measures with weights
renormalized; an unscorable measure is excluded, never zero, and the axis is
marked partial. Roll-ups are recomputable later from stored scores without
any LLM call."""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from agent.analyzer.placement import compute_placement
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM, call_with_backoff, parse_json
from app.services.prompts.store import PromptStore
from app.settings import get_settings

log = logging.getLogger(__name__)

RUNNING_STATES = {"running", "terminating"}
TORA_AXES = ("market_potential", "strategic_fit", "adoption_readiness")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── run lifecycle ────────────────────────────────────────────────────

def active_scoring_run_id() -> str | None:
    doc = get_collection("scoring_runs").find_one(
        {"status": {"$in": list(RUNNING_STATES)}}, {"_id": 1})
    return doc["_id"] if doc else None


def create_scoring_run(params: dict) -> str:
    """Freeze the method: measures, fabrics and scoring_config are copied into
    the run document and every call in this run renders from the copy."""
    run_id = uuid.uuid4().hex[:12]
    snapshot = {
        "measures": list(get_collection("measures").find()),
        "fabrics": list(get_collection("fabrics").find({"enabled": True})),
        "scoring_config": list(get_collection("scoring_config").find()),
    }
    techs = _select_technologies(params)
    get_collection("scoring_runs").insert_one({
        "_id": run_id,
        "status": "running",
        "stage": "preparing",
        "stage_history": [{"stage": "preparing", "at": _now()}],
        "params": params,
        "snapshot": snapshot,
        "technologies": [{"tech_id": t["_id"], "name": t["name"],
                          "doc_count": t.get("doc_count", 0)} for t in techs],
        "progress": {"techs_total": len(techs), "techs_done": 0, "llm_calls": 0},
        "started_at": _now(),
    })
    return run_id


def _select_technologies(params: dict) -> list[dict]:
    coll = get_collection("technologies")
    if params.get("technologies"):
        return list(coll.find({"_id": {"$in": params["technologies"]}, "enabled": True}))
    query: dict = {"enabled": True}
    if params.get("min_docs"):
        query["doc_count"] = {"$gte": int(params["min_docs"])}
    cursor = coll.find(query).sort("doc_count", -1)
    if params.get("top"):  # optional budget cap — omitted means every qualifying tech
        cursor = cursor.limit(int(params["top"]))
    return list(cursor)


def cancelled(run_id: str) -> bool:
    doc = get_collection("scoring_runs").find_one({"_id": run_id}, {"status": 1})
    return doc is None or doc["status"] != "running"


def request_terminate(run_id: str) -> bool:
    result = get_collection("scoring_runs").update_one(
        {"_id": run_id, "status": "running"}, {"$set": {"status": "terminating"}})
    return result.modified_count == 1


def set_stage(run_id: str, stage: str) -> None:
    get_collection("scoring_runs").update_one(
        {"_id": run_id},
        {"$set": {"stage": stage},
         "$push": {"stage_history": {"stage": stage, "at": _now()}}})


def finish(run_id: str, status: str, error: str | None = None) -> None:
    set_stage(run_id, "done")
    get_collection("scoring_runs").update_one({"_id": run_id}, {"$set": {
        "status": status, "error": error, "finished_at": _now()}})


def _bump(run_id: str, **inc) -> None:
    get_collection("scoring_runs").update_one(
        {"_id": run_id},
        {"$inc": {f"progress.{k}": v for k, v in inc.items()},
         "$set": {"heartbeat": _now()}})


def reconcile_stale_scoring_runs() -> None:
    """A 'running' scoring run at boot died with the last process."""
    result = get_collection("scoring_runs").update_many(
        {"status": {"$in": list(RUNNING_STATES)}},
        {"$set": {"status": "terminated", "error": "interrupted — found running at start-up",
                  "finished_at": _now()}})
    if result.modified_count:
        log.warning("reconciled %d stale scoring run(s)", result.modified_count)


def shutdown() -> None:
    result = get_collection("scoring_runs").update_many(
        {"status": {"$in": list(RUNNING_STATES)}},
        {"$set": {"status": "terminated", "error": "interrupted — service shutdown",
                  "finished_at": _now()}})
    if result.modified_count:
        log.warning("shutdown: marked %d scoring run(s) terminated", result.modified_count)


# ── evidence dossier ─────────────────────────────────────────────────

def build_dossier(tech_name: str, max_tokens: int) -> dict:
    """Every stamped document's summary — full dossier, no doc cap. Deduped by
    URL keeping the newest visit. The token ceiling is a guard for
    pathological volume only: oldest entries drop first, and the dossier says
    so. Returns the `text` with what it read: `pages`, the page versions (an
    unchanged revisit counts as the version it repeats); `runs`, the
    collection runs those visits came from; and `from`, the newest-visit time
    of the oldest page read, set only when the guard dropped pages."""
    seen: dict[str, dict] = {}
    for d in get_collection("documents").find(
            {"technologies_resolved": tech_name},
            {"end_url": 1, "title": 1, "kind": 1, "published_date": 1,
             "scraped_at": 1, "summary_text": 1, "scout_take": 1,
             "source_id": 1, "run_id": 1, "is_stub": 1, "ref_doc_id": 1}).sort("scraped_at", -1):
        seen.setdefault(d.get("end_url") or str(d["_id"]), d)
    kept, pages, runs, cutoff, last_visit = [], [], set(), None, None
    total_chars, budget = 0, max_tokens * 4  # ~4 chars per token
    for d in seen.values():  # newest first; oldest fall off if the guard trips
        lines = [f"- [{d.get('kind') or 'article'}] {d.get('title') or d.get('end_url')}",
                 f"  url: {d.get('end_url')} · source: {d.get('source_id')}"
                 f" · published: {d.get('published_date') or 'n/a'}"
                 f" · extracted: {str(d.get('scraped_at'))[:10]}"]
        if d.get("summary_text"):
            lines.append(f"  summary: {d['summary_text']}")
        if d.get("scout_take"):
            lines.append(f"  scout take: {d['scout_take']}")
        text = "\n".join(lines)
        if total_chars + len(text) > budget:
            kept.append(f"[dossier truncated at ~{max_tokens} tokens — "
                        f"{len(seen) - len(pages)} oldest entries omitted]")
            cutoff = last_visit
            break
        kept.append(text)
        total_chars += len(text)
        pages.append(d["ref_doc_id"] if d.get("is_stub") and d.get("ref_doc_id") else d["_id"])
        last_visit = d.get("scraped_at")
        if d.get("run_id"):
            runs.add(d["run_id"])
    return {"text": "\n\n".join(kept), "pages": pages, "runs": sorted(runs), "from": cutoff}


# ── scoring ──────────────────────────────────────────────────────────

def _ask_json(llm: LLM, rendered: str, run_id: str):
    """One scoring call. A bad reply gets one retry; provider errors (rate
    limits above all — six parallel dossier-sized calls can burst the TPM
    cap) back off and retry rather than killing the whole run."""
    def call() -> str:
        _bump(run_id, llm_calls=1)
        return llm.ask(rendered)

    for attempt in (1, 2):
        reply = call_with_backoff(call, lambda: cancelled(run_id))
        try:
            return parse_json(reply)
        except ValueError as exc:
            log.warning("scoring call returned bad JSON (attempt %d): %s", attempt, exc)
    return None


def _relevant_fabrics(llm: LLM, run_id: str, tech_name: str,
                      fabrics: list[dict], dossier: str) -> list[dict]:
    """Which fabrics is this technology assessed in? One call, fail-open to
    all enabled fabrics — a gate failure must widen scoring, never narrow it."""
    try:
        prompt = PromptStore.get("fabric_relevance")
        listing = "\n".join(f"- {f['_id']}: {f['name']} — {f['definition']}" for f in fabrics)
        data = _ask_json(llm, prompt.render(
            technology=tech_name, fabrics=listing, evidence=dossier), run_id)
        ids = set(data.get("fabrics", [])) if isinstance(data, dict) else set()
        chosen = [f for f in fabrics if f["_id"] in ids]
        if chosen:
            return chosen
    except Exception:
        log.exception("fabric relevance gate failed for %s", tech_name)
    return fabrics


def _score_measure(llm: LLM, run_id: str, measure: dict, tech_name: str,
                   fabric: dict, dossier: str) -> dict:
    anchors = measure.get("anchors", {})
    rendered = PromptStore.get("measure_scoring").render(
        measure_name=f"{measure.get('code')} {measure.get('name')}",
        definition=measure.get("definition", ""),
        anchors="\n".join(f"{k}: {v}" for k, v in anchors.items()),
        required_evidence=measure.get("required_evidence", ""),
        technology=tech_name,
        fabric_name=fabric.get("name", ""),
        fabric_definition=fabric.get("definition", ""),
        tcl_today=fabric.get("tcl_today") or "Not described.",  # TCL's side of the TCL-position measures
        evidence=dossier,
    )
    data = _ask_json(llm, rendered, run_id)
    if not isinstance(data, dict):
        return {"score": None, "unscorable": True,
                "missing": "scoring call failed — re-score to retry",
                "justification": None, "evidence_urls": [], "counter_case": None}
    score = data.get("score")
    if isinstance(score, (int, float)):
        score = max(0, min(10, round(float(score), 1)))
    else:
        score = None
    result = {
        "score": score,
        "justification": data.get("justification"),
        "evidence_urls": data.get("evidence_urls") or [],
        "counter_case": data.get("counter_case"),
        "unscorable": bool(data.get("unscorable")) or score is None,
        "missing": data.get("missing"),
    }
    if result["score"] is not None and not result["evidence_urls"]:
        # the prompt's own rule: a score without citations is invalid
        result.update(score=None, unscorable=True,
                      missing="model scored without citing dossier URLs")
    return result


def rollup_tora(measure_results: dict[str, dict], measures: list[dict]) -> dict:
    """Deterministic TORA roll-up. Weighted mean per axis over the measures
    that scored, weights renormalized; unscorable excluded, never zero; the
    axis is partial when any of its measures is missing."""
    tora: dict[str, dict] = {}
    for axis in TORA_AXES:
        axis_measures = [m for m in measures if m.get("axis") == axis]
        scored = [(m.get("weight") or 0, measure_results[m["_id"]]["score"])
                  for m in axis_measures
                  if m["_id"] in measure_results
                  and measure_results[m["_id"]]["score"] is not None]
        weight_sum = sum(w for w, _ in scored)
        tora[axis] = {
            "score": round(sum(w * s for w, s in scored) / weight_sum, 2)
            if weight_sum > 0 else None,
            "scored": len(scored),
            "of": len(axis_measures),
            "partial": len(scored) < len(axis_measures),
        }
    return tora


def assess_technology(run_id: str, tech_id: str, llm: LLM,
                      executor: ThreadPoolExecutor) -> str:
    """Score one technology across its relevant fabrics — the unit of work the
    analyzer agent (and the deterministic sweep) invokes."""
    run = get_collection("scoring_runs").find_one({"_id": run_id})
    if run is None:
        return f"unknown scoring run {run_id}"
    entry = next((t for t in run["technologies"] if t["tech_id"] == tech_id), None)
    if entry is None:
        return f"{tech_id} is not part of this scoring run"
    snapshot = run["snapshot"]
    measures = snapshot["measures"]
    fabrics = snapshot["fabrics"]
    evidence_cfg = next((c for c in snapshot["scoring_config"]
                         if c["_id"] == "evidence"), {})
    max_tokens = int(evidence_cfg.get("max_dossier_tokens", 300000))

    built = build_dossier(entry["name"], max_tokens)
    dossier = built["text"]
    if not dossier:
        _record_skip(run_id, entry, "no evidence — no documents stamped with this technology")
        return f"{entry['name']}: skipped, no evidence"

    # the gate's verdict is stored on the run, so a resume knows exactly which
    # fabrics are owed without re-gating (and without missing one)
    gated_ids = run.get("gates", {}).get(tech_id)
    if gated_ids is None:
        gated = _relevant_fabrics(llm, run_id, entry["name"], fabrics, dossier)
        gated_ids = [f["_id"] for f in gated]
        get_collection("scoring_runs").update_one(
            {"_id": run_id}, {"$set": {f"gates.{tech_id}": gated_ids}})
    assessed = []
    for fabric in [f for f in fabrics if f["_id"] in gated_ids]:
        if cancelled(run_id):
            break
        existing = get_collection("assessments").find_one(
            {"_id": f"{run_id}:{tech_id}:{fabric['_id']}"}, {"_id": 1})
        if existing:
            continue  # agent already did it; the sweep must not redo it
        futures = {m["_id"]: executor.submit(
            _score_measure, llm, run_id, m, entry["name"], fabric, dossier)
            for m in measures}
        results = {mid: f.result() for mid, f in futures.items()}
        get_collection("assessments").insert_one({
            "_id": f"{run_id}:{tech_id}:{fabric['_id']}",
            "scoring_run_id": run_id,
            "tech_id": tech_id,
            "technology": entry["name"],
            "fabric_id": fabric["_id"],
            "fabric": fabric.get("name"),
            "doc_count": len(built["pages"]),  # pages actually read, after the size guard
            "evidence_runs": built["runs"],  # the collection runs whose pages the scorer read
            "dossier_pages": built["pages"],  # the page versions read: new evidence is any other
            **({"dossier_from": built["from"]} if built["from"] else {}),
            "measures": {mid: {**results[mid],
                               "code": next((m.get("code") for m in measures
                                             if m["_id"] == mid), mid)}
                         for mid in results},
            "tora": rollup_tora(results, measures),
            "placement": compute_placement(results, snapshot["scoring_config"]),
            # compact copy of the outside-TORA scores so list views can show
            # them without shipping the full measure payloads
            "extras": {m["code"]: results[m["_id"]]["score"]
                       for m in measures
                       if str(m.get("code", "")).startswith("X") and m["_id"] in results},
            "tora_basis": "scored",
            "created_at": _now(),
        })
        assessed.append(fabric.get("name"))

    # watch metrics — one call per technology per run (fabric-independent),
    # copied onto each of its assessments; skipped when already present so a
    # resume never re-spends it
    has_watch = get_collection("assessments").find_one(
        {"scoring_run_id": run_id, "tech_id": tech_id,
         "watch_metrics": {"$exists": True}}, {"_id": 1})
    if not has_watch and not cancelled(run_id) and \
            get_collection("assessments").count_documents(
                {"scoring_run_id": run_id, "tech_id": tech_id}) > 0:
        metrics: list = []
        try:
            data = _ask_json(llm, PromptStore.get("watch_metrics").render(
                technology=entry["name"], evidence=dossier), run_id)
            if isinstance(data, list):
                metrics = [m for m in data if isinstance(m, dict) and m.get("metric")]
        except Exception:
            log.exception("watch metrics failed for %s", entry["name"])
        get_collection("assessments").update_many(
            {"scoring_run_id": run_id, "tech_id": tech_id},
            {"$set": {"watch_metrics": metrics}})

    done = len(get_collection("assessments").distinct("tech_id", {"scoring_run_id": run_id}))
    done += len(get_collection("scoring_runs").find_one(
        {"_id": run_id}, {"skipped": 1}).get("skipped", []))
    get_collection("scoring_runs").update_one(
        {"_id": run_id},
        {"$set": {"progress.techs_done": done, "heartbeat": _now()}})
    return f"{entry['name']}: assessed in {', '.join(assessed) or 'no new fabrics'}"


def _record_skip(run_id: str, entry: dict, reason: str) -> None:
    get_collection("scoring_runs").update_one(
        {"_id": run_id}, {"$push": {"skipped": {"tech_id": entry["tech_id"],
                                                "name": entry["name"],
                                                "reason": reason}},
                          "$inc": {"progress.techs_done": 1}})


def recompute_run(run_id: str) -> int:
    """Re-derive every TORA roll-up AND placement in a run from its stored
    measure scores using the CURRENT weights, cut-points and horizon map — a
    config edit needs no LLM."""
    run = get_collection("scoring_runs").find_one({"_id": run_id}, {"_id": 1})
    if run is None:
        raise KeyError(f"unknown scoring run {run_id!r}")
    measures = list(get_collection("measures").find())
    config = list(get_collection("scoring_config").find())
    count = 0
    for a in get_collection("assessments").find({"scoring_run_id": run_id}):
        get_collection("assessments").update_one(
            {"_id": a["_id"]},
            {"$set": {"tora": rollup_tora(a["measures"], measures),
                      "placement": compute_placement(a["measures"], config),
                      "tora_basis": f"recomputed {_now()}"}})
        count += 1
    return count
