"""Find evidence, for one gap, started by a person:

  1. the query, from the gap: the technology, the fabric, and what the gap
     says is missing
  2. a web search (services/websearch), unless a link was given
  3. pages already collected are skipped
  4. the rest are read like any collected page — fetched, summarised, their
     findings checked — and saved under a small run of kind find_evidence,
     from the source "Web search" (each page still counts as its own site),
     marked as found by this job, and filed under the technology; a page a
     Can ignore rule sets aside is kept but not filed, like any other
  5. only the call behind the gap is run again, when a page was filed: the
     technology's Classify call, that one measure, or that fabric's use cases
  6. what came of it is recorded on the job, with the query used: each page
     filed, set aside (by which rule) or not read (why). Whenever the job is
     shown (`view`), each page's status is read again from its document.

Add evidence (kind `links`) takes several links and uploaded files a person
gives for one technology, reads them like the rest, and judges its evidence
again. With `through: "pov"` it carries on by itself: once its evidence is
judged enough (or the person chose to assess anyway) it's assessed, then its
Point of View is written. Each step that can't go on says why.

The daily budget of searches is checked when it starts (api/find_evidence)."""

import hashlib
import logging
import re
import time
import uuid
from collections import Counter
from datetime import date

from agent.scout.tools.crawl import fetch_page, why_failed
from agent.scout.tools.summarize import summarize_page
from app.services.db.mongo import get_collection
from app.services.llm.context import with_context
from app.services.llm.llm import LLM
from app.services.runs import store
from app.services.signals import snapshot
from app.services.timezone import now_utc
from app.services import websearch
from app.services.display import display_name
from app.services import jobs as background

log = logging.getLogger(__name__)
QUERY_CHARS = 120  # a search, not a sentence: cut at a word
FILLER = {"a", "an", "and", "or", "of", "for", "the", "to", "in", "on", "with", "by", "from", "as", "at", "such",
          "its", "their", "that", "which", "plus", "including"}


def query_for(gap: dict) -> str:
    """The technology, the fabric, and what the gap says is missing: an
    unscored measure's `missing`, or a fabric's `no_use_case.evidence_needed`,
    up to its first comma or full stop (the thing itself, not its
    qualifiers), cut at a word to about QUERY_CHARS characters. A thin
    verdict names nothing, so it asks for the kinds of signal that count."""
    tech = get_collection("technologies").find_one({"_id": gap["tech_id"]}, {"name": 1, "label": 1}) or {}
    parts = [display_name(tech, gap["tech_id"])]
    if gap.get("fabric_id"):
        f = get_collection("fabrics").find_one({"_id": gap["fabric_id"]}, {"name": 1}) or {}
        parts.append(f.get("name") or "")
    if gap.get("measure_id"):
        a = latest_assessment(gap["tech_id"], gap.get("fabric_id"))
        m = ((a or {}).get("measures") or {}).get(gap["measure_id"]) or {}
        measure = get_collection("measures").find_one({"_id": gap["measure_id"]}, {"name": 1}) or {}
        needed = m.get("missing") or measure.get("name") or ""
    elif gap.get("kind") == "use_case":
        a = latest_assessment(gap["tech_id"], gap.get("fabric_id"))
        needed = ((a or {}).get("no_use_case") or {}).get("evidence_needed") or "enterprise use case"
    else:
        needed = f"deployment trial funding standard {date.today().year}"
    clause = re.split(r"[,;:()]|\.(?:\s|$)", str(needed).strip(), maxsplit=1)[0]
    parts.append(re.sub(r"^(?:an?|the)\s+", "", clause.strip(), flags=re.I))
    return _cut(" ".join(parts), QUERY_CHARS)


def _cut(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a word, with no dangling "or",
    "for", "the"… at the end."""
    out: list[str] = []
    for w in re.sub(r"[^\w\s\-./]", " ", text).split():
        if out and len(" ".join([*out, w])) > limit:
            break
        out.append(w)
    while len(out) > 1 and out[-1].lower() in FILLER:
        out.pop()
    return " ".join(out)


def latest_assessment(tech_id: str, fabric_id: str | None) -> dict | None:
    from app.services import evidence
    s = evidence.state(tech_id) or {}
    a = s.get("assessment")
    if not a:
        return None
    fab = next((f for f in a["fabrics"] if f["fabric_id"] == fabric_id), a["fabrics"][0] if a["fabrics"] else None)
    return get_collection("assessments").find_one({"_id": fab["assessment_id"]}) if fab else None


WAIT_S = 10  # how often an Add evidence job looks whether an assessment already going has finished
PASTED = ("link", "links")  # kinds a person gives the pages for: no search


def file_url(name: str, text: str) -> str:
    """An uploaded file's address: its name and what's in it, so the same file
    given twice is read once."""
    return f"upload:{hashlib.sha1(text.encode()).hexdigest()[:12]}/{name}"


def start(gap: dict, tz: str, files: list[dict] | None = None) -> str:
    """`files`: uploaded files already turned into text, [{name, text}]."""
    job_id = uuid.uuid4().hex[:12]
    get_collection("find_evidence_jobs").insert_one({
        "_id": job_id, "gap": gap, "status": "running", "at": now_utc(), "tz": tz, "results": [],
        "files": [{"name": f["name"], "url": file_url(f["name"], f["text"]), "text": f["text"]} for f in files or []],
        "query": None if gap.get("kind") in PASTED else query_for(gap), "searched": gap.get("kind") not in PASTED})
    background.start(run, job_id)
    return job_id


def reconcile_stale() -> None:
    """Start-up: a job still 'running' at boot died with the last process.
    Say so on it; pages it already read and filed are kept."""
    done = get_collection("find_evidence_jobs").update_many(
        {"status": "running"},
        {"$set": {"status": "failed", "finished_at": now_utc(),
                  "error": "the service restarted while it ran; pages already read are kept"}})
    if done.modified_count:
        log.warning("find evidence: %d interrupted job(s) marked failed", done.modified_count)


def run(job_id: str, fetch=fetch_page, search=websearch.search) -> None:
    jobs = get_collection("find_evidence_jobs")
    job = jobs.find_one({"_id": job_id})
    gap = job["gap"]
    try:
        with with_context(run_kind="find_evidence", run_id=job_id, tech_id=gap["tech_id"]):
            _run(job, fetch, search)
    except Exception as exc:
        log.exception("find evidence %s failed", job_id)
        jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "error": str(exc)[:300], "finished_at": now_utc()}})


def _run(job: dict, fetch, search) -> None:
    jobs = get_collection("find_evidence_jobs")
    documents = get_collection("documents")
    gap = job["gap"]
    tech = get_collection("technologies").find_one({"_id": gap["tech_id"]})
    from app.services.settings_store import radar_settings
    n = int(radar_settings()["find_evidence_results"])
    if gap.get("kind") == "link":
        found = [{"url": gap["url"], "title": None}]
    elif gap.get("kind") == "links":
        found = [{"url": u, "title": None} for u in gap.get("urls") or []] + \
                [{"url": f["url"], "title": f["name"]} for f in job.get("files") or []]
    else:
        with with_context(skills=["web_search"]):
            found = list({r["url"]: r for r in search(job["query"], n)}.values())  # each address once
    known = set(documents.distinct("end_url", {"end_url": {"$in": [r["url"] for r in found]}}))
    results = [{"url": r["url"], "title": r.get("title"), "status": "already" if r["url"] in known else "new"} for r in found]
    jobs.update_one({"_id": job["_id"]}, {"$set": {"results": results, "stage": "reading"}})

    fresh = [r for r in results if r["status"] == "new"]
    if fresh:
        run_id = store.create_run({"kind": "find_evidence", "job_id": job["_id"]}, snapshot.build())
        jobs.update_one({"_id": job["_id"]}, {"$set": {"run_id": run_id}})
        snap = get_collection("runs").find_one({"_id": run_id}, {"signal_list": 1, "signals_hash": 1, "crawl_settings": 1})
        llm = LLM.initialize()
        uploaded = {f["url"]: f for f in job.get("files") or []}
        for r in fresh:
            try:
                if r["url"] in uploaded:
                    f = uploaded[r["url"]]
                    text, meta, why = f["text"], {"kind": "pdf" if f["name"].lower().endswith(".pdf") else "document",
                                                  "title": f["name"], "published_date": None}, None
                else:
                    text, meta, why = fetch(r["url"])
                if not text:
                    r.update(status="failed", reason=why or "no text came back")
                    continue
                given = "uploaded" if r["url"] in uploaded else "added by hand" if gap.get("kind") in PASTED else "web search"
                site = uploaded[r["url"]]["name"] if r["url"] in uploaded else websearch.site(r["url"])
                source = {**websearch.SOURCE, "url": r["url"], "name": f"{site} ({given})"}
                with with_context(run_kind="find_evidence", run_id=run_id):
                    store.save_document(run_id, source["horizon"], source, r["url"], text,
                                        lambda url, t: summarize_page(llm, url, t, snap), meta=meta)
            except Exception as exc:  # one bad page never stops the others
                log.warning("find evidence %s: %s couldn't be read: %s", job["_id"], r["url"], exc)
                r.update(status="failed", reason=why_failed(exc))
                continue
            doc = documents.find_one({"end_url": r["url"], "run_id": run_id})
            error = doc.get("analysis_error")
            if error and not doc.get("partial"):  # read, but the model couldn't summarise it: nothing to file
                r.update(status="failed", reason=f"the model couldn't summarise it: {error.get('reason')}")
                continue
            # found for this technology: filed under it, whatever names the page used
            documents.update_one({"_id": doc["_id"]}, {
                "$addToSet": {"technologies": tech["name"], "technologies_resolved": tech["name"]},
                "$set": {"source_name": source["name"], "title": doc.get("title") or r.get("title"),
                         "found_by": {"job_id": job["_id"], "at": job["at"], "tz": job.get("tz")}}})
            r.update(doc_id=doc["_id"])
        store.finish_run(run_id, "completed")
        if uploaded:  # read and saved: the copy isn't needed
            jobs.update_one({"_id": job["_id"]}, {"$unset": {"files.$[].text": ""}})
        if any(r.get("doc_id") for r in fresh):
            from agent.resolver import restamp
            restamp([tech["name"]])  # the pages filed under it (a set-aside one loses it here, as any set-aside page does)
    settle(results)
    jobs.update_one({"_id": job["_id"]}, {"$set": {"results": results, "stage": "re-running"}})
    if not any(r["status"] == "filed" for r in results):
        outcome = f"{'Nothing was filed under it' if fresh else 'Nothing new to read'}, so nothing was run again."
    else:
        try:
            outcome = rerun(gap, tech, job["_id"])
        except Exception as exc:  # the pages stay filed; only the call failed
            log.exception("find evidence %s: the call behind the gap failed", job["_id"])
            outcome = f"Its call couldn't be run again: {str(exc)[:200]}."
    if gap.get("through") == "pov" and any(r["status"] == "filed" for r in results):
        outcome += " " + follow(job, tech)
    done = {**job, "results": results, "rerun": {"kind": gap["kind"], "outcome": outcome}}
    jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "completed", "stage": "done", "finished_at": now_utc(),
                                                   "summary": describe(done, display_name(tech)),
                                                   "rerun": done["rerun"]}})


# ── Add evidence, on to the Point of View ────────────────────────────

def follow(job: dict, tech: dict) -> str:
    """After its evidence is judged again: assess the technology (waiting for an
    assessment already going), then write its Point of View. Returns what came
    of it, in words; each step that can't go on says why."""
    from agent.analyzer import pov
    from agent.analyzer.agent import start_scoring_run
    from agent.analyzer.engine import RUNNING_STATES
    from app.services import busy, radar_status
    jobs, runs = get_collection("find_evidence_jobs"), get_collection("scoring_runs")
    tech_id = tech["_id"]
    verdict = (((get_collection("technologies").find_one({"_id": tech_id}, {"classification": 1}) or {})
                .get("classification") or {}).get("evidence") or {}).get("verdict")
    if verdict not in ("strong", "enough") and not job["gap"].get("assess_anyway"):
        return (f"Its evidence is still judged {verdict or 'not yet'}, so it wasn't assessed. Add more, or choose "
                "Assess anyway.")
    jobs.update_one({"_id": job["_id"]}, {"$set": {"stage": "assessing"}})
    run_id = None
    while run_id is None:  # one assessment at a time: wait for one already going
        try:
            run_id = start_scoring_run({"technologies": [tech_id]})
        except busy.Busy:
            pass
        if run_id is None:
            time.sleep(WAIT_S)
    jobs.update_one({"_id": job["_id"]}, {"$set": {"scoring_run_id": run_id}})
    while (run := runs.find_one({"_id": run_id}, {"status": 1, "error": 1}))["status"] in RUNNING_STATES:
        time.sleep(WAIT_S)
    if run["status"] != "completed":
        return f"Its assessment didn't finish: {run.get('error') or run['status']}."
    status = radar_status.statuses([tech_id])[tech_id]
    assessed = f"Assessed: {status['reason']}."
    jobs.update_one({"_id": job["_id"]}, {"$set": {"stage": "writing"}})
    try:
        pov.compose_pov(run_id, tech_id, job.get("tz"))
    except Exception as exc:  # the assessment stands; only the writing failed
        log.exception("add evidence %s: the Point of View couldn't be written", job["_id"])
        return f"{assessed} Its Point of View couldn't be written: {str(exc)[:200]}."
    return f"{assessed} Its Point of View is written; leaders see it once you publish."


# ── the one call behind the gap, run again ───────────────────────────

def rerun(gap: dict, tech: dict, job_id: str) -> str:
    target = gap.get("measure_id") and "measure" or (
        "use_case" if gap.get("kind") == "use_case" or gap.get("target") == "use_case" else "technology")
    if target == "technology":
        from agent.classifier import classify
        from app.services.settings_store import radar_settings
        tech = get_collection("technologies").find_one({"_id": tech["_id"]})
        r = classify.classify_one(LLM.initialize(), tech, job_id, classify.lists(), int(radar_settings()["classify_pages_cap"]))
        c = (get_collection("technologies").find_one({"_id": tech["_id"]}) or {}).get("classification") or {}
        verdict = (c.get("evidence") or {}).get("verdict")
        return f"Classified again: its evidence is now judged {verdict}." if verdict else f"Classified again ({r['status']})."
    if target == "measure":
        return rerun_measure(gap, tech, job_id)
    return rerun_use_cases(gap, tech, job_id)


def rerun_measure(gap: dict, tech: dict, job_id: str) -> str:
    """That one measure, in its single call, on the technology's evidence now;
    the latest assessment takes the new answer, and its scores are worked
    out again (no other call)."""
    from agent.analyzer import engine
    from agent.analyzer.stacked import WHOLE, scope
    a = latest_assessment(gap["tech_id"], gap.get("fabric_id"))
    if a is None:
        return "It hasn't been assessed, so there's no measure to score again."
    m = get_collection("measures").find_one({"_id": gap["measure_id"]})
    fabric = WHOLE if scope(m) == "technology" else (get_collection("fabrics").find_one({"_id": a["fabric_id"]}) or WHOLE)
    config = list(get_collection("scoring_config").find())
    dossier = engine.build_dossier(tech["name"], engine.dossier_limit(config), signals_first=True)["text"]
    # no scoring run: nothing to count, and a call that errors isn't waited on
    result = {**engine._score_measure(LLM.initialize(), None, m, tech["name"], fabric, dossier), "code": m.get("code"),
              "scope": scope(m), "found_by_job": job_id}
    targets = [x["_id"] for x in get_collection("assessments").find(
        {"scoring_run_id": a["scoring_run_id"], "tech_id": a["tech_id"],
         **({} if scope(m) == "technology" else {"fabric_id": a["fabric_id"]})}, {"_id": 1})]
    measures = list(get_collection("measures").find())
    for aid in targets:
        row = get_collection("assessments").find_one({"_id": aid})
        row["measures"][gap["measure_id"]] = result
        get_collection("assessments").update_one({"_id": aid}, {"$set": {
            f"measures.{gap['measure_id']}": result,
            **engine.rollup(row["measures"], measures, config, f"rescored {now_utc()}")}})
    name = m.get("name")
    if result["score"] is None:
        return f"{name} is still not scored: {result.get('missing') or 'the pages still do not show it'}."
    return f"{name} is now scored {result['score']}: {result.get('justification') or ''}".strip()


def rerun_use_cases(gap: dict, tech: dict, job_id: str) -> str:
    """Find use cases: that fabric's value levers again, alone, on the evidence now."""
    from agent.analyzer import engine, value
    from app.services.prompts import recipe as recipes
    a = latest_assessment(gap["tech_id"], gap.get("fabric_id"))
    if a is None:
        return "It hasn't been assessed in this fabric, so there are no use cases to look again for."
    fabric = get_collection("fabrics").find_one({"_id": a["fabric_id"]}) or {"_id": a["fabric_id"], "name": a.get("fabric")}
    config = list(get_collection("scoring_config").find())
    built = engine.build_dossier(tech["name"], engine.dossier_limit(config), signals_first=True)
    mechs = value.mechanisms()
    with with_context(fabric_id=fabric["_id"]):
        result = recipes.alone(LLM.initialize(), value.task(fabric, mechs),
                               {"technology": tech["name"], "evidence": built["text"], **engine.fabric_values(fabric)},
                               value.check(fabric, mechs, built["pages"]))
    if isinstance(result, recipes.Failure):
        return f"Use cases weren't updated: {result.reason}."
    get_collection("assessments").update_one({"_id": a["_id"]}, {"$set": {**value.fields(result), "use_cases_found_by_job": job_id}})
    n = len(result["use_cases"])
    return (f"{n} use case{'s' if n != 1 else ''} from the pages in {fabric.get('name')}."
            if n else f"Still no use case from the pages in {fabric.get('name')}.")


# ── what came of it, as it reads now ─────────────────────────────────

def settle(results: list[dict]) -> list[dict]:
    """Each page read is filed under the technology, or set aside by a Can
    ignore rule (its name, and what it sets aside), as its document says now."""
    docs = {d["_id"]: d for d in get_collection("documents").find(
        {"_id": {"$in": [r["doc_id"] for r in results if r.get("doc_id")]}}, {"ignored_by": 1})}
    rules = {s["_id"]: s for s in get_collection("signals").find(
        {"_id": {"$in": [d["ignored_by"] for d in docs.values() if d.get("ignored_by")]}}, {"name": 1, "look_for": 1})}
    for r in results:
        d = docs.get(r.get("doc_id"))
        if d is None:
            continue
        r.pop("rule", None)
        r.pop("reason", None)
        if d.get("ignored_by"):
            rule = rules.get(d["ignored_by"]) or {}
            r.update(status="set_aside", rule=rule.get("name") or d["ignored_by"], reason=rule.get("look_for"))
        else:
            r.update(status="filed")
    return results


def describe(job: dict, name: str) -> str:
    """What came of a job, in one line: the pages filed under the technology,
    set aside (by which rule) and not read (why), then the call run again."""
    results = job.get("results") or []
    outcome = (job.get("rerun") or {}).get("outcome")
    then = f" {outcome}" if outcome else ""
    if not results:
        return "Nothing found." + (f' The search was: "{job["query"]}".' if job.get("query") else "")
    if job["gap"].get("kind") == "link":  # a pasted link: one page
        r = results[0]
        return {"filed": f"The page was read and filed under {name}.",
                "already": "That page is already collected, so it wasn't read again.",
                "set_aside": f'The page was read but set aside by the Can ignore rule "{r.get("rule")}", '
                             f"so it isn't filed under {name}.",
                "failed": f"The page couldn't be read: {r.get('reason')}."}.get(r["status"], "") + then
    count = Counter(r["status"] for r in results)
    given = "result" if job.get("searched") else "link or file" if len(results) == 1 else "links and files"
    parts = [f"{_n(count['filed'], 'new page')} filed under {name} from "
             + (_n(len(results), given) if job.get("searched") or len(results) == 1 else f"{len(results)} {given}")
             + (f" ({count['already']} already collected)" if count["already"] else "")]
    parts += [f'{n} set aside by the Can ignore rule "{rule}"'
              for rule, n in Counter(r.get("rule") for r in results if r["status"] == "set_aside").items()]
    parts += [f"{n} couldn't be read ({why})"
              for why, n in Counter(r.get("reason") for r in results if r["status"] == "failed").items()]
    return "; ".join(parts) + "." + then


def _n(n: int, one: str) -> str:
    return f"{n} {one}{'' if n == 1 else 's'}"


def name_of(tech_id: str) -> str:
    t = get_collection("technologies").find_one({"_id": tech_id}, {"name": 1, "label": 1}) or {}
    return display_name(t, tech_id)


def view(job: dict, name: str | None = None) -> dict:
    """A job as it reads now: each page's status from its document, and, once
    it's done, the summary written from them, so a job from before set-aside
    pages were told apart, or a page set aside since, reads true."""
    settle(job.get("results") or [])
    for f in job.get("files") or []:
        f.pop("text", None)  # an uploaded file's text stays on the server
    if job.get("status") == "completed":
        job["summary"] = describe(job, name or name_of(job["gap"]["tech_id"]))
    return job
