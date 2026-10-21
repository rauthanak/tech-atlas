"""What a skill turns into: the Skills page's preview.

For each of the 12 skills: when it's used, what multiplies it (with today's
counts), how many prompts the last run sent (worked out from what the runs
already store), where each blank is filled from, and one real example. The
example is built by the same fill function the run uses (scout_values,
measure_scoring_values, …) from today's settings and the stored pages, so it
can't drift from what really runs. Reads only: it never calls a model."""

import math
from collections import Counter
from string import Formatter

from agent.analyzer.engine import (build_dossier, dossier_limit, fabric_relevance_values, fabric_values,
                                   measure_scoring_values, watch_metrics_values)
from agent.analyzer.pov import pov_inputs
from agent.resolver.resolver import LABEL_BATCH, known_register, label_values, resolve_values
from agent.scout.agent import scout_values
from agent.scout.tools.collect import page_budget
from agent.scout.tools.crawl import LINK_SELECTION_WIDTH, link_selection_values
from agent.scout.tools.summarize import article_summary_values, split_text
from agent.supervisor.agent import supervisor_values
from agent.supervisor.tools.sources import collectable_query, fetch_sources
from app.horizons import HORIZONS
from app.services import evidence
from app.services.db.mongo import get_collection
from app.services.prompts.store import Prompt
from app.services.signals import snapshot
from app.services.signals.snapshot import prompt_lines
from app.settings import get_settings

CUT = 200_000          # a blank longer than this is cut for display only; the model gets all of it
CHARS_PER_TOKEN = 4    # the evidence ceiling's rule of thumb
PAGES_LISTED = 50      # newest pages offered per source
NAMES_SAMPLED = 50     # newest pages whose raw names stand in for the resolver's waiting names
TECHS_WITHOUT_RUN = 200
AGENTS = {"orchestrator", "supervisor", "scout", "analyzer"}


class BadChoice(ValueError):
    """A switch value that doesn't exist. The API answers 422 with its text."""


# ── where each blank is filled from ──────────────────────────────────

SOURCES = ("Sources", "/admin/sources")
SIGNALS = ("Signal list", "/admin/signals/list")
CRAWL = ("Settings", "/admin/sources/settings")
MEASURES = ("Scoring method › Measures", "/admin/scoring/measures")
FABRICS = ("Scoring method › Fabrics", "/admin/scoring/fabrics")
GRID = ("Scoring method › Weights & Grid", "/admin/scoring/config")
REGISTER = ("Technologies", "/admin/technologies")
CLASSIFICATION = ("Classification", "/admin/classification")
CLASSIFY_PAGES = ("Its newest pages, findings first, at most the Classify page cap (radar settings)", None)


def _blank(what: str, tag: str, where: tuple[str, str | None]) -> dict:
    """`tag` is the short origin shown inside the example; `from` the full one."""
    return {"what": what, "tag": tag, "from": where[0], "href": where[1]}


HORIZON = _blank("the horizon: H1, H2 or H3", "the horizon", ("The horizon chosen below", None))
TECHNOLOGY = _blank("the technology's name", "the technology", ("The technology chosen below", None))
EVIDENCE = _blank("each of the technology's collected pages: its summary and scout's take, newest first",
                  "collected pages",
                  ("Its collected pages, capped by the evidence ceiling in Scoring method › Weights & Grid",
                   GRID[1]))

BLANKS: dict[str, dict[str, dict]] = {
    "orchestrator": {},
    "supervisor": {"category": HORIZON},
    "scout": {
        "category": HORIZON,
        "sources": _blank("each source in the scout's batch: its id, name and address", "Sources", SOURCES),
        "max_depth": _blank("how many links deep a crawl may go", "a server setting",
                            ("Server setting SCRAPE_MAX_DEPTH, not editable here", None)),
        "max_pages": _blank("pages per source", "Settings", ("Settings › pages per source", CRAWL[1])),
    },
    "link_selection": {
        "budget": _blank("how many links to keep: the pages left for the source, at most "
                         f"{LINK_SELECTION_WIDTH}", "Settings", ("Settings › pages per source", CRAWL[1])),
        "never_miss_names": _blank("the never-miss signal names", "Signal list", SIGNALS),
        "links": _blank("the links found at this level of the crawl", "the crawl", ("The crawl", None)),
    },
    "article_summary": {
        "never_miss": _blank("each never-miss signal, with what to look for", "Signal list", SIGNALS),
        "can_ignore": _blank("each can-ignore rule", "Signal list", SIGNALS),
        "url": _blank("the page's address", "the page", ("The page chosen below", None)),
        "text": _blank("the page's text, or one part of a long page", "the page", ("The page chosen below", None)),
    },
    "technology_resolve": {
        "known_list": _blank("the established names, most pages first", "Technologies", REGISTER),
        "tech_list": _blank("the new names to fold in", "collected pages", ("Names found on collected pages", None)),
    },
    "technology_label": {
        "names": _blank("technology names without a display label yet", "Technologies", REGISTER),
    },
    "analyzer": {},
    "fabric_relevance": {
        "technology": TECHNOLOGY,
        "fabrics": _blank("each fabric switched on: its id, name and definition", "Fabrics", FABRICS),
        "evidence": EVIDENCE,
    },
    "measure_scoring": {
        "measure_name": _blank("the measure's code and name", "Measures", MEASURES),
        "definition": _blank("the measure's definition", "Measures", MEASURES),
        "anchors": _blank("what each score means", "Measures", MEASURES),
        "required_evidence": _blank("the evidence a score needs", "Measures", MEASURES),
        "technology": TECHNOLOGY,
        "fabric_name": _blank("the fabric's name", "Fabrics", FABRICS),
        "fabric_definition": _blank("the fabric's definition", "Fabrics", FABRICS),
        "tcl_today": _blank("what TCL has in this fabric today", "Fabrics", FABRICS),
        "evidence": EVIDENCE,
    },
    "watch_metrics": {"technology": TECHNOLOGY, "evidence": EVIDENCE},
    "value_levers": {
        "technology": TECHNOLOGY,
        "fabric_name": _blank("the fabric's name", "Fabrics", FABRICS),
        "fabric_definition": _blank("the fabric's definition", "Fabrics", FABRICS),
        "tcl_today": _blank("what TCL has in this fabric today", "Fabrics", FABRICS),
        "fabric_levers": _blank("the fabric's two levers, each with its mechanism", "Fabrics", FABRICS),
        "mechanisms": _blank("the four ways value reaches Tata", "Value mechanisms", ("Seeded list: value mechanisms", None)),
        "fabric_cautions": _blank("what to watch for in this fabric", "Fabrics", FABRICS),
        "fabric_blockers": _blank("the fabric's list of blockers to test", "Fabrics", FABRICS),
        "evidence": EVIDENCE,
    },
    **{name: {"technology": TECHNOLOGY,
              "evidence": _blank("its pages, numbered, findings first: source, kind, date, title, summary and the "
                                 "findings' quotes", "numbered pages", CLASSIFY_PAGES),
              **extra}
       for name, extra in {
           "evidence_strength": {"facts": _blank("all its pages, independent sources and kinds of source",
                                                 "the facts", ("Counted from all its pages", None))},
           "domain_subdomain": {"domains": _blank("each domain: its id, name and definition", "Classification",
                                                  CLASSIFICATION),
                                "subdomains": _blank("the sub-domains, grouped by domain", "Classification",
                                                     CLASSIFICATION)},
           "commercial_availability": {"availability_values": _blank("each commercial availability value",
                                                                     "Classification", CLASSIFICATION)},
           "trl_level": {"trl_levels": _blank("the TRL scale, 1 to 9, in words", "Classification", CLASSIFICATION)},
           "possible_nascent": {},
       }.items()},
    "pov": {
        "technology": _blank("the technology's display name", "the technology", ("The technology chosen below", None)),
        "assessment_data": _blank("its latest assessment: scores per fabric, TORA, placement, priority, "
                                  "watch metrics and pages read", "the assessment",
                                  ("The technology's latest assessment", None)),
    },
}


# ── the preview ──────────────────────────────────────────────────────

def preview(name: str, choices: dict[str, str], draft: dict | None = None) -> dict | None:
    """One skill's preview, or None when there's no such skill. `draft`
    ({system, prompt, variables}) builds the example from unsaved text."""
    doc = get_collection("prompts").find_one({"_id": name})
    if doc is None or name not in VIEWS:
        return None
    text = draft or doc
    template = Prompt(name=name, description=doc.get("description", ""),
                      system=text.get("system") or None, prompt=text["prompt"],
                      variables=text.get("variables") or [], version=doc.get("version", 1))
    view = VIEWS[name]({k: v for k, v in choices.items() if v})
    return {
        "skill": name,
        "version": doc.get("version", 1),
        "enabled": doc.get("enabled", True),
        "draft": draft is not None,
        "agent": name in AGENTS,
        "fires": view["fires"],
        "versions": view["versions"],
        "last_run": view["last_run"],
        "blanks": [{"name": v, **BLANKS[name].get(v, _blank("not filled by this step", "?", ("Nowhere", None)))}
                   for v in template.variables],
        "switches": view.get("switches", []),
        "example": _example(template, view),
    }


def _example(template: Prompt, view: dict) -> dict:
    out = {"parts": [], "characters": 0, "tokens_about": 0, "built_from": view.get("built_from"),
           "stand_in": view.get("stand_in"), "note": view.get("note"), "why_missing": view.get("why_missing")}
    values = view.get("values")
    if values is None:
        return out
    rendered = template.render(**values)
    parts = _parts(template, values)
    if "".join(p["text"] for p in parts) != rendered:  # never expected (tested); show the plain text then
        parts = [{"text": rendered}]
    for p in parts:
        if "blank" in p:
            p["cut"] = max(0, len(p["text"]) - CUT)
            p["text"] = p["text"][:CUT]
    return {**out, "parts": parts, "characters": len(rendered),
            "tokens_about": round(len(rendered) / CHARS_PER_TOKEN)}


def _parts(template: Prompt, values: dict) -> list[dict]:
    """The prompt as plain skill text and filled-in blanks, read the way
    str.format reads the template: doubled braces come out single."""
    f = Formatter()
    parts = [{"text": f"{template.system}\n\n"}] if template.system else []
    for literal, field, spec, conversion in f.parse(template.prompt):
        if literal:
            parts.append({"text": literal})
        if field is not None:
            value = f.format_field(f.convert_field(values[field], conversion), spec or "")
            parts.append({"blank": field, "text": value})
    return parts


# ── shared pieces ────────────────────────────────────────────────────

def _n(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _versions(sentence: str, count: int | None, per: str, up_to: bool = False,
              set_in: tuple = ()) -> dict:
    return {"sentence": sentence, "count": count, "up_to": up_to, "per": per,
            "set_in": [{"from": w, "href": h} for w, h in set_in]}


def _newest(collection: str, at: str) -> dict | None:
    return get_collection(collection).find_one(sort=[(at, -1)])


def _last(kind: str, run: dict | None, at: str, prompts: int | None = None,
          why: str | None = None, note: str | None = None) -> dict:
    """The last run of this kind and how many prompts it built (a retry isn't
    counted again), or why there's no count."""
    if run is None:
        return {"kind": kind, "run_id": None, "at": None, "status": None, "prompts": None,
                "why_missing": f"No {kind} yet.", "note": None}
    return {"kind": kind, "run_id": run["_id"], "at": run.get(at), "status": run.get("status"),
            "prompts": None if why else prompts, "why_missing": why, "note": note}


def _collection() -> dict | None:
    return _newest("runs", "run_start_date_time")


def _scoring_run() -> dict | None:
    return _newest("scoring_runs", "started_at")


def _pick(key: str, label: str, options: list[dict], chosen: str | None, missing: str) -> tuple[dict, dict | None]:
    """A switch and the option it's on: the chosen one, or else the first.
    Options may carry the record they stand for under "data" (not sent)."""
    option = options[0] if options else None
    if chosen is not None:
        option = next((o for o in options if o["value"] == chosen), None)
        if option is None:
            raise BadChoice(missing.format(chosen))
    switch = {"key": key, "label": label, "value": option["value"] if option else None,
              "options": [{k: v for k, v in o.items() if k != "data"} for o in options], "note": None}
    return switch, option


def _horizon_switch(choices: dict) -> tuple[dict, str]:
    options = [{"value": k, "label": f"{k} · {m['label']}"} for k, m in HORIZONS.items()]
    switch, option = _pick("horizon", "Horizon", options, choices.get("horizon"),
                           "no horizon {!r}: choose " + ", ".join(HORIZONS))
    return switch, option["value"]


def _tech_switch(choices: dict) -> tuple[dict, dict | None]:
    """The technologies a scoring skill is shown for: the latest assessment
    run's, most pages first; before any run, the ones with the most pages."""
    run = _scoring_run()
    if run:
        rows = [{"tech_id": t["tech_id"], "name": t["name"], "doc_count": t.get("doc_count", 0)}
                for t in run["technologies"]]
        where = "in the latest assessment run"
    else:
        rows = [{"tech_id": t["_id"], "name": t["name"], "doc_count": t.get("doc_count", 0)}
                for t in get_collection("technologies").find({"enabled": True}, {"name": 1, "doc_count": 1})
                .sort("doc_count", -1).limit(TECHS_WITHOUT_RUN)]
        where = "among the technologies with the most pages"
    labels = {t["_id"]: t.get("label") for t in get_collection("technologies").find(
        {"_id": {"$in": [r["tech_id"] for r in rows]}}, {"label": 1})}
    options = [{"value": r["tech_id"], "label": f"{labels.get(r['tech_id']) or r['name']} · {_n(r['doc_count'], 'page')}",
                "data": {**r, "label": labels.get(r["tech_id"]) or r["name"]}} for r in rows]
    switch, option = _pick("technology", "Technology", options, choices.get("technology"),
                           "no technology {!r} " + where)
    return switch, option["data"] if option else None


def _dossier(name: str) -> str:
    return build_dossier(name, dossier_limit(list(get_collection("scoring_config").find())))["text"]


def _evidence_for(tech: dict | None) -> tuple[str | None, str | None]:
    """(dossier, why it's missing)."""
    if tech is None:
        return None, "No technologies yet: run a collection, then organize technologies."
    dossier = _dossier(tech["name"])
    return (dossier, None) if dossier else (None, f"No collected pages are linked to {tech['label']} yet.")


SCORING_BUILT_FROM = "Today's measures and fabrics, and the pages collected so far."


# ── one view per skill ───────────────────────────────────────────────

def _orchestrator(choices: dict) -> dict:
    run = _collection()
    return {
        "fires": "Once per collection run. It's an agent's standing instructions: the agent carries "
                 "them on every step it takes, at most 20.",
        "versions": _versions("One version: the text has no blanks.", 1, "collection run"),
        "last_run": _last("collection", run, "run_start_date_time", 1),
        "values": {},
        "built_from": "The skill's text alone: it has no blanks.",
    }


def _supervisor(choices: dict) -> dict:
    run = _collection()
    switch, horizon = _horizon_switch(choices)
    ran = len((run.get("params") or {}).get("categories") or HORIZONS) if run else None
    return {
        "fires": "Once per horizon in a collection run. It's an agent's standing instructions, "
                 "carried on every step it takes, at most 20.",
        "versions": _versions(f"{_n(len(HORIZONS), 'version')}, one per horizon: {', '.join(HORIZONS)}.",
                              len(HORIZONS), "collection run"),
        "last_run": _last("collection", run, "run_start_date_time", ran),
        "switches": [switch],
        "values": supervisor_values(horizon),
        "built_from": "The horizon chosen above.",
    }


def _scout(choices: dict) -> dict:
    settings = get_settings()
    per = settings.sources_per_scout
    run = _collection()
    switch, horizon = _horizon_switch(choices)
    counts = {h: len(fetch_sources(h)) for h in HORIZONS}
    total = sum(math.ceil(n / per) for n in counts.values())
    ran = None
    if run:
        by = Counter(s["category"] for s in run.get("sources") or [])
        ran = sum(math.ceil(n / per) for n in by.values())
    sources = fetch_sources(horizon)
    values = note = why = None
    if sources:
        values = scout_values(horizon, sources[:per], settings.scrape_max_depth, page_budget(snapshot.build()))
        if len(sources) > per:
            note = (f"{horizon} has {_n(len(sources), 'source')}, so {math.ceil(len(sources) / per)} scouts: "
                    "this is the first one's batch.")
    else:
        why = f"No sources are switched on in {horizon}."
    return {
        "fires": f"Once per batch of up to {per} sources in a horizon (server setting SOURCES_PER_SCOUT). "
                 "It's an agent's standing instructions, carried on every step it takes: at most 10, "
                 "plus 4 per source.",
        "versions": _versions(f"{_n(total, 'version')} per collection run, one per batch of up to {per} sources: "
                              + ", ".join(f"{h} has {_n(n, 'source')}" for h, n in counts.items()) + ".",
                              total, "collection run", set_in=(SOURCES, CRAWL)),
        "last_run": _last("collection", run, "run_start_date_time", ran),
        "switches": [switch],
        "values": values, "note": note, "why_missing": why,
        "built_from": "Today's sources and crawl settings.",
    }


def _link_selection(choices: dict) -> dict:
    settings = get_settings()
    snap = snapshot.build()
    pages = page_budget(snap)
    depth = settings.scrape_max_depth
    websites = list(get_collection("sources").find({**collectable_query(), "access": "crawl"}).sort("name", 1))
    options = [{"value": s["source_id"], "label": s["name"], "data": s} for s in websites]
    switch, option = _pick("source", "Source", options, choices.get("source"),
                           "no website {!r} is switched on")
    values = why = stand_in = None
    if option:
        links = list(dict.fromkeys(d["end_url"] for d in get_collection("documents").find(
            {"source_id": option["value"], "end_url": {"$nin": [None, ""]}}, {"end_url": 1})
            .sort("scraped_at", -1).limit(pages)))
        if links:
            values = link_selection_values(links, min(pages, LINK_SELECTION_WIDTH),
                                           prompt_lines(snap["signal_list"])["never_miss_names"])
            stand_in = ("The crawler doesn't keep the links it was offered, so {links} here is this "
                        "source's pages from the collections so far.")
        else:
            why = f"No pages collected from {option['data']['name']} yet: run a collection first."
    else:
        why = "No websites are switched on in Sources."
    return {
        "fires": "At each level of a website's crawl that finds more links than it may follow: "
                 f"the smaller of the pages left and {LINK_SELECTION_WIDTH} (fixed in code).",
        "versions": _versions(f"Up to {depth} crawl levels × {_n(len(websites), 'website')} = "
                              f"up to {depth * len(websites):,} per collection run.",
                              depth * len(websites), "collection run", up_to=True,
                              set_in=(SOURCES, ("Server setting SCRAPE_MAX_DEPTH", None))),
        "last_run": _last("collection", _collection(), "run_start_date_time",
                          why="Not counted: the crawler doesn't record link-selection calls."),
        "switches": [switch],
        "values": values, "stand_in": stand_in, "why_missing": why,
        "built_from": "Today's signal list and crawl settings, and this source's collected pages.",
    }


def _article_summary(choices: dict) -> dict:
    snap = snapshot.build()
    size = int(snap["crawl_settings"].get("page_part_chars") or 120000)
    pages = page_budget(snap)
    sources = list(get_collection("sources").find(collectable_query()).sort("name", 1))
    options = [{"value": s["source_id"], "label": s["name"], "data": s} for s in sources]
    source_switch, source = _pick("source", "Source", options, choices.get("source"),
                                  "no source {!r} is switched on")
    page_options: list[dict] = []
    if source:
        readable = {"source_id": source["value"], "is_stub": {"$ne": True},
                    "extracted_text": {"$nin": [None, ""]}}
        shown = {"title": 1, "end_url": 1, "scraped_at": 1}
        docs = list(get_collection("documents").find(readable, shown).sort("scraped_at", -1).limit(PAGES_LISTED))
        wanted = choices.get("page")
        if wanted and all(d["_id"] != wanted for d in docs):  # an older page of this source, from a link
            older = get_collection("documents").find_one({**readable, "_id": wanted}, shown)
            docs = [older, *docs] if older else docs
        page_options = [{"value": d["_id"], "label": f"{d.get('title') or d.get('end_url')} · "
                                                     f"{str(d.get('scraped_at'))[:10]}"} for d in docs]
    page_switch, page = _pick("page", "Page", page_options, choices.get("page"),
                              "no page {!r} from this source")
    values = note = why = None
    if page:
        doc = get_collection("documents").find_one({"_id": page["value"]}, {"end_url": 1, "extracted_text": 1})
        text = doc["extracted_text"]
        parts = split_text(text, size)
        if len(parts) > 1:
            note = (f"This page is longer than {size:,} characters, so it's split into {len(parts)} parts: "
                    f"{len(parts)} prompts like this one, plus one merge. This is part 1.")
            text = parts[0]
        values = article_summary_values(doc["end_url"], text, prompt_lines(snap["signal_list"]))
    elif source:
        why = f"No pages collected from {source['data']['name']} yet: run a collection first."
    else:
        why = "No sources are switched on in Sources."
    run = _collection()
    sent = None
    if run:
        sent = sum((d.get("parts") or 1) + 1 if (d.get("parts") or 1) > 1 else 1
                   for d in get_collection("documents").find({"run_id": run["_id"], "is_stub": {"$ne": True}},
                                                             {"parts": 1}))
    return {
        "fires": f"Once per new or changed page. A page longer than {size:,} characters is split: "
                 "once per part, plus one merge.",
        "versions": _versions(f"One per page: up to {pages} pages × {_n(len(sources), 'source')} = "
                              f"up to {pages * len(sources):,} per collection run, plus one per extra part "
                              "of a long page.", pages * len(sources), "collection run", up_to=True,
                              set_in=(CRAWL, SOURCES, SIGNALS)),
        "last_run": _last("collection", run, "run_start_date_time", sent),
        "switches": [source_switch, page_switch],
        "values": values, "note": note, "why_missing": why,
        "built_from": "Today's signal list and crawl settings, and the page chosen above.",
    }


def _technology_resolve(choices: dict) -> dict:
    settings = get_settings()
    docs = get_collection("documents").find(
        {"technologies": {"$exists": True, "$ne": []}, "ignored_by": None},
        {"technologies": 1}).sort("scraped_at", -1).limit(NAMES_SAMPLED)
    names = sorted({t for d in docs for t in d["technologies"]})
    organize = _newest("resolves", "started_at")
    return {
        "fires": "When technologies are organized: pass 1 over the names not yet in the register, then "
                 f"pass 2 over all names, in chunks of up to {settings.resolve_batch_size:,}.",
        "versions": _versions(f"One per chunk of up to {settings.resolve_batch_size:,} names, in two passes. "
                              f"Each carries the register's {settings.resolve_known_limit:,} names with the "
                              "most pages.", None, "organize",
                              set_in=(("Server settings RESOLVE_BATCH_SIZE and RESOLVE_KNOWN_LIMIT", None),)),
        "last_run": _last("organize", organize, "started_at", (organize or {}).get("llm_calls"),
                          note="Counted together with Technology label: the organize record doesn't "
                               "split them."),
        "values": resolve_values(names, known_register(settings.resolve_known_limit)) if names else None,
        "stand_in": "After an organize no names are waiting, so {tech_list} here is the raw names found "
                    f"on the {NAMES_SAMPLED} newest pages." if names else None,
        "why_missing": None if names else "No collected pages yet: run a collection first.",
        "built_from": "Today's technology register and the newest collected pages.",
    }


def _technology_label(choices: dict) -> dict:
    techs = get_collection("technologies")
    waiting = sorted(t["name"] for t in techs.find({"label": {"$in": [None, ""]}}, {"name": 1}))
    names, stand_in = waiting[:LABEL_BATCH], None
    if not names:
        names = sorted(t["name"] for t in techs.find({}, {"name": 1}))[:LABEL_BATCH]
        if names:
            stand_in = ("No names are waiting for their capitals today, so {names} here is the first "
                        f"{LABEL_BATCH} names in the register.")
    organize = _newest("resolves", "started_at")
    batches = math.ceil(len(waiting) / LABEL_BATCH)
    return {
        "fires": f"When technologies are organized: once per batch of up to {LABEL_BATCH} names that "
                 "have no display capitals yet.",
        "versions": _versions(f"One per batch of up to {LABEL_BATCH} names without a label. "
                              + (f"{_n(len(waiting), 'name')} waiting today, so {_n(batches, 'prompt')} at the "
                                 "next organize." if waiting else "None are waiting today."), batches, "organize"),
        "last_run": _last("organize", organize, "started_at", (organize or {}).get("llm_calls"),
                          note="Counted together with Technology resolve: the organize record doesn't "
                               "split them."),
        "values": label_values(names) if names else None,
        "stand_in": stand_in,
        "why_missing": None if names else "No technologies yet: run a collection, then organize technologies.",
        "built_from": "Today's technology register.",
    }


def _analyzer(choices: dict) -> dict:
    run = _scoring_run()
    return {
        "fires": "Once per assessment run. It's an agent's standing instructions, carried on every step "
                 "it takes, at most 60; after that a backup loop assesses whatever is left.",
        "versions": _versions("One version: the text has no blanks.", 1, "assessment run"),
        "last_run": _last("assessment run", run, "started_at", 1),
        "values": {},
        "built_from": "The skill's text alone: it has no blanks.",
    }


def _fabric_relevance(choices: dict) -> dict:
    run = _scoring_run()
    switch, tech = _tech_switch(choices)
    dossier, why = _evidence_for(tech)
    fabrics = list(get_collection("fabrics").find({"enabled": True}))
    return {
        "fires": "Once per technology in an assessment run, before it's scored.",
        "versions": _versions("One per technology, built from its own pages"
                              + (f": {len(run['technologies']):,} in the latest assessment run." if run else "."),
                              1, "technology", set_in=(FABRICS, GRID)),
        "last_run": _last("assessment run", run, "started_at", len((run or {}).get("gates") or {})),
        "switches": [switch],
        "values": fabric_relevance_values(tech["name"], fabrics, dossier) if dossier else None,
        "why_missing": why,
        "built_from": SCORING_BUILT_FROM,
    }


def _measure_scoring(choices: dict) -> dict:
    run = _scoring_run()
    tech_switch, tech = _tech_switch(choices)
    measures = list(get_collection("measures").find())
    fabrics = list(get_collection("fabrics").find({"enabled": True}))
    gated = ((run or {}).get("gates") or {}).get(tech["tech_id"]) if tech else None
    fabric_options = [{"value": f["_id"], "label": f["name"], "scored_last_run": bool(gated) and f["_id"] in gated,
                       "data": f} for f in fabrics]
    first_scored = next((f["_id"] for f in fabrics if gated and f["_id"] in gated), None)
    fabric_switch, fabric = _pick("fabric", "Fabric", fabric_options, choices.get("fabric") or first_scored,
                                  "no fabric {!r} is switched on")
    if tech and gated:
        names = [f["name"] for f in fabrics if f["_id"] in gated]
        fabric_switch["note"] = (f"The last run scored {tech['label']} in {', '.join(names)}: "
                                 f"{_n(len(names) * len(measures), 'prompt')}.")
    elif tech and run:
        fabric_switch["note"] = f"The latest assessment run hasn't scored {tech['label']}."
    measure_options = [{"value": m["_id"], "label": f"{m.get('code')} {m.get('name')}", "data": m}
                       for m in measures]
    measure_switch, measure = _pick("measure", "Measure", measure_options, choices.get("measure"),
                                    "no measure {!r}")
    dossier, why = _evidence_for(tech)
    sent = None
    if run:
        rows = list(get_collection("assessments").aggregate([
            {"$match": {"scoring_run_id": run["_id"]}},
            {"$group": {"_id": None, "n": {"$sum": {"$size": {"$objectToArray": {"$ifNull": ["$measures", {}]}}}}}}]))
        sent = rows[0]["n"] if rows else 0
    values = None
    if dossier and fabric and measure:
        values = measure_scoring_values(measure["data"], tech["name"], fabric["data"], dossier)
    stacked = (get_collection("scoring_config").find_one({"_id": "engine"}) or {}).get("mode") == "stacked"
    return {
        "fires": ("Inside an assessment's stacked calls: the measures judged for the technology as a whole go in "
                  "its technology call, the others in the call for each fabric Fabric relevance picked "
                  "(Weights & Grid › How an assessment calls the model)." if stacked else
                  "Once per measure, for each fabric Fabric relevance picked, for each technology in an "
                  "assessment run."),
        "versions": _versions(f"{_n(len(measures), 'measure')}, each once per technology or once per fabric."
                              if stacked else
                              f"{_n(len(measures), 'measure')} × up to {_n(len(fabrics), 'fabric')} = up to "
                              f"{len(measures) * len(fabrics):,} versions per technology.",
                              len(measures) * len(fabrics), "technology", up_to=True,
                              set_in=(MEASURES, FABRICS)),
        "last_run": _last("assessment run", run, "started_at", sent),
        "switches": [tech_switch, fabric_switch, measure_switch],
        "values": values,
        "why_missing": why or (None if fabric and measure else "No fabric or measure to show: check Scoring method."),
        "built_from": SCORING_BUILT_FROM,
    }


def _watch_metrics(choices: dict) -> dict:
    run = _scoring_run()
    switch, tech = _tech_switch(choices)
    dossier, why = _evidence_for(tech)
    sent = len(get_collection("assessments").distinct("tech_id", {"scoring_run_id": run["_id"]})) if run else None
    return {
        "fires": "Once per technology in an assessment run, after its fabrics are scored.",
        "versions": _versions("One per technology, built from its own pages.", 1, "technology", set_in=(GRID,)),
        "last_run": _last("assessment run", run, "started_at", sent),
        "switches": [switch],
        "values": watch_metrics_values(tech["name"], dossier) if dossier else None,
        "why_missing": why,
        "built_from": SCORING_BUILT_FROM,
    }


def _pov(choices: dict) -> dict:
    targets = evidence.latest_assessments(evidence.states())
    techs = {t["_id"]: t for t in get_collection("technologies").find(
        {"_id": {"$in": [t["tech_id"] for t in targets]}}, {"label": 1, "doc_count": 1})}
    targets.sort(key=lambda t: (-(techs.get(t["tech_id"], {}).get("doc_count") or 0), t["technology"]))
    options = [{"value": t["tech_id"], "data": t,
                "label": f"{techs.get(t['tech_id'], {}).get('label') or t['technology']} · "
                         f"assessed {str(t['assessed_at'])[:10]}"} for t in targets]
    switch, option = _pick("technology", "Technology", options, choices.get("technology"),
                           "no technology {!r} has an assessment")
    run = _scoring_run()
    written = get_collection("povs").count_documents({"scoring_run_id": run["_id"]}) if run else None
    values = pov_inputs(option["data"]["scoring_run_id"], option["value"])[1] if option else None
    return {
        "fires": "Once per technology, when Points of View are written.",
        "versions": _versions("One per technology with an assessment, written from its latest one.",
                              1, "technology", set_in=(MEASURES, GRID)),
        "last_run": _last("assessment run", run, "started_at", written,
                          note="Points of View written from this run's assessments."),
        "switches": [switch],
        "values": values,
        "why_missing": None if option else "No technology has an assessment yet: run an assessment first.",
        "built_from": "The technology's latest assessment, laid out with that run's measures and priority grid.",
    }


def _value_levers(choices: dict) -> dict:
    from agent.analyzer import value
    run = _scoring_run()
    tech_switch, tech = _tech_switch(choices)
    fabrics = list(get_collection("fabrics").find({"enabled": True}))
    options = [{"value": f["_id"], "label": f["name"], "data": f} for f in fabrics]
    fabric_switch, fabric = _pick("fabric", "Fabric", options, choices.get("fabric"), "no fabric {!r} is switched on")
    dossier, why = _evidence_for(tech)
    values = None
    if dossier and fabric:
        f = fabric["data"]
        values = {"technology": tech["name"], "evidence": dossier, **fabric_values(f),
                  **value.task_values(f, value.mechanisms())}
    return {
        "fires": "Once per fabric a technology is assessed in, stacked in that fabric's call with its measures.",
        "versions": _versions("One per technology and fabric it's assessed in.", 1, "fabric", set_in=(FABRICS,)),
        "last_run": _last("assessment run", run, "started_at"),
        "switches": [tech_switch, fabric_switch],
        "values": values,
        "why_missing": why,
        "built_from": SCORING_BUILT_FROM,
    }


def _classify_view(name: str):
    def view(choices: dict) -> dict:
        from agent.classifier.classify import classification_tasks, list_values, lists
        from agent.classifier.evidence import pack
        from app.services.settings_store import radar_settings
        switch, tech = _tech_switch(choices)
        cap = int(radar_settings()["classify_pages_cap"])
        run = _newest("classify_runs", "started_at")
        values, why = None, None
        if tech is None:
            why = "No technologies yet: run a collection, then organize technologies."
        else:
            ev = pack(tech["name"], cap)
            if not ev["pages"]:
                why = f"No collected pages are linked to {tech['label']} yet."
            else:
                task = next(t for t in classification_tasks(list_values(lists())) if t.skill == name)
                values = {"technology": tech["label"], "evidence": ev["text"], "facts": ev["facts"], **task.values}
                values = {k: values[k] for k in BLANKS[name]}
        return {
            "fires": "Once per technology with new pages, after organizing, stacked with the other classification "
                     "skills in one Classify call.",
            "versions": _versions(f"One per technology, built from its own pages (at most {cap}).", 1, "technology",
                                  set_in=(CLASSIFICATION,)),
            "last_run": _last("classify run", run, "started_at", (run or {}).get("done")),
            "switches": [switch],
            "values": values,
            "why_missing": why,
            "built_from": "Its newest pages and the classification lists today.",
        }
    return view


VIEWS = {
    "orchestrator": _orchestrator,
    "supervisor": _supervisor,
    "scout": _scout,
    "link_selection": _link_selection,
    "article_summary": _article_summary,
    "technology_resolve": _technology_resolve,
    "technology_label": _technology_label,
    "analyzer": _analyzer,
    "fabric_relevance": _fabric_relevance,
    "measure_scoring": _measure_scoring,
    "watch_metrics": _watch_metrics,
    "pov": _pov,
    "value_levers": _value_levers,
    **{name: _classify_view(name) for name in
       ("evidence_strength", "domain_subdomain", "commercial_availability", "trl_level", "possible_nascent")},
}
