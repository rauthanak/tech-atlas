"""Where Find evidence can look for one technology: the vertical search,
built from the radar's own sources so it follows them as they're added or
switched on and off.

  kind      built from                                              searched by
  search    each data source whose connector takes words and lists  Adapter.top
  counts    each digest data source whose connector takes words     Adapter.digest_item
  websites  every switched-on website, as one place                 the web search, limited to their hosts
  web       the web search                                          the web search

A place that can't be searched now says why (`why`); a connector that searches
by company, not words, isn't a place for a technology, so it isn't listed."""

from urllib.parse import urlparse

from agent.scout.tools.adapters import REGISTRY
from agent.supervisor.tools.sources import collectable_query
from app.services import websearch
from app.services.db.mongo import get_collection
from app.settings import get_settings

WEBSITES, WEB = "radar_websites", "web"


def hosts() -> dict[str, str]:
    """Each switched-on website's host → its source_id (a page found there is filed under it)."""
    found: dict[str, str] = {}
    for s in get_collection("sources").find({"$and": [collectable_query(), {"access": "crawl"}]}, {"url": 1}):
        host = urlparse(s.get("url") or "").netloc.removeprefix("www.")
        if host:
            found.setdefault(host, s["_id"])
    return found


ORDER = ["openalex_works", "openalex_awards", "openalex_trends", "epo_ops", "epo_trends", "usajobs"]  # research, then patents, then jobs
KEY_WORDS = {"EPO_OPS_KEY": "the patent office's free key", "USAJOBS_API_KEY": "a free USAJOBS key",
             "OPENALEX_API_KEY": "a free OpenAlex key"}


def places() -> list[dict]:
    """[{id, label, gives, kind, source_id, available, why}], data sources first, the web last.
    A connector searched by company, not by words, isn't a place at all, so it isn't listed."""
    web_ok = websearch.configured()
    no_web = None if web_ok else "not set up yet: needs a web search (an Anthropic key and model, set by your administrator)"
    paid_ok = get_settings().include_paid_sources
    rows: list[dict] = []
    by_order = lambda s: (ORDER.index(s.get("adapter")) if s.get("adapter") in ORDER else len(ORDER), s["name"])
    for s in sorted(get_collection("sources").find({"access": "query"}), key=by_order):
        adapter = REGISTRY.get(s.get("adapter") or "")
        if adapter is None or not adapter.by_name:
            continue
        why = None
        if missing := adapter.missing_keys():
            needs = " and ".join(dict.fromkeys(KEY_WORDS.get(k, k) for k in missing if k != "EPO_OPS_SECRET"))
            why = f"not set up yet: needs {needs}, which your administrator adds (see the Deployment Guide)"
        elif s.get("cost") == "licensed" and not paid_ok:
            why = "licensed: off until Tata gives access"
        elif not s.get("enabled"):
            why = "switched off in Sources" + (f": {s['note']}" if s.get("note") else "")
        rows.append({"id": s["_id"], "label": adapter.find_label or s["name"], "gives": adapter.find_gives,
                     "kind": "counts" if adapter.digest else "search", "source_id": s["_id"],
                     "available": why is None, "why": why})
    sites = len(hosts())
    rows.append({"id": WEBSITES, "label": "The radar's websites", "kind": "websites", "source_id": None,
                 "gives": f"one web search across all {sites} websites the radar reads, keeping its best results",
                 "available": web_ok and bool(sites), "why": no_web or (None if sites else "no website is switched on")})
    rows.append({"id": WEB, "label": "The whole web", "kind": "web", "source_id": None,
                 "gives": "one web search of the whole web, keeping its best results", "available": web_ok, "why": no_web})
    return rows


def names(tech: dict) -> list[str]:
    """The technology's names to search under: its label, name and aliases, at most 3."""
    out: list[str] = []
    for n in [tech.get("label"), tech.get("name"), *(tech.get("aliases") or [])]:
        n = (n or "").strip()
        if n and n.lower() not in {o.lower() for o in out}:
            out.append(n)
    return out[:3]
