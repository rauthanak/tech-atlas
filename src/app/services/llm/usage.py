"""Every model call, recorded: one `llm_calls` document per call with its
tokens, how long it took, whether it worked (and why not), and what it was
for (services/llm/context). Tokens are stored the same way for every
provider: `input_tokens` were sent and paid in full, `cache_read_tokens` were
reused from an earlier call at a fraction of the price, `cache_write_tokens`
were stored for reuse. Recording never breaks a call."""

import logging
import uuid

from app.services.db.mongo import get_collection
from app.services.llm.context import call_context
from app.services.timezone import now_utc

log = logging.getLogger(__name__)


def anthropic_usage(usage) -> dict:
    return {"input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0}


def openai_usage(usage) -> dict:
    cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
    return {"input_tokens": (getattr(usage, "input_tokens", 0) or 0) - cached,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_read_tokens": cached, "cache_write_tokens": 0}


def langchain_usage(metadata: dict | None) -> dict:
    """LangChain's usage_metadata, whose input count includes reused tokens."""
    m = metadata or {}
    details = m.get("input_token_details") or {}
    read, write = details.get("cache_read") or 0, details.get("cache_creation") or 0
    return {"input_tokens": max(0, (m.get("input_tokens") or 0) - read - write),
            "output_tokens": m.get("output_tokens") or 0,
            "cache_read_tokens": read, "cache_write_tokens": write}


def record(provider: str, model: str, tokens: dict | None, ms: int, ok: bool,
           error: str | None = None, context: dict | None = None, reasoning: bool | None = None) -> None:
    ctx = context if context is not None else call_context.get()
    doc = {"_id": uuid.uuid4().hex, "at": now_utc(),
           "run_kind": ctx.get("run_kind"), "run_id": ctx.get("run_id"), "tech_id": ctx.get("tech_id"),
           "fabric_id": ctx.get("fabric_id"), "recipe": ctx.get("recipe"), "skills": ctx.get("skills") or [],
           "provider": provider, "model": model, "ms": ms, "ok": ok, "reasoning": reasoning,
           **{"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
           **(tokens or {})}
    if error:
        doc["error"] = error[:300]
    try:
        get_collection("llm_calls").insert_one(doc)
    except Exception as exc:  # the call itself matters more than its record
        log.warning("could not record a model call: %s", exc)
