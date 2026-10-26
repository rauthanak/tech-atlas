"""Link known names (Organize's second part): pages that name a technology the
radar tracks are found by name and filed under it, when the page is about it.

  1. the known technologies: Tata's catalog (chosen 22 Oct: the technologies
     Tata asked about; broad assessed ones already have plenty of pages)
  2. names to look for, once per technology (skill `technology_names`, in
     batches): its usual name, other spellings and short forms; a person can
     edit them on the technology's page. The same call says when a catalog
     entry reads as a use case or a category rather than one technology.
  3. a name match over the stored pages, at no model cost: words in order,
     ignoring case and punctuation; a one-word name only as it's written
     (eBPF, FlexE, DID), so "did" or "matter" in a sentence isn't a match
  4. a check of what matched (skill `name_check`, a few passages a call, per
     technology): the page is about it, names it in passing, or uses the
     word for something else
  5. a page about it is filed under it, like a page Organize linked; a page
     naming it in passing is counted apart (`mentions`) and never counts as
     evidence. Each page and technology is checked once (`name_checks`).

It runs at every collection, after names are merged, over that collection's
pages; and on demand over every stored page (the catch-up). Its record is a
`tag_runs` document; each step that fails says why."""

import json
import logging
import re
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from pymongo import UpdateOne

from app.services import auth, decisions, page_texts
from app.services.db.mongo import get_collection
from app.services.llm.context import carry, with_context
from app.services.llm.llm import LLM, parse_json
from app.services.prompts.store import PromptStore
from app.services.timezone import now_utc
from app.settings import get_settings
from app.services.display import display_name
from app.services import jobs

log = logging.getLogger(__name__)

NAMES_BATCH = 40    # technologies per technology_names call
CHECK_BATCH = 10    # passages per name_check call
MAX_WORDS = 8       # the longest name looked for, in words
MIN_CHARS = 3       # shorter names ("AI") match too much to be worth looking for
SNIPPET = 300       # characters either side of a match, for the check
TEXT_BATCH = 500    # pages whose texts are read together
VERDICTS = ("about", "mention", "other")
STALE_AFTER = timedelta(minutes=10)  # a running run with no sign of life for this long was cut off
_lock = threading.Lock()
WORD = re.compile(r"[A-Za-z0-9]+")


# ── which technologies, and the names they go by ─────────────────────

def known() -> list[dict]:
    """The technologies the radar looks for by name: the catalog's, a person's
    add or take-out first."""
    choices = {d["tech_id"]: d for d in decisions.active(kinds=["catalog"])}
    out = []
    for t in get_collection("technologies").find({"enabled": {"$ne": False}},
                                                 {"name": 1, "label": 1, "aliases": 1, "imported": 1, "origin": 1,
                                                  "look_for": 1, "look_for_by": 1}):
        if decisions.in_catalog(t, choices.get(t["_id"]))["in"]:
            out.append(t)
    return out


def names_values(techs: list[dict]) -> dict:
    rows = [{"id": t["_id"], "name": display_name(t),
             "description": (((t.get("imported") or {}).get("row") or {}).get("description") or "")[:300]}
            for t in techs]
    return {"technologies": json.dumps(rows, ensure_ascii=False)}


def give_names(llm, techs: list[dict]) -> tuple[int, list[str]]:
    """Names to look for, for the technologies that have none yet. Returns
    (calls made, why each failed batch failed)."""
    waiting = [t for t in techs if not t.get("look_for")]
    prompt = PromptStore.get("technology_names")
    calls, failed = 0, []
    for i in range(0, len(waiting), NAMES_BATCH):
        chunk = waiting[i:i + NAMES_BATCH]
        calls += 1
        try:
            with with_context(skills=["technology_names"]):
                reply = parse_json(llm.ask(prompt.render(**names_values(chunk))))
            if not isinstance(reply, dict):
                raise ValueError("the reply wasn't an object")
        except Exception as exc:  # those technologies wait for the next run
            failed.append(f"{len(chunk)} technologies got no names: {str(exc)[:150]}")
            continue
        writes = []
        for t in chunk:
            r = reply.get(t["_id"]) or {}
            names = _clean([display_name(t), *(r.get("names") or [])])
            update = {"look_for": names, "look_for_by": "model", "look_for_at": now_utc()}
            if isinstance(r.get("not_a_technology"), str) and r["not_a_technology"].strip():
                update["not_a_technology"] = r["not_a_technology"].strip()[:300]
            writes.append(UpdateOne({"_id": t["_id"]}, {"$set": update}))
            t.update(update)
        if writes:
            get_collection("technologies").bulk_write(writes)
    return calls, failed


def _clean(names: list) -> list[str]:
    """Each name once (ignoring case), long enough to look for, at most 12."""
    out, seen = [], set()
    for n in names:
        if not isinstance(n, str):
            continue
        n = re.sub(r"\s+", " ", n).strip()[:80]
        key = _key(n)
        if len(n) >= MIN_CHARS and key and key not in seen:
            seen.add(key)
            out.append(n)
    return out[:12]


# ── the name match, at no model cost ─────────────────────────────────

def _key(text: str) -> str:
    return " ".join(w.lower() for w in WORD.findall(text))


def _one_word(name: str) -> bool:
    """A one-word name (eBPF, FlexE, Terraform) is matched only as it's written."""
    return len(WORD.findall(name)) == 1


def index(techs: list[dict]) -> dict[str, list[tuple[str, str | None]]]:
    """Each name's words → [(technology id, the exact form a one-word name must have)]."""
    out: dict[str, list] = defaultdict(list)
    for t in techs:
        for n in t.get("look_for") or [display_name(t)]:
            key = _key(n)
            if key and len(key.split()) <= MAX_WORDS and len(n) >= MIN_CHARS:
                entry = (t["_id"], WORD.findall(n)[0] if _one_word(n) else None)
                if entry not in out[key]:
                    out[key].append(entry)
    return out


def starts(idx: dict) -> dict[str, int]:
    """Each name's first word → the most words a name starting with it has."""
    out: dict[str, int] = {}
    for key in idx:
        first, n = key.split()[0], len(key.split())
        out[first] = max(out.get(first, 0), n)
    return out


def matches(text: str, idx: dict, first: dict[str, int] | None = None) -> dict[str, tuple[int, int]]:
    """Technology id → (times named, where first named) in a page's text."""
    first = first if first is not None else starts(idx)
    words = [(m.group(), m.start(), m.end()) for m in WORD.finditer(text)]
    low = [w[0].lower() for w in words]
    found: dict[str, list] = {}
    for i in range(len(words)):
        longest = first.get(low[i])
        if not longest:
            continue
        for n in range(1, longest + 1):
            if i + n > len(words):
                break
            hits = idx.get(" ".join(low[i:i + n]))
            if not hits:
                continue
            for tech_id, form in hits:
                if form is not None and words[i][0] != form:
                    continue
                f = found.setdefault(tech_id, [0, words[i][1]])
                f[0] += 1
    return {k: (v[0], v[1]) for k, v in found.items()}


def candidates(techs: list[dict], query: dict) -> dict[str, list[dict]]:
    """Pages that name a known technology and aren't filed under it or checked
    for it yet: technology id → [{doc_id, title, url, count, passage}]."""
    idx = index(techs)
    first = starts(idx)
    by_id = {t["_id"]: t for t in techs}
    out: dict[str, list] = defaultdict(list)

    def read(batch: list[dict]) -> None:
        texts = page_texts.get(d["_id"] for d in batch)
        for d in batch:
            text = texts.get(d["_id"]) or ""
            filed = set(d.get("technologies_resolved") or [])
            checked = {c["tech_id"] for c in d.get("name_checks") or []}
            for tech_id, (count, at) in matches(text, idx, first).items():
                if tech_id in checked or by_id[tech_id]["name"] in filed:
                    continue
                out[tech_id].append({"doc_id": d["_id"], "title": d.get("title"), "url": d.get("end_url"), "count": count,
                                     "passage": text[max(0, at - SNIPPET):at + SNIPPET].replace("\n", " ")})

    batch: list[dict] = []
    for d in get_collection("documents").find(
            {**query, "is_stub": {"$ne": True}, "ignored_by": None, "has_text": True},
            {"technologies_resolved": 1, "name_checks": 1, "title": 1, "end_url": 1}):
        batch.append(d)
        if len(batch) == TEXT_BATCH:
            read(batch)
            batch = []
    read(batch)
    return out


# ── the check, and filing ────────────────────────────────────────────

def check_values(tech: dict, pages: list[dict]) -> dict:
    desc = ((tech.get("imported") or {}).get("row") or {}).get("description") or ""
    about = f"{tech.get('label') or tech['name']} (also written: {', '.join(tech.get('look_for') or [])})"
    passages = "\n\n".join(f"[{i}] {p.get('title') or p.get('url')} (named {p['count']} times)\n…{p['passage']}…"
                           for i, p in enumerate(pages, 1))
    return {"technology": about + (f"\nWhat it is: {desc[:400]}" if desc else ""), "passages": passages}


def check(llm, tech: dict, pages: list[dict]) -> tuple[dict[str, str], int, list[str]]:
    """doc id → about | mention | other, for these pages. Returns (verdicts,
    calls made, why each failed batch failed); a failed batch stays unchecked."""
    prompt = PromptStore.get("name_check")
    verdicts, calls, failed = {}, 0, []
    for i in range(0, len(pages), CHECK_BATCH):
        chunk = pages[i:i + CHECK_BATCH]
        calls += 1
        try:
            with with_context(skills=["name_check"], tech_id=tech["_id"]):
                reply = parse_json(llm.ask(prompt.render(**check_values(tech, chunk))))
            if not isinstance(reply, dict):
                raise ValueError("the reply wasn't an object")
        except Exception as exc:
            failed.append(f"{len(chunk)} pages for {tech.get('label') or tech['name']}: {str(exc)[:150]}")
            continue
        for n, p in enumerate(chunk, 1):
            v = reply.get(str(n))
            if v in VERDICTS:
                verdicts[p["doc_id"]] = v
    return verdicts, calls, failed


def file(tech: dict, verdicts: dict[str, str], run_id: str) -> None:
    """Record each verdict on its page; a page about the technology is filed under it."""
    at, name = now_utc(), tech["name"]
    writes = []
    for doc_id, v in verdicts.items():
        update: dict = {"$push": {"name_checks": {"tech_id": tech["_id"], "verdict": v, "at": at, "run_id": run_id}}}
        if v == "about":
            update["$addToSet"] = {"technologies": name, "technologies_resolved": name}
        elif v == "mention":
            update["$addToSet"] = {"mentions": name}
        writes.append(UpdateOne({"_id": doc_id}, update))
    if writes:
        get_collection("documents").bulk_write(writes)
    if "about" in verdicts.values():  # its own name stays one of its spellings, so restamping keeps the link
        get_collection("technologies").update_one({"_id": tech["_id"]}, {"$addToSet": {"aliases": name}})


# ── a run ────────────────────────────────────────────────────────────

def start(trigger: str = "on demand", query: dict | None = None, wait: bool = False) -> str | None:
    """Look for the known technologies' names on the pages `query` picks (all
    stored pages when None). None when a run is already going."""
    with _lock:
        runs = get_collection("tag_runs")
        for r in runs.find({"status": "running"}, {"heartbeat_at": 1, "started_at": 1}):
            seen = datetime.fromisoformat(r.get("heartbeat_at") or r["started_at"])
            if datetime.fromisoformat(now_utc()) - seen < STALE_AFTER:
                return None
            runs.update_one({"_id": r["_id"]}, {"$set": {  # cut off by a restart: say so, and let this one start
                "status": "failed", "finished_at": now_utc(),
                "error": "it stopped when the server restarted; pages already checked keep their result"}})
        run_id = uuid.uuid4().hex[:12]
        runs.insert_one({"_id": run_id, "status": "running", "trigger": trigger, "started_at": now_utc(), "by": auth.by(),
                         "heartbeat_at": now_utc(), "stage": "naming", "query": query or {}, "calls": 0, "failed": []})
    if wait:
        _execute(run_id)
    else:
        jobs.start(_execute, run_id)
    return run_id


def _execute(run_id: str) -> None:
    runs = get_collection("tag_runs")
    run = runs.find_one({"_id": run_id})
    try:
        with with_context(run_kind="tag", run_id=run_id):
            llm = LLM.initialize()
            techs = known()
            calls, failed = give_names(llm, techs)
            runs.update_one({"_id": run_id}, {"$set": {"stage": "matching", "technologies": len(techs),
                                                       "calls": calls, "failed": failed}})
            found = candidates(techs, run.get("query") or {})
            by_id = {t["_id"]: t for t in techs}
            total = sum(len(v) for v in found.values())
            runs.update_one({"_id": run_id}, {"$set": {"stage": "checking", "named_on": total,
                                                       "techs_named": len(found), "done": 0}})
            counts = {v: 0 for v in VERDICTS}
            linked: list[str] = []
            tally = threading.Lock()
            progress = {"done": 0, "calls": calls}

            def one(tech_id: str) -> None:  # each technology on its own: its pages are its own
                verdicts, c, f = check(llm, by_id[tech_id], found[tech_id])
                file(by_id[tech_id], verdicts, run_id)
                with tally:
                    progress["done"] += 1
                    progress["calls"] += c
                    failed.extend(f)
                    for v in verdicts.values():
                        counts[v] += 1
                    if "about" in verdicts.values():
                        linked.append(tech_id)
                    runs.update_one({"_id": run_id}, {"$set": {
                        "done": progress["done"], "calls": progress["calls"], "failed": failed,
                        "heartbeat_at": now_utc(), **{f"pages_{k}": v for k, v in counts.items()}}})

            with ThreadPoolExecutor(max_workers=get_settings().scoring_concurrency, thread_name_prefix="tag") as pool:
                for future in [pool.submit(carry(one), t) for t in found]:
                    future.result()
            calls = progress["calls"]
            if linked:
                from agent.resolver import restamp
                restamp([by_id[t]["name"] for t in linked])  # page counts include the pages filed
        runs.update_one({"_id": run_id}, {"$set": {"status": "completed", "stage": "done", "finished_at": now_utc(),
                                                   "linked_techs": linked, "calls": calls, "failed": failed}})
    except Exception as exc:
        log.exception("tag run %s failed", run_id)
        runs.update_one({"_id": run_id}, {"$set": {"status": "failed", "error": str(exc)[:500], "finished_at": now_utc()}})


def view(run: dict | None) -> dict | None:
    if not run:
        return None
    run["id"] = run.pop("_id")
    run.pop("query", None)
    return run
