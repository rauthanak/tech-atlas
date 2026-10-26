"""A stand-in for the model, for timing the radar's own work at scale with no
model cost (the 10-million-page test, 24 Oct). Used only with
MODEL_PROVIDER=standin; never in production.

It answers each skill in the shape that skill asks for, at once (or after
STANDIN_DELAY_MS), so every step runs as it would: pages are crawled for real,
read (naming technologies the database already knows, and now and then a
funding round), organized, classified, assessed and written up. The model's
own time is added afterwards from live averages per call. Its calls are
recorded like real ones (provider "standin", no tokens)."""

import hashlib
import itertools
import json
import os
import re
import time

from app.services.llm import usage

DELAY_S = int(os.getenv("STANDIN_DELAY_MS", "0")) / 1000
_names: list[str] = []


def _known() -> list[str]:
    """Names of technologies already known, for pages to mention (read once)."""
    if not _names:
        from app.services.db.mongo import get_collection
        _names.extend(t["name"] for t in get_collection("technologies").find(
            {"page_count": {"$gte": 3}}, {"name": 1}).limit(2000))
    return _names or ["edge computing", "agentic ai"]


def _pick(seed: str, n: int) -> list[str]:
    names = _known()
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    return [names[(h >> (8 * i)) % len(names)] for i in range(n)]


def _measure(text: str = "") -> dict:
    cited = re.search(r"url: (\S+)", text)  # a page from the evidence it was given, as a real answer cites
    return {"score": 6, "justification": "The evidence shows it (stand-in).",
            "evidence_urls": [cited.group(1) if cited else "https://example.com/standin"],
            "counter_case": "Stand-in.", "unscorable": False, "missing": None}


def _answer(skill: str, text: str):
    """One skill's reply, as JSON-ready data (or text, for link_selection)."""
    if skill == "article_summary":
        url = text.split("URL:")[-1][:300]
        funding = int(hashlib.sha1(url.encode()).hexdigest(), 16) % 5 == 0
        return {"summary": "A page read by the stand-in model.", "technologies": _pick(url, 2),
                "scout_take": "Stand-in read.", "ignore": None,
                "signals": [{"signal": "Funding round", "label": None, "what": "Stand-in raised money",
                             "who": "Stand-in Co", "when": "2026-10", "quote": "Stand-in Co raised $1M.",
                             "implication": "i"}] if funding else []}
    if skill == "link_selection":
        return "\n".join(re.findall(r"https?://\S+", text.split("{links}")[-1])[:25])
    if skill == "technology_resolve":
        return {"groups": []}
    if skill == "technology_label":
        return {"labels": {}}
    if skill == "evidence_strength":
        return {"verdict": "enough", "reason": "Stand-in.", "pages": [1]}
    if skill == "domain_subdomain":
        return {"domain_id": "other", "subdomain": None, "subdomain_new": None, "reason": "Stand-in.", "pages": [1]}
    if skill == "commercial_availability":
        return {"value_id": "early_commercial", "reason": "Stand-in.", "pages": [1]}
    if skill == "trl_level":
        return {"level": 6, "reason": "Stand-in.", "missing": None, "pages": [1]}
    if skill == "possible_nascent":
        return {"flag": False}
    if skill == "fabric_relevance":
        return {"fabrics": ["cloud"]}
    if skill == "watch_metrics":
        return [{"metric": "Paying customers", "current_value": "100 in Oct 2026", "source": "",
                 "inflection_threshold": "1,000", "direction": "rising", "implication": "Proven demand."}]
    if skill == "value_levers":
        return {"use_cases": [], "no_use_case": {"reason": "Stand-in.", "evidence_needed": "A named buyer."}}
    if skill == "pov":
        return {"headline": "A stand-in Point of View.", "background": "Stand-in.", "maturity": "Stand-in.",
                "value": "Stand-in.", "summary": "Stand-in.", "tora_analysis": {}, "other_measures": "Stand-in.",
                "placement_rationale": "Stand-in.", "evidence_gaps": [], "recommendation": "Monitor."}
    if skill == "technology_names":
        return {i: {"names": [], "not_a_technology": None} for i in re.findall(r"^\s*-?\s*([\w.-]+):", text, re.M)}
    if skill == "name_check":
        return {n: "about" for n in re.findall(r"^\s*\[?(\d+)\]?[.:)]", text, re.M)}
    return _measure(text)  # measure_scoring, and anything else that asks for one measure


def _skill_of(key: str) -> str:
    return "measure_scoring" if key.startswith("measure") else key


class StandIn:
    """Has what the radar's model client has: ask, chat_model, web_search."""

    provider, model_name = "standin", "standin"

    def ask(self, prompt: str, system: str | None = None, *, blocks: list[str] | None = None) -> str:
        from app.services.llm.context import call_context
        start = time.monotonic()
        if DELAY_S:
            time.sleep(DELAY_S)
        text = "\n".join([*(blocks or []), system or "", prompt])
        keys = re.search(r"Its keys are exactly: (.*?)\. Under", text)
        if keys:  # a stacked call: each task's answer under its key
            reply = {k: _answer(_skill_of(k), text) for k in keys.group(1).split(", ")}
        else:
            skills = call_context.get().get("skills") or ["measure_scoring"]
            reply = _answer(skills[0], text)
        usage.record(self.provider, self.model_name, None, int((time.monotonic() - start) * 1000), ok=True)
        return reply if isinstance(reply, str) else json.dumps(reply)

    def chat_model(self):
        """The crawl's steering agents: each says it's done, and the fixed sweep after it
        collects every source, as when an agent skips one."""
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage

        class Done(GenericFakeChatModel):
            def bind_tools(self, tools, **kw):
                return self

        return Done(messages=itertools.repeat(AIMessage(content="done")))

    def web_search(self, query: str, n: int) -> list[dict]:
        return []
