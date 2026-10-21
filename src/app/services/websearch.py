"""Web search for Find evidence: whether it's set up, and search(query, n)
→ [{url, title}]. The search itself is a model call, so it goes through the
LLM adapter (LLM.web_search) and is recorded like any other.

The provider is WEB_SEARCH_PROVIDER in .env: `anthropic` (the model
provider's own web search, on the same key; the default when an Anthropic
key is set), or `none`."""

import os
from urllib.parse import urlparse

from app.services.llm import LLM
from app.settings import get_settings

# the seeded "Web search" source every page Find evidence reads is stored under
SOURCE = {"source_id": "web_search", "url": "https://web-search", "name": "Web search", "horizon": "H2"}


def site(url: str) -> str:
    return urlparse(url or "").netloc.removeprefix("www.")


def source_of(doc: dict) -> str | None:
    """The independent source a page counts as: its source, except that a
    page found by web search counts as its own site (arxiv.org and
    partnershiponai.org are two voices, not one "Web search")."""
    if doc.get("source_id") == SOURCE["source_id"]:
        return site(doc.get("end_url") or "") or SOURCE["source_id"]
    return doc.get("source_id")


class NotConfigured(RuntimeError):
    """No web search is set up; the message says what's needed."""


def provider() -> str:
    chosen = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
    if chosen:
        return chosen
    return "anthropic" if get_settings().anthropic_api_key else "none"


def configured() -> bool:
    """An Anthropic search needs the key and an Anthropic model to run it."""
    return provider() == "anthropic" and bool(get_settings().anthropic_api_key) and \
        LLM.initialize().provider == "anthropic"


def search(query: str, n: int) -> list[dict]:
    if not configured():
        raise NotConfigured("Find evidence needs a web search: it uses the Anthropic model's own search, so set "
                            "ANTHROPIC_API_KEY and an Anthropic MODEL_NAME in the server's .env. Add a link works without it.")
    return LLM.initialize().web_search(query, n)
