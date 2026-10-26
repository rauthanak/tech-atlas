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
import math
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from agent.analyzer.placement import compute_placement
from app.services.llm.context import carry, with_context
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM, call_with_backoff, parse_json
from app.services.prompts.store import PromptStore
from app.services.timezone import now_utc
from app.services.evidence import page_key
from app.services.pages import NEWEST as pages_newest, link_key

log = logging.getLogger(__name__)

RUNNING_STATES = {"running", "terminating"}
TORA_AXES = ("market_potential", "strategic_fit", "adoption_readiness")


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
        "recipes": list(get_collection("recipes").find()),
    }
    techs = _select_technologies(params)
    get_collection("scoring_runs").insert_one({
        "_id": run_id,
        "status": "running",
        "stage": "preparing",
        "stage_history": [{"stage": "preparing", "at": now_utc()}],
        "params": params,
        "snapshot": snapshot,
        "technologies": [{"tech_id": t["_id"], "name": t["name"],
                          "doc_count": t.get("doc_count", 0)} for t in techs],
        "progress": {"techs_total": len(techs), "techs_done": 0, "llm_calls": 0},
        "started_at": now_utc(),
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
         "$push": {"stage_history": {"stage": stage, "at": now_utc()}}})


def finish(run_id: str, status: str, error: str | None = None) -> None:
    set_stage(run_id, "done")
    get_collection("scoring_runs").update_one({"_id": run_id}, {"$set": {
        "status": status, "error": error, "finished_at": now_utc()}})


def _bump(run_id: str, **inc) -> None:
    get_collection("scoring_runs").update_one(
        {"_id": run_id},
        {"$inc": {f"progress.{k}": v for k, v in inc.items()},
         "$set": {"heartbeat": now_utc()}})


def reconcile_stale_scoring_runs(keep=()) -> None:
    """A 'running' scoring run at boot died with the last process, unless it's
    still waiting in the queue (`keep`)."""
    result = get_collection("scoring_runs").update_many(
        {"status": {"$in": list(RUNNING_STATES)}, "_id": {"$nin": list(keep)}},
        {"$set": {"status": "terminated", "error": "interrupted — found running at start-up",
                  "finished_at": now_utc()}})
    if result.modified_count:
        log.warning("reconciled %d stale scoring run(s)", result.modified_count)


def shutdown(keep=()) -> None:
    result = get_collection("scoring_runs").update_many(
        {"status": {"$in": list(RUNNING_STATES)}, "_id": {"$nin": list(keep)}},
        {"$set": {"status": "terminated", "error": "interrupted — service shutdown",
                  "finished_at": now_utc()}})
    if result.modified_count:
        log.warning("shutdown: marked %d scoring run(s) terminated", result.modified_count)


# ── evidence dossier ─────────────────────────────────────────────────

def build_dossier(tech_name: str, max_tokens: int, signals_first: bool = False) -> dict:
    """Each linked page's summary, as its newest visit — full dossier, no doc
    cap — newest first. With `signals_first`, pages carrying a kept finding
    about this technology come first, then the rest, each group newest first.
    The token ceiling is a guard for pathological volume only: pages are read
    only until it's reached, so the last entries drop (the oldest, after the
    findings), and the dossier says how many. Returns the `text` with what it read: `pages`, the page versions (an
    unchanged revisit counts as the version it repeats); `runs`, the
    collection runs those visits came from; and `from`, the newest-visit time
    of the oldest page read, set only when the guard dropped pages."""
    docs = get_collection("documents")
    fields = {"end_url": 1, "page_key": 1, "title": 1, "kind": 1, "published_date": 1,
              "scraped_at": 1, "summary_text": 1, "scout_take": 1,
              "source_id": 1, "run_id": 1, "is_stub": 1, "ref_doc_id": 1}
    linked = {"technologies_resolved": tech_name, **pages_newest}
    groups = [{**linked, "ignored_by": None, "signals.technologies_resolved": tech_name}, linked] \
        if signals_first else [linked]

    def newest_first():  # each page once, as its newest visit
        seen: set[str] = set()
        for query in groups:
            for d in docs.find(query, fields).sort("scraped_at", -1):
                if page_key(d) not in seen:
                    seen.add(page_key(d))
                    yield d

    kept, pages, runs, cutoff, last_visit = [], [], set(), None, None
    total_chars, budget = 0, max_tokens * 4  # ~4 chars per token
    for d in newest_first():  # the oldest fall off if the guard trips
        mark = f"[{len(pages) + 1}]" if signals_first else "-"  # numbered: answers can cite pages by number
        lines = [f"{mark} [{d.get('kind') or 'article'}] {d.get('title') or d.get('end_url')}",
                 f"  url: {d.get('end_url')} · source: {d.get('source_id')}"
                 f" · published: {d.get('published_date') or 'n/a'}"
                 f" · extracted: {str(d.get('scraped_at'))[:10]}"]
        if d.get("summary_text"):
            lines.append(f"  summary: {d['summary_text']}")
        if d.get("scout_take"):
            lines.append(f"  scout take: {d['scout_take']}")
        text = "\n".join(lines)
        if total_chars + len(text) > budget:
            linked_pages = (get_collection("technologies").find_one({"name": tech_name}, {"page_count": 1}) or {})
            kept.append(f"[dossier truncated at ~{max_tokens} tokens — "
                        f"{max(0, (linked_pages.get('page_count') or 0) - len(pages))} oldest entries omitted]")
            cutoff = last_visit
            break
        kept.append(text)
        total_chars += len(text)
        pages.append(d["ref_doc_id"] if d.get("is_stub") and d.get("ref_doc_id") else d["_id"])
        last_visit = d.get("scraped_at")
        if d.get("run_id"):
            runs.add(d["run_id"])
    return {"text": "\n\n".join(kept), "pages": pages, "runs": sorted(runs), "from": cutoff}


# ── the skills' blanks ───────────────────────────────────────────────
# The Skills page's preview fills them with these same functions, so it
# shows exactly what a run sends.

def dossier_limit(scoring_config: list[dict]) -> int:
    """The evidence ceiling, in tokens."""
    evidence_cfg = next((c for c in scoring_config if c["_id"] == "evidence"), {})
    return int(evidence_cfg.get("max_dossier_tokens", 300000))


def fabric_list(fabrics: list[dict]) -> str:
    return "\n".join(f"- {f['_id']}: {f['name']} — {f['definition']}" for f in fabrics)


def fabric_values(fabric: dict) -> dict:
    """A fabric's blanks, wherever a skill is about one fabric."""
    return {"fabric_name": fabric.get("name", ""), "fabric_definition": fabric.get("definition", ""),
            "tcl_today": fabric.get("tcl_today") or "Not described."}  # TCL's side of the TCL-position measures


def fabric_relevance_values(technology: str, fabrics: list[dict], dossier: str) -> dict:
    return {"technology": technology, "fabrics": fabric_list(fabrics), "evidence": dossier}


def measure_scoring_values(measure: dict, technology: str, fabric: dict, dossier: str) -> dict:
    anchors = measure.get("anchors", {})
    return {
        "measure_name": f"{measure.get('code')} {measure.get('name')}",
        "definition": measure.get("definition", ""),
        "anchors": "\n".join(f"{k}: {v}" for k, v in anchors.items()),
        "required_evidence": measure.get("required_evidence", ""),
        "technology": technology,
        **fabric_values(fabric),
        "evidence": dossier,
    }


NO_PREVIOUS = "None: this is the technology's first assessment."


def previous_watch(tech_id: str, run_id: str) -> str:
    """The metrics the technology's latest earlier assessment set to watch,
    for this one to check against the evidence: said to have crossed or not."""
    a = get_collection("assessments").find_one(
        {"tech_id": tech_id, "scoring_run_id": {"$ne": run_id}, "watch_metrics.0": {"$exists": True}},
        {"watch_metrics": 1, "created_at": 1}, sort=[("created_at", -1)])
    if not a:
        return NO_PREVIOUS
    from app.services import decisions, watch
    fixed = watch.fixed_thresholds(decisions.active([tech_id], ["watch_threshold"]))
    return f"Set on {str(a.get('created_at'))[:10]}:\n" + "\n".join(
        f"- {m.get('metric')} | then: {m.get('current_value')} | threshold: "
        + (f"{fixed[k]} (set by a person: keep it exactly as written)" if (k := watch.sign_key(m.get("metric") or "")) in fixed
           else str(m.get("inflection_threshold")))
        + f" | direction: {m.get('direction')}" for m in a["watch_metrics"])


def watch_metrics_values(technology: str, dossier: str, previous: str = NO_PREVIOUS) -> dict:
    return {"technology": technology, "evidence": dossier, "previous": previous}


def page_urls(pages: list[str] | None) -> set[str]:
    """The addresses of the page versions an assessment read."""
    return {d.get("end_url") or d.get("source_url") for d in
            get_collection("documents").find({"_id": {"$in": list(pages or [])}}, {"end_url": 1, "source_url": 1})}


def watch_result(data, urls: set[str] | None = None) -> list:
    """The metrics to watch under their rules: each names what's measured, and
    a crossing counts only when its source is a page the assessment read."""
    out = []
    for m in data if isinstance(data, list) else []:
        if not isinstance(m, dict) or not m.get("metric"):
            continue
        if m.get("crossed") is True and urls is not None and m.get("source") not in urls:
            m = {**m, "crossed": None, "crossed_note": "said to have crossed, but on a page this assessment didn't read"}
        out.append(m)
    return out


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


def keep_worked_on(tech_id: str, chosen: list[str], fabrics: list[dict]) -> list[str]:
    """The fabrics to assess: the ones judged relevant, plus every fabric
    where people recorded something for this technology (Tata's plan, a
    priority, a hand score, an accepted gap), so a new run never drops what
    they worked on from its page, its Point of View or the leaders' view."""
    worked = set(get_collection("decisions").distinct(
        "fabric_id", {"tech_id": tech_id, "active": True, "fabric_id": {"$ne": None}}))
    return [f["_id"] for f in fabrics if f["_id"] in set(chosen) | worked]


def _relevant_fabrics(llm: LLM, run_id: str, tech_name: str,
                      fabrics: list[dict], dossier: str) -> list[dict]:
    """Which fabrics is this technology assessed in? One call, fail-open to
    all enabled fabrics — a gate failure must widen scoring, never narrow it."""
    try:
        prompt = PromptStore.get("fabric_relevance")
        with with_context(skills=["fabric_relevance"]):
            data = _ask_json(llm, prompt.render(
                **fabric_relevance_values(tech_name, fabrics, dossier)), run_id)
        ids = set(data.get("fabrics", [])) if isinstance(data, dict) else set()
        chosen = [f for f in fabrics if f["_id"] in ids]
        if chosen:
            return chosen
    except Exception:
        log.exception("fabric relevance gate failed for %s", tech_name)
    return fabrics


def _score_measure(llm: LLM, run_id: str, measure: dict, tech_name: str,
                   fabric: dict, dossier: str) -> dict:
    rendered = PromptStore.get("measure_scoring").render(
        **measure_scoring_values(measure, tech_name, fabric, dossier))
    with with_context(skills=["measure_scoring"], fabric_id=fabric.get("_id")):
        data = _ask_json(llm, rendered, run_id)
    if not isinstance(data, dict):
        return unscored("the reply wasn't a JSON object, twice")
    return measure_result(data, cited_keys(dossier, fabric))


def unscored(why: str) -> dict:
    """A measure whose call failed, saying why."""
    return {"score": None, "unscorable": True, "missing": f"scoring call failed ({why}) — re-score to retry",
            "justification": None, "evidence_urls": [], "counter_case": None}


def _figure(f, cited: list) -> dict | None:
    """A market figure a measure rests on, kept only when it is a number from
    a page the measure cites: the radar never shows a figure the model made up."""
    if not isinstance(f, dict) or f.get("url") not in cited:
        return None
    try:
        amount = float(f.get("amount_usd_bn"))
    except (TypeError, ValueError):
        return None
    return {"amount_usd_bn": amount, "year": f.get("year"), "scope": f.get("scope"), "url": f["url"]} if amount > 0 else None


ABSTAINED = "the answer said the pages don't support a score, so its number isn't used"
NOT_A_NUMBER = "the answer's score wasn't a number from 0 to 10"
NOT_GIVEN = "the answer cited only pages it wasn't given, so its score isn't used"


def cited_keys(dossier: str, fabric: dict | None = None) -> set[str]:
    """The links a measure's answer may cite, tidied: every page in the
    evidence it was shown (its `url:` lines), and the sources in the fabric's
    TCL TODAY text."""
    urls = re.findall(r"url: (\S+)", dossier or "")
    urls += [u.rstrip(".,;)") for u in re.findall(r"https?://\S+", (fabric or {}).get("tcl_today") or "")]
    return {link_key(u) for u in urls}


def measure_result(data: dict, cite: set[str] | None = None) -> dict:
    """A measure's answer under the scoring rules: the score a real number,
    clamped to 0–10; no score when the answer abstained; and a score counts
    only when it cites pages — with `cite`, pages from its evidence (cited_keys):
    links it wasn't given are dropped."""
    raw = data.get("score")
    ok = isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)
    score = max(0, min(10, round(float(raw), 1))) if ok else None
    urls = data.get("evidence_urls")
    urls = [urls] if isinstance(urls, str) else urls if isinstance(urls, list) else []
    given = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    kept = given if cite is None else [u for u in given if link_key(u) in cite]
    said = bool(data.get("unscorable"))
    missing = data.get("missing")
    if score is not None and said:
        score, missing = None, missing or ABSTAINED
    elif score is not None and not kept:
        # the prompt's own rule: a score without citations is invalid
        score, missing = None, "model scored without citing dossier URLs" if not given else NOT_GIVEN
    elif score is None and raw is not None and not missing:
        missing = NOT_A_NUMBER
    return {
        "score": score,
        "justification": data.get("justification"),
        "evidence_urls": kept,
        "counter_case": data.get("counter_case"),
        "unscorable": said or score is None,
        "missing": missing,
        "figure": _figure(data.get("figure"), kept),
    }


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


def rollup(measure_results: dict[str, dict], measures: list[dict], config: list[dict], basis: str) -> dict:
    """What an assessment stores from its measures' scores: the TORA roll-up,
    the placement, and how they were reached."""
    return {"tora": rollup_tora(measure_results, measures),
            "placement": compute_placement(measure_results, config), "tora_basis": basis}


def _load(run_id: str, tech_id: str, signals_first: bool = False) -> tuple[dict, dict, dict] | str:
    """(the run, the technology's entry in it, its evidence dossier), or what
    to say instead when there's nothing to assess (no evidence is recorded as
    a skip)."""
    runs = get_collection("scoring_runs")
    # the run's per-technology records (gates, tech_calls) grow with its size:
    # read only this technology's, not every technology's each time
    run = runs.find_one({"_id": run_id}, {"gates": 0, "tech_calls": 0})
    if run is None:
        return f"unknown scoring run {run_id}"
    own = runs.find_one({"_id": run_id}, {f"gates.{tech_id}": 1, f"tech_calls.{tech_id}": 1})
    # its technology call's answers: their own record; a run from before 24 Oct kept them on the run
    call = get_collection("scoring_tech_calls").find_one({"_id": f"{run_id}:{tech_id}"}, {"done": 1})
    run.update(gates=own.get("gates") or {}, tech_calls={tech_id: call["done"]} if call else own.get("tech_calls") or {})
    entry = next((t for t in run["technologies"] if t["tech_id"] == tech_id), None)
    if entry is None:
        return f"{tech_id} is not part of this scoring run"
    built = build_dossier(entry["name"], dossier_limit(run["snapshot"]["scoring_config"]), signals_first)
    if not built["text"]:
        _record_skip(run_id, entry, "no evidence — no documents stamped with this technology")
        return f"{entry['name']}: skipped, no evidence"
    return run, entry, built


def assessment_doc(run: dict, entry: dict, fabric: dict, built: dict, results: dict[str, dict], **extra) -> dict:
    """A technology's assessment in one fabric, as stored: each measure's
    result, rolled up and placed under the run's frozen method, with the
    evidence it read."""
    measures, config = run["snapshot"]["measures"], run["snapshot"]["scoring_config"]
    return {
        "_id": f"{run['_id']}:{entry['tech_id']}:{fabric['_id']}",
        "scoring_run_id": run["_id"],
        "tech_id": entry["tech_id"],
        "technology": entry["name"],
        "fabric_id": fabric["_id"],
        "fabric": fabric.get("name"),
        "doc_count": len(built["pages"]),  # pages actually read, after the size guard
        "evidence_runs": built["runs"],  # the collection runs whose pages the scorer read
        "dossier_pages": built["pages"],  # the page versions read: new evidence is any other
        **({"dossier_from": built["from"]} if built["from"] else {}),
        "measures": {mid: {**r, "code": next((m.get("code") for m in measures if m["_id"] == mid), mid)}
                     for mid, r in results.items()},
        # compact copy of the outside-TORA scores so list views can show
        # them without shipping the full measure payloads
        "extras": {m["code"]: results[m["_id"]]["score"]
                   for m in measures if str(m.get("code", "")).startswith("X") and m["_id"] in results},
        **extra,
        **rollup(results, measures, config, "scored"),
        "created_at": now_utc(),
    }


def assess_technology(run_id: str, tech_id: str, llm: LLM,
                      executor: ThreadPoolExecutor) -> str:
    """Score one technology across its relevant fabrics — the unit of work the
    analyzer agent (and the deterministic sweep) invokes."""
    with with_context(run_kind="scoring", run_id=run_id, tech_id=tech_id):
        if engine_mode(run_id) == "stacked":
            from agent.analyzer import stacked
            return stacked.assess(run_id, tech_id, llm, executor)
        return _assess_per_measure(run_id, tech_id, llm, executor)


def engine_mode(run_id: str) -> str:
    """How a run assesses: `stacked` (a technology call, then one call per
    fabric) or `per_measure` (one call per measure per fabric). A run's
    params.engine wins; else the setting frozen with the run's method."""
    run = get_collection("scoring_runs").find_one({"_id": run_id}, {"params.engine": 1, "snapshot.scoring_config": 1}) or {}
    if (run.get("params") or {}).get("engine") in ("stacked", "per_measure"):
        return run["params"]["engine"]
    cfg = next((c for c in (run.get("snapshot") or {}).get("scoring_config") or [] if c["_id"] == "engine"), {})
    return cfg.get("mode") or "per_measure"


def _assess_per_measure(run_id: str, tech_id: str, llm: LLM, executor: ThreadPoolExecutor) -> str:
    loaded = _load(run_id, tech_id)
    if isinstance(loaded, str):
        return loaded
    run, entry, built = loaded
    measures, fabrics, dossier = run["snapshot"]["measures"], run["snapshot"]["fabrics"], built["text"]

    # the gate's verdict is stored on the run, so a resume knows exactly which
    # fabrics are owed without re-gating (and without missing one)
    gated_ids = run.get("gates", {}).get(tech_id)
    if gated_ids is None:
        gated = _relevant_fabrics(llm, run_id, entry["name"], fabrics, dossier)
        gated_ids = keep_worked_on(tech_id, [f["_id"] for f in gated], fabrics)
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
        from agent.analyzer import stacked
        # Tata's own measures are never asked: they wait for Tata's figure, as in the stacked engine
        waiting = {mid: {**r, "scope": "tata"} for mid, r in stacked.tata_results(measures).items()}
        futures = {m["_id"]: executor.submit(
            carry(_score_measure), llm, run_id, m, entry["name"], fabric, dossier)
            for m in measures if m["_id"] not in waiting}
        results = {m["_id"]: waiting.get(m["_id"]) or futures[m["_id"]].result() for m in measures}
        get_collection("assessments").insert_one(assessment_doc(run, entry, fabric, built, results))
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
        metrics = watch_metrics_call(llm, run_id, entry["name"], dossier, previous_watch(tech_id, run_id),
                                     page_urls(built["pages"]))
        get_collection("assessments").update_many(
            {"scoring_run_id": run_id, "tech_id": tech_id},
            {"$set": {"watch_metrics": metrics}})

    mark_progress(run_id)
    return f"{entry['name']}: assessed in {', '.join(assessed) or 'no new fabrics'}"


def watch_metrics_call(llm: LLM, run_id: str, tech_name: str, dossier: str, previous: str = NO_PREVIOUS,
                       urls: set[str] | None = None) -> list:
    """The metrics to watch, in one call of their own, the previous ones
    checked; none when it fails."""
    try:
        with with_context(skills=["watch_metrics"]):
            data = _ask_json(llm, PromptStore.get("watch_metrics").render(
                **watch_metrics_values(tech_name, dossier, previous)), run_id)
        if isinstance(data, list):
            return watch_result(data, urls)
    except Exception:
        log.exception("watch metrics failed for %s", tech_name)
    return []


def mark_progress(run_id: str) -> None:
    done = len(get_collection("assessments").distinct("tech_id", {"scoring_run_id": run_id}))
    done += len(get_collection("scoring_runs").find_one(
        {"_id": run_id}, {"skipped": 1}).get("skipped", []))
    get_collection("scoring_runs").update_one(
        {"_id": run_id},
        {"$set": {"progress.techs_done": done, "heartbeat": now_utc()}})


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
            {"_id": a["_id"]}, {"$set": rollup(a["measures"], measures, config, f"recomputed {now_utc()}")})
        count += 1
    return count
