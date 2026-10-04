"""PoV composer (Phase E). One LLM call per technology that NARRATES the
stored assessment data into the client's house-format sections — it never
scores. Every number in a PoV is copied from assessments (TORA roll-ups,
placement, watch metrics); the composer writes the prose around them, and an
unscorable measure becomes an explicit evidence-gap sentence, never a guess."""

import logging
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM, parse_json
from app.services.prompts.store import PromptStore
from app.settings import get_settings

log = logging.getLogger(__name__)

# one section per score, one for the other measures, then the priority: each
# measure is discussed once (before v4 of the skill: maturity, market_view and
# capability_gap, which retold the scores' measures)
SECTIONS = ("headline", "summary", "tora_analysis", "other_measures",
            "placement_rationale", "evidence_gaps", "recommendation")

AXES = {"market_potential": "Market Potential", "strategic_fit": "Strategic Fit",
        "adoption_readiness": "Adoption Readiness"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(x: float) -> str:
    """A score as the portal shows it: at most one decimal (8.0 → 8, 7.29 → 7.3)."""
    return f"{round(x, 1):g}"


def _site(url: str) -> str:
    return (urlparse(url).hostname or url).removeprefix("www.")


def _axis_line(name: str, v: dict | None) -> str:
    if not v:
        return f"  {name}: not assessed"
    if v.get("score") is None:
        return f"  {name}: no score (none of its {v.get('of')} measures had enough evidence)"
    rest = (f"from all {v['of']} measures" if v.get("scored") == v.get("of")
            else f"from only {v.get('scored')} of its {v.get('of')} measures")
    return f"  {name}: {_num(v['score'])} out of 10, {rest}"


def _priority_line(p: dict, inputs: dict[str, str]) -> str:
    """The priority and horizon, and the two things they're worked out from:
    how soon (`inputs["timeline"]`: the measures behind it) and how big."""
    def part(label: str, c: dict | None, names: str) -> str:
        c, src = c or {}, f" (from {names})" if names else ""
        if c.get("score") is None:
            return f"{label}{src} couldn't be worked out: {c.get('scored', 0)} of {c.get('of', '?')} inputs scored"
        band = f", {c['band']}" if c.get("band") else ""
        return f"{label}{src}: {_num(c['score'])}{band}, from {c.get('scored')} of {c.get('of')} inputs"
    rest = (f"{part('How soon', p.get('timeline'), inputs.get('timeline', ''))}. "
            f"{part('How big', p.get('potential'), inputs.get('potential', ''))}.")
    if p.get("priority"):
        return f"  Priority {p['priority']}, horizon {p.get('horizon') or 'not set'}. {rest}"
    return f"  Priority and horizon: not set. {rest}"


def _assessment_digest(assessments: list[dict], method: dict[str, dict], grid: dict | None = None,
                       read: set[str] | None = None) -> str:
    """The composer's only source of truth: the stored scores, in plain words.
    Each measure is named under its axis (`method`: the run's own frozen
    measures, by id), with what couldn't be scored and what would resolve it;
    then the priority and the measures behind it (`grid`: the run's own
    priority grid), and the sites the evidence comes from (`read`: the URLs of
    the pages the assessment read). No codes, so none can leak into the prose."""
    def names(ids: list[str] | None) -> str:
        return ", ".join((method.get(i) or {}).get("name") or i for i in ids or [])
    inputs = {"timeline": names((grid or {}).get("timeline_from")),
              "potential": names((grid or {}).get("potential_from"))}
    def from_sites(pages: set[str]) -> str:
        sites = Counter(_site(u) for u in pages)
        return (f"from {len(sites)} {'site' if len(sites) == 1 else 'sites'}: "
                + ", ".join(f"{s} ({n})" for s, n in sites.most_common()))
    docs = len(read) if read else max((a.get("doc_count") or 0) for a in assessments)
    urls = {u for a in assessments for m in (a.get("measures") or {}).values()
            for u in m.get("evidence_urls") or []}
    pages = f"{docs} pages read, {from_sites(read)}" if read else f"{docs} pages read"
    cited = (f"The scores cite {len(urls)} of them" + ("" if read else f", {from_sites(urls)}") if urls
             else "The scores cite none of them")
    blocks = [f"EVIDENCE: {pages}. {cited}."]
    for a in assessments:
        lines = [f"FABRIC: {a['fabric']}"]
        by_axis: dict[str, list[str]] = {}
        for mid, m in a.get("measures", {}).items():
            meta = method.get(mid) or {}
            name = meta.get("name") or mid.replace("-", " ").capitalize()
            if m.get("unscorable") or m.get("score") is None:
                text = f"    - {name}: not enough evidence. Would need: {m.get('missing') or 'not recorded'}"
            else:
                text = f"    - {name}: {_num(m['score'])}. {m.get('justification') or ''}".rstrip()
                if m.get("counter_case"):
                    text += f"\n      Counter-case: {m['counter_case']}"
            by_axis.setdefault(meta.get("axis") or "extra", []).append(text)
        for axis, name in AXES.items():
            lines.append(_axis_line(name, (a.get("tora") or {}).get(axis)))
            lines += by_axis.get(axis, [])
        if by_axis.get("extra"):
            lines.append("  Other measures (not part of the three scores):")
            lines += by_axis["extra"]
        lines.append(_priority_line(a.get("placement") or {}, inputs))
        blocks.append("\n".join(lines))
    wm = next((a["watch_metrics"] for a in assessments if a.get("watch_metrics")), [])  # one per technology
    if wm:
        blocks.append("SIGNS TO WATCH (suggested by the assessment, not tracked automatically):\n" + "\n".join(
            f"  - {m.get('metric')} | now: {m.get('current_value')} | threshold: {m.get('inflection_threshold')}"
            f" | if crossed: {m.get('implication')}" + (f" | source: {m['source']}" if m.get("source") else "")
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
    tech = get_collection("technologies").find_one({"_id": tech_id}, {"label": 1}) or {}
    # the run's own frozen method, so later Setup edits can't change what an old run meant
    snapshot = (get_collection("scoring_runs").find_one(
        {"_id": run_id}, {"snapshot.measures": 1, "snapshot.scoring_config": 1}) or {}).get("snapshot") or {}
    method = snapshot.get("measures") or list(get_collection("measures").find())
    config = snapshot.get("scoring_config") or list(get_collection("scoring_config").find())
    grid = next((c for c in config if c["_id"] == "priority_grid"), None)
    # the pages it read: the versions it recorded, or (older assessments) the
    # technology's linked pages, as the evidence builder picks them
    versions = [p for a in assessments for p in a.get("dossier_pages") or []]
    query = {"_id": {"$in": versions}} if versions else {"technologies_resolved": technology}
    read = {d.get("end_url") or str(d["_id"]) for d in get_collection("documents").find(query, {"end_url": 1})}

    prompt = PromptStore.get("pov")
    llm = LLM.initialize()
    rendered = prompt.render(technology=tech.get("label") or technology,
                             assessment_data=_assessment_digest(assessments, {m["_id"]: m for m in method}, grid, read))
    sections = None
    for attempt in (1, 2):
        try:
            data = parse_json(llm.ask(rendered))
            if isinstance(data, dict):
                sections = {k: data.get(k) for k in SECTIONS}
                break
        except ValueError as exc:
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
