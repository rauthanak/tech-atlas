"""PoV composer (Phase E). One LLM call per technology that NARRATES the
stored assessment data into the client's house-format sections — it never
scores. Every number in a PoV is copied from assessments (TORA roll-ups,
placement, watch metrics); the composer writes the prose around them, and an
unscorable measure becomes an explicit evidence-gap sentence, never a guess."""

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM
from app.services.prompts.store import PromptStore
from app.settings import get_settings

log = logging.getLogger(__name__)

SECTIONS = ("headline", "summary", "tora_analysis", "maturity", "market_view",
            "placement_rationale", "capability_gap", "evidence_gaps",
            "recommendation")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assessment_digest(assessments: list[dict]) -> str:
    """The composer's only source of truth: the stored scores, verbatim."""
    docs = max((a.get("doc_count") or 0) for a in assessments)
    blocks = [f"EVIDENCE BASE: {docs} source documents"]
    for a in assessments:
        lines = [f"FABRIC: {a['fabric']}"]
        for axis, v in a.get("tora", {}).items():
            lines.append(f"  TORA {axis}: {v['score'] if v['score'] is not None else 'UNSCORED'}"
                         f" ({v['scored']}/{v['of']} measures{' — partial' if v['partial'] else ''})")
        p = a.get("placement") or {}
        lines.append(f"  priority: {p.get('priority') or 'not placeable'}"
                     f" | by disruptiveness: {p.get('priority_by_disruptiveness') or '—'}"
                     f" | horizon: {p.get('horizon') or '—'}")
        for mid, m in sorted(a.get("measures", {}).items(), key=lambda x: x[1]["code"]):
            if m.get("unscorable"):
                lines.append(f"  {m['code']} {mid}: UNSCORABLE — missing: {m.get('missing')}")
            else:
                lines.append(f"  {m['code']} {mid}: {m['score']} — {m.get('justification')}")
                if m.get("counter_case"):
                    lines.append(f"    counter-case: {m['counter_case']}")
        blocks.append("\n".join(lines))
    wm = assessments[0].get("watch_metrics") or []
    if wm:
        blocks.append("WATCH METRICS:\n" + "\n".join(
            f"  - {m.get('metric')} | now: {m.get('current_value')} | "
            f"inflection: {m.get('inflection_threshold')} | implication: {m.get('implication')}"
            for m in wm))
    return "\n\n".join(blocks)


def compose_pov(run_id: str, tech_id: str) -> dict:
    """Compose (or recompose) the PoV for one technology in one scoring run.
    Raises KeyError when the run has no assessments for the technology."""
    assessments = list(get_collection("assessments")
                       .find({"scoring_run_id": run_id, "tech_id": tech_id})
                       .sort("fabric_id", 1))
    if not assessments:
        raise KeyError(f"no assessments for {tech_id!r} in scoring run {run_id!r}")
    technology = assessments[0]["technology"]

    prompt = PromptStore.get("pov")
    llm = LLM.initialize()
    rendered = prompt.render(technology=technology,
                             assessment_data=_assessment_digest(assessments))
    sections = None
    for attempt in (1, 2):
        try:
            data = json.loads(llm.ask(rendered))
            if isinstance(data, dict):
                sections = {k: data.get(k) for k in SECTIONS}
                break
        except json.JSONDecodeError as exc:
            log.warning("pov compose returned bad JSON (attempt %d): %s", attempt, exc)
    if sections is None:
        raise RuntimeError("PoV composition failed twice — try again")

    doc_id = f"{run_id}:{tech_id}"
    existing = get_collection("povs").find_one({"_id": doc_id}, {"version": 1})
    get_collection("povs").replace_one(
        {"_id": doc_id},
        {"_id": doc_id,
         "scoring_run_id": run_id,
         "tech_id": tech_id,
         "technology": technology,
         "sections": sections,
         "assessment_ids": [a["_id"] for a in assessments],
         "version": (existing or {}).get("version", 0) + 1,
         "composed_at": _now()},
        upsert=True)
    return get_collection("povs").find_one({"_id": doc_id})


# --- compose-all: one background job over every uncomposed technology -------

_batch_lock = threading.Lock()
_batch_active = False

_STALE_AFTER_S = 180  # a running job whose heartbeat is older than this died
                      # with the process — surface it as interrupted


def batch_status() -> dict | None:
    """The latest compose-all job, for the Points of View tab's polling."""
    job = get_collection("pov_compose_jobs").find_one(sort=[("started_at", -1)])
    if job and job["status"] == "running" and not _batch_active:
        last = job.get("heartbeat_at") or job["started_at"]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
        if age > _STALE_AFTER_S:
            get_collection("pov_compose_jobs").update_one(
                {"_id": job["_id"], "status": "running"},
                {"$set": {"status": "interrupted", "current": [],
                          "finished_at": _now()}})
            job["status"], job["current"] = "interrupted", []
    return job


def start_compose_all(targets: list[dict], recompose: bool = False) -> str | None:
    """Compose PoVs for every (scoring_run_id, tech_id) in targets, in a
    background thread pool. None when a job is already running. `recompose`
    is recorded on the job so the portal can badge composed rows as queued."""
    global _batch_active
    with _batch_lock:
        if _batch_active:
            return None
        _batch_active = True
    job_id = uuid.uuid4().hex[:12]
    get_collection("pov_compose_jobs").insert_one(
        {"_id": job_id, "status": "running", "recompose": recompose,
         "total": len(targets), "done": 0,
         "current": [], "failed": [], "started_at": _now(),
         "heartbeat_at": _now()})
    threading.Thread(target=_run_batch, args=(job_id, targets),
                     name=f"pov-batch-{job_id}", daemon=True).start()
    return job_id


def _run_batch(job_id: str, targets: list[dict]) -> None:
    global _batch_active
    jobs = get_collection("pov_compose_jobs")

    def one(t: dict) -> None:
        jobs.update_one({"_id": job_id},
                        {"$push": {"current": t["tech_id"]},
                         "$set": {"heartbeat_at": _now()}})
        update: dict = {"$inc": {"done": 1},
                        "$pull": {"current": t["tech_id"]},
                        "$set": {"heartbeat_at": _now()}}
        try:
            compose_pov(t["scoring_run_id"], t["tech_id"])
        except Exception as exc:
            log.exception("compose-all: %s failed", t["tech_id"])
            update["$push"] = {"failed": {"tech_id": t["tech_id"],
                                          "scoring_run_id": t["scoring_run_id"],
                                          "error": str(exc)}}
        jobs.update_one({"_id": job_id}, update)

    try:
        with ThreadPoolExecutor(max_workers=get_settings().scoring_concurrency,
                                thread_name_prefix="pov") as executor:
            list(executor.map(one, targets))
        jobs.update_one({"_id": job_id},
                        {"$set": {"status": "completed", "current": [],
                                  "finished_at": _now()}})
    except Exception as exc:
        jobs.update_one({"_id": job_id},
                        {"$set": {"status": "failed", "error": str(exc),
                                  "current": [], "finished_at": _now()}})
    finally:
        _batch_active = False
