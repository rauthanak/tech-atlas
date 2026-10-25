"""Classify: one stacked call per technology (recipe `classify`) — how solid
its evidence is, its domain and sub-domain, commercial availability,
readiness (TRL), and whether it may be nascent — each answer with a reason
and the numbered pages it rests on.

Runs after organizing, at the end of every collection, for technologies that
are switched on and are new, have pages their last classification didn't
read, or were marked for review when a list definition changed; or on
demand. A technology classified before gets its current answers and only
its new pages. The tasks and lists are the same for every technology, so
they lead the call and are reused. A run judges every technology it was
given: catalog technologies first, then those with the most pages."""

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from agent.classifier.evidence import pack
from app.services import decisions, tech_status
from app.services.db.mongo import get_collection
from app.services.llm.context import carry, with_context
from app.services.llm.llm import LLM
from app.services.prompts import recipe as recipes
from app.services.prompts.recipe import Failure, Task
from app.services.settings_store import radar_settings
from app.services.timezone import now_utc
from app.settings import get_settings
from app.services import jobs

log = logging.getLogger(__name__)
VERDICTS = ("strong", "enough", "thin", "not_credible")
# each task's reply key, and the field of a classification its answer fills
FIELD_OF = {"evidence_strength": "evidence", "domain_subdomain": "domain", "commercial_availability": "availability",
            "trl_level": "trl", "possible_nascent": "nascent"}
_lock = threading.Lock()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def subdomain_id(domain_id: str, name: str) -> str:
    return f"{domain_id}--{slug(name)}"


# ── the lists, as the skills read them ───────────────────────────────

def lists() -> dict:
    by_order = lambda x: (x.get("order", 50), x.get("name", ""))
    return {"availability": sorted(get_collection("availability").find(), key=by_order),
            "domains": sorted(get_collection("domains").find(), key=by_order),
            "subdomains": sorted(get_collection("subdomains").find(), key=lambda s: (s["domain_id"], s["name"].lower())),
            "trl_levels": sorted(get_collection("trl_levels").find(), key=lambda t: t["level"])}


def list_values(ls: dict) -> dict:
    names = {d["_id"]: d["name"] for d in ls["domains"]}
    grouped: dict[str, list[str]] = {}
    for s in ls["subdomains"]:
        grouped.setdefault(s["domain_id"], []).append(s["name"])
    return {
        "availability_values": "\n".join(f"- {a['_id']}: {a['name']} — {a['definition']}" for a in ls["availability"]),
        "domains": "\n".join(f"- {d['_id']}: {d['name']} — {d['definition']}" for d in ls["domains"]),
        "subdomains": "\n".join(f"{names.get(d, d)} ({d}): {'; '.join(subs)}" for d, subs in grouped.items()),
        "trl_levels": "\n".join(f"{t['level']}: {t['name']} — {t['definition']}" for t in ls["trl_levels"]),
    }


def classification_tasks(values: dict, with_evidence_and_nascent: bool = True) -> list[Task]:
    tasks = [Task("domain_subdomain", "domain_subdomain", "File it under a domain",
                  {"domains": values["domains"], "subdomains": values["subdomains"]}),
             Task("commercial_availability", "commercial_availability", "Judge how available it is to buy",
                  {"availability_values": values["availability_values"]}),
             Task("trl_level", "trl_level", "Judge its readiness (TRL)", {"trl_levels": values["trl_levels"]})]
    if with_evidence_and_nascent:
        tasks = [Task("evidence_strength", "evidence_strength", "Judge how solid the evidence is"), *tasks,
                 Task("possible_nascent", "possible_nascent", "Spot a possibly nascent technology")]
    return tasks


# ── each answer, checked ─────────────────────────────────────────────

def validators(ls: dict, pages: list[str]) -> dict:
    """Each skill's rules for its answer; page numbers become page ids."""
    def cite(value) -> list[str]:
        nums = value.get("pages") if isinstance(value, dict) else None
        return [pages[n - 1] for n in nums or [] if isinstance(n, int) and 1 <= n <= len(pages)]

    def reason(value) -> str:
        r = str(value.get("reason") or "").strip()
        if not r:
            raise ValueError("the answer gave no reason")
        return r

    def evidence(v, task):
        if not isinstance(v, dict) or v.get("verdict") not in VERDICTS:
            raise ValueError(f"the verdict must be one of {', '.join(VERDICTS)}")
        return {"verdict": v["verdict"], "reason": reason(v), "pages": cite(v)}

    domains = {d["_id"] for d in ls["domains"]}
    subs = {(s["domain_id"], s["name"].lower()): s["_id"] for s in ls["subdomains"]}

    def domain(v, task):
        if not isinstance(v, dict) or v.get("domain_id") not in domains:
            raise ValueError("the domain must be one of the listed ids")
        name = str(v.get("subdomain") or "").strip()
        sub_id = subs.get((v["domain_id"], name.lower())) if name else None
        new = str(v.get("subdomain_new") or "").strip() or (name if name and not sub_id else None)
        return {"domain_id": v["domain_id"], "subdomain_id": sub_id, "subdomain_new": new, "reason": reason(v),
                "pages": cite(v)}

    values = {a["_id"] for a in ls["availability"]}

    def availability(v, task):
        if not isinstance(v, dict) or v.get("value_id") not in values:
            raise ValueError("the value must be one of the listed ids")
        return {"value_id": v["value_id"], "reason": reason(v), "pages": cite(v)}

    def trl(v, task):
        if not isinstance(v, dict) or "level" not in v:
            raise ValueError("the answer gave no level")
        level = v["level"]
        if level is not None and (isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 9):
            raise ValueError("TRL is a whole number from 1 to 9, or null")
        return {"level": level, "reason": str(v.get("reason") or "").strip(), "missing": v.get("missing") if level is None else None,
                "pages": cite(v)}

    def nascent(v, task):
        if not isinstance(v, dict) or not isinstance(v.get("flag"), bool):
            raise ValueError("the answer must say flag true or false")
        if not v["flag"]:
            return None
        n = v.get("page")
        page = pages[n - 1] if isinstance(n, int) and 1 <= n <= len(pages) else None
        if not page or not str(v.get("quote") or "").strip():
            raise ValueError("a flag needs a quote and its page")
        return {"reason": reason(v), "quote": str(v["quote"]).strip(), "page": page}

    return {"evidence_strength": evidence, "domain_subdomain": domain, "commercial_availability": availability,
            "trl_level": trl, "possible_nascent": nascent}


# ── one technology ───────────────────────────────────────────────────

def _current(c: dict, ls: dict) -> str:
    """Its current answers, for an incremental call."""
    names = {**{a["_id"]: a["name"] for a in ls["availability"]}, **{d["_id"]: d["name"] for d in ls["domains"]}}
    sub = {s["_id"]: s["name"] for s in ls["subdomains"]}
    lines = []
    if c.get("evidence"):
        lines.append(f"- evidence: {c['evidence']['verdict']} ({c['evidence'].get('reason')})")
    if c.get("domain"):
        d = c["domain"]
        lines.append(f"- domain: {names.get(d['domain_id'], d['domain_id'])}"
                     f"{' › ' + (sub.get(d.get('subdomain_id')) or d.get('subdomain_new') or '') if d.get('subdomain_id') or d.get('subdomain_new') else ''}"
                     f" ({d.get('reason')})")
    if c.get("availability"):
        lines.append(f"- commercial availability: {names.get(c['availability']['value_id'])} ({c['availability'].get('reason')})")
    if c.get("trl"):
        lines.append(f"- TRL: {c['trl'].get('level')} ({c['trl'].get('reason')})")
    return ("CURRENT ANSWERS, from the pages read before (not listed again below). Keep each unless the new pages "
            "below change it; a verdict on the evidence weighs every page, old and new, as FACTS describe them:\n"
            + "\n".join(lines) + "\n\n") if lines else ""


def classify_one(llm: LLM, tech: dict, run_id: str, ls: dict, cap: int) -> dict:
    """Classify one technology; returns {status, calls, reason?}."""
    name = tech["name"]
    label = tech.get("label") or name
    prior = tech.get("classification") or {}
    incremental = bool(prior) and not tech.get("classification_stale")
    seen = set(tech.get("pages_seen") or []) if incremental else None
    ev = pack(name, cap, seen)
    if not ev["pages"]:
        if incremental:  # nothing new to read; an older visit of a page read before is known now too
            get_collection("technologies").update_one({"_id": tech["_id"]},
                                                      {"$addToSet": {"pages_seen": {"$each": ev["known"]}}})
            tech_status.touch([tech["_id"]])  # it no longer waits for Classify
            return {"status": "unchanged"}
        return {"status": "skipped", "reason": "no pages"}
    values = list_values(ls)
    recipe = get_collection("recipes").find_one({"_id": "classify"}) or {"_id": "classify", "cache": "instructions"}
    built = recipes.build(recipe, classification_tasks(values), {"technology": label, "evidence": ev["text"], "facts": ev["facts"]})
    with with_context(run_kind="classify", run_id=run_id, tech_id=tech["_id"]):
        out, retries = recipes.ask(llm, built, validators(ls, ev["pages"]), prefix=_current(prior, ls) if incremental else "")
    now = now_utc()
    cls = dict(prior)
    for key, field in FIELD_OF.items():
        value = out[key]
        if isinstance(value, Failure):
            continue  # keep the earlier answer, if any
        if field == "nascent" and value is None and incremental and prior.get("nascent") \
                and not decisions.active([tech["_id"]], ["nascent"]):
            continue  # only new pages were read: no new early sign leaves an unanswered flag standing
        if field == "evidence":
            value = {**value, "read": ev["read"] + (prior.get("evidence") or {}).get("read", 0) if incremental else ev["read"],
                     "of": ev["of"], "sources": ev["sources"]}
        if field == "domain" and value.get("subdomain_new"):
            value["subdomain_id"] = _propose_subdomain(value["domain_id"], value["subdomain_new"], tech["_id"])
        cls[field] = None if value is None else {**value, "source": "pages", "at": now}
    cls.update(at=now, run_id=run_id)
    get_collection("technologies").update_one(
        {"_id": tech["_id"]},
        {"$set": {"classification": cls}, "$addToSet": {"pages_seen": {"$each": ev["known"]}},
         "$unset": {"classification_stale": ""}})
    tech_status.touch([tech["_id"]])  # its verdict, domain and availability: the lists show them next pass
    failed = [k for k, v in out.items() if isinstance(v, Failure)]
    return {"status": "classified" if not failed else "partly", "retries": retries,
            **({"reason": "; ".join(f"{k}: {out[k].reason}" for k in failed)} if failed else {})}


def _propose_subdomain(domain_id: str, name: str, tech_id: str) -> str:
    """A sub-domain the model proposed: kept as "new", for an admin to accept,
    merge or rename (it shows on Changes until it's in the seeding data)."""
    sid = subdomain_id(domain_id, name)
    get_collection("subdomains").update_one(
        {"_id": sid},
        {"$setOnInsert": {"subdomain_id": sid, "name": name, "domain_id": domain_id, "status": "new",
                          "proposed_by": tech_id, "updated_at": now_utc()}}, upsert=True)
    return sid


# ── which technologies, and the run ──────────────────────────────────

def pending() -> list[str]:
    """Switched on, with pages, and new, with a page version its last
    classification didn't know (a changed page is a new version), or marked
    for review. Catalog technologies first, then the most pages first, so
    what matters most is judged first. Read from the answers kept ready
    (services/tech_status); a technology whose answers wait to be worked out
    again (its pages just changed) is checked against its pages here, in the
    database, so memory stays flat however many pages there are."""
    from app.services import tech_status
    tech_status.fresh()  # the few waiting are worked out first, as a screen does
    marked = get_collection("technologies").distinct("name", {tech_status.DIRTY: {"$exists": True}})
    kept = [(*r["f"]["classify_order"], r["_id"]) for r in get_collection("tech_status").find(
        {"f.classify_waiting": True, "name": {"$nin": marked}}, {"f.classify_order": 1})]
    return [tech_id for *_, tech_id in sorted(kept + _pending_from_pages(marked))]


def _pending_from_pages(names: list[str]) -> list[tuple]:
    """pending(), worked out from these technologies' pages: (not in the catalog, -pages, id) each, a few
    thousand names at a time (a query naming them all can outgrow MongoDB's 16 MB)."""
    return [r for i in range(0, len(names), 5000) for r in _pending_of(names[i:i + 5000])]


def _pending_of(names: list[str]) -> list[tuple]:
    if not names:
        return []
    rows = get_collection("documents").aggregate([
        {"$match": {"is_stub": {"$ne": True}, "ignored_by": None, "technologies_resolved": {"$in": names}}},
        {"$unwind": "$technologies_resolved"},
        {"$match": {"technologies_resolved": {"$in": names}}},
        {"$group": {"_id": "$technologies_resolved", "v": {"$addToSet": "$_id"}}},
        {"$lookup": {"from": "technologies", "localField": "_id", "foreignField": "name", "as": "t",
                     "pipeline": [{"$match": {"enabled": {"$ne": False}}},
                                  {"$project": {"pages_seen": 1, "classification_stale": 1, "imported": 1, "origin": 1,
                                                "classified": {"$gt": [{"$size": {"$objectToArray": {
                                                    "$ifNull": ["$classification", {}]}}}, 0]}}}]}},
        {"$unwind": "$t"},
        {"$project": {"_id": 0, "tech_id": "$t._id", "imported": "$t.imported", "origin": "$t.origin",
                      "pages": {"$size": "$v"},
                      "due": {"$or": [{"$not": ["$t.classified"]}, {"$eq": ["$t.classification_stale", True]},
                                      {"$gt": [{"$size": {"$setDifference": ["$v", {"$ifNull": ["$t.pages_seen", []]}]}}, 0]}]}}},
        {"$match": {"due": True}}], allowDiskUse=True)
    catalog = {d["tech_id"]: d for d in decisions.active(kinds=["catalog"])}
    return [(int(not decisions.in_catalog(r, catalog.get(r["tech_id"]))["in"]), -r["pages"], r["tech_id"]) for r in rows]


def spent(run_id: str) -> int:
    """Tokens a run has paid for, counting reused ones at a tenth (their price): recorded when it ends."""
    rows = list(get_collection("llm_calls").aggregate([
        {"$match": {"run_id": run_id}},
        {"$group": {"_id": None, "n": {"$sum": {"$add": ["$input_tokens", "$output_tokens", "$cache_write_tokens",
                                                        {"$multiply": ["$cache_read_tokens", 0.1]}]}}}}]))
    return int(rows[0]["n"]) if rows else 0


def active_run() -> dict | None:
    return get_collection("classify_runs").find_one({"status": "running"})


def reconcile_stale() -> None:
    """Start-up: only this process classifies, so a run still 'running' at
    boot died with the last process. Mark it, or it would block every later
    Classify; technologies it already judged keep their verdict."""
    done = get_collection("classify_runs").update_many(
        {"status": "running"},
        {"$set": {"status": "terminated", "finished_at": now_utc(),
                  "error": "the service restarted while it ran; technologies already judged keep their verdict"}})
    if done.modified_count:
        log.warning("classify: %d interrupted run(s) marked terminated", done.modified_count)


def start(tech_ids: list[str], trigger: str = "on demand", tz: str | None = None, wait: bool = False) -> str | None:
    """Start a classify run in the background (or inline with `wait`); None
    when one is already running."""
    with _lock:
        if active_run():
            return None
        settings = radar_settings()
        run_id = uuid.uuid4().hex[:12]
        get_collection("classify_runs").insert_one({
            "_id": run_id, "status": "running", "trigger": trigger, "started_at": now_utc(), "tz": tz,
            "tech_ids": tech_ids, "total": len(tech_ids), "done": 0, "unchanged": 0, "failed": [], "retries": 0,
            "cap": int(settings["classify_pages_cap"])})
    if wait:
        _execute(run_id)
    else:
        jobs.start(_execute, run_id)
    return run_id


def _execute(run_id: str) -> None:
    runs = get_collection("classify_runs")
    run = runs.find_one({"_id": run_id})
    try:
        llm = LLM.initialize()
        ls = lists()
        techs = {t["_id"]: t for t in get_collection("technologies").find({"_id": {"$in": run["tech_ids"]}})}

        def one(tech_id: str) -> None:
            if (runs.find_one({"_id": run_id}, {"status": 1}) or {}).get("status") != "running":
                return  # stopped by a person
            tech = techs.get(tech_id)
            if tech is None or tech.get("enabled") is False:
                runs.update_one({"_id": run_id}, {"$inc": {"done": 1, "unchanged": 1}})
                return
            try:
                r = classify_one(llm, tech, run_id, ls, run["cap"])
                update: dict = {"$inc": {"done": 1, "retries": r.get("retries", 0),
                                         "unchanged": int(r["status"] in ("unchanged", "skipped"))}}
                if r["status"] == "partly":
                    update["$push"] = {"failed": {"tech_id": tech_id, "reason": r["reason"]}}
            except Exception as exc:  # one technology must not sink the run; it says why
                log.exception("classify %s failed", tech_id)
                update = {"$inc": {"done": 1}, "$push": {"failed": {"tech_id": tech_id, "reason": str(exc)[:300]}}}
            update.setdefault("$set", {})["heartbeat_at"] = now_utc()
            runs.update_one({"_id": run_id}, update)

        with with_context(run_kind="classify", run_id=run_id), \
                ThreadPoolExecutor(max_workers=get_settings().scoring_concurrency, thread_name_prefix="classify") as pool:
            for future in [pool.submit(carry(one), t) for t in run["tech_ids"]]:  # each carries the run's context
                future.result()
        done = runs.find_one({"_id": run_id})
        status = "terminated" if done["status"] == "terminating" else "completed"
        runs.update_one({"_id": run_id}, {"$set": {"status": status, "finished_at": now_utc(), "tokens": spent(run_id)}})
    except Exception as exc:
        log.exception("classify run %s failed", run_id)
        runs.update_one({"_id": run_id}, {"$set": {"status": "failed", "error": str(exc)[:500], "finished_at": now_utc()}})
