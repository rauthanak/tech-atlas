"""LLM access. The single place model logic lives.

Usage everywhere else in the app:

    from app.services.llm import LLM

    llm = LLM.initialize("gpt-5.6-luna")   # or LLM.initialize() for the .env default
    reply = llm.ask("...")                 # call at any point, as often as needed

Provider is inferred from the model name (claude-* → anthropic, otherwise
MODEL_PROVIDER from .env); API keys come from .env. No other module may talk
to a model SDK directly.

Every call is recorded with its tokens (services/llm/usage), labelled by the
caller's context (services/llm/context). Fixed text that repeats from call to
call goes in `blocks`: Anthropic is asked to reuse it (prompt caching), and
OpenAI reuses an identical opening on its own.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

import json_repair

from app.services.llm import usage
from app.services.llm.context import call_context
from app.settings import get_settings

log = logging.getLogger(__name__)

MAX_TOKENS = 64000  # the longest reply asked for; streamed, so long replies don't time out
BACKOFFS = (5, 15, 30, 60, 120)  # seconds between retries of a failed model call


def parse_json(reply: str):
    """The JSON value in a model reply, tolerating ``` fences and prose around
    it (providers differ in how strictly they follow "reply with only JSON").
    Raises ValueError when nothing parses."""
    text = (reply or "").strip()
    fenced = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if starts:
        start = min(starts)
        end = text.rfind("}" if text[start] == "{" else "]")
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        # nearly JSON (an unescaped quote, a trailing comma): repaired, when
        # what comes back is still an object or a list
        repaired = json_repair.loads(text[start:])
        kind = dict if text[start] == "{" else list  # it must stay what it opened as
        values = (repaired.values() if kind is dict else repaired) if isinstance(repaired, kind) else []
        if any(v not in ("", None, [], {}) for v in values):  # not garbage turned into empty keys
            return repaired
    raise ValueError("the reply is not valid JSON")


def call_with_backoff(fn, cancelled=None):
    """Call fn(); on an error (rate limits above all) wait and retry on the
    BACKOFFS schedule. Gives up early when cancelled() turns true."""
    for attempt in range(len(BACKOFFS) + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= len(BACKOFFS) or (cancelled is not None and cancelled()):
                raise
            delay = BACKOFFS[attempt]
            log.warning("model call failed (%s) — retrying in %ds", exc, delay)
            time.sleep(delay)


_clients: dict[tuple, object] = {}  # one SDK client (and its connection pool) per provider and key
_clients_lock = threading.Lock()


def _client_for(provider: str, settings) -> object:
    """The provider's client, made once and shared: the SDK clients are safe
    across threads, and each carries its own pool of connections."""
    key = settings.anthropic_api_key if provider == "anthropic" else settings.openai_api_key
    with _clients_lock:
        if (provider, key) not in _clients:
            if provider == "anthropic":
                from anthropic import Anthropic
                _clients[(provider, key)] = Anthropic(api_key=key)
            else:
                from openai import OpenAI
                _clients[(provider, key)] = OpenAI(api_key=key)
        return _clients[(provider, key)]


class LLM:
    def __init__(self, provider: str, model_name: str, client: object) -> None:
        self.provider = provider
        self.model_name = model_name
        self._client = client

    @classmethod
    def initialize(cls, model_name: str | None = None) -> "LLM":
        """Create a ready-to-use client for `model_name` (default: MODEL_NAME in .env)."""
        settings = get_settings()
        if settings.model_provider == "standin":  # the scale test's stand-in: no model, no cost (services/llm/standin)
            from app.services.llm.standin import StandIn
            return StandIn()  # type: ignore[return-value]
        name = model_name or settings.model_name
        provider = "anthropic" if name.startswith("claude") else (
            "openai" if name.startswith(("gpt", "o")) else settings.model_provider
        )

        return cls(provider, name, _client_for(provider, settings))

    def chat_model(self):
        """A LangChain chat model for deep agents — the only place LangChain
        provider classes are imported. Its calls are recorded like ask()'s."""
        settings = get_settings()
        recorder = _AgentUsage(self.provider, self.model_name, call_context.get())
        if self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=self.model_name, api_key=settings.anthropic_api_key,
                max_tokens=16000, max_retries=5, callbacks=[recorder],
                thinking={"type": "disabled"},  # agents only steer; the steps they call do the judging
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=self.model_name, api_key=settings.openai_api_key, max_retries=5,
                          callbacks=[recorder])

    def ask(self, prompt: str, system: str | None = None, *, blocks: list[str] | None = None) -> str:
        """Send one prompt, return the model's text response. `blocks` is fixed
        text sent ahead of `system` and the prompt, each block marked for reuse
        by the next call that starts the same way. The model thinks before it
        answers (billed as output, unseen) when a skill in the call's context
        asks for it (its `reasoning` setting). A reply cut off at the length
        limit raises ValueError."""
        start = time.monotonic()
        tokens: dict | None = None
        think = _reasoning(call_context.get().get("skills"))
        try:
            if self.provider == "anthropic":
                with self._client.messages.stream(
                    model=self.model_name,
                    max_tokens=MAX_TOKENS,
                    system=_anthropic_system(blocks, system),
                    messages=[{"role": "user", "content": prompt}],
                    thinking={"type": "adaptive"} if think else {"type": "disabled"},
                ) as stream:
                    response = stream.get_final_message()
                tokens = usage.anthropic_usage(response.usage)
                if response.stop_reason == "max_tokens":
                    raise ValueError(f"the reply was cut off at the {MAX_TOKENS:,}-token limit")
                text = "".join(b.text for b in response.content if b.type == "text")
            else:
                instructions = "\n\n".join([*(blocks or []), *([system] if system else [])]) or None
                response = self._client.responses.create(
                    model=self.model_name,
                    instructions=instructions,
                    input=prompt,
                )
                tokens = usage.openai_usage(response.usage)
                text = response.output_text
        except Exception as exc:
            usage.record(self.provider, self.model_name, tokens, _ms(start), ok=False, error=str(exc),
                         reasoning=think)
            raise
        usage.record(self.provider, self.model_name, tokens, _ms(start), ok=True, reasoning=think)
        return text

    def web_search(self, query: str, n: int) -> list[dict]:
        """Up to n pages the provider's own web search finds: [{url, title}].
        Only Anthropic has one built in; another provider raises with why."""
        if self.provider != "anthropic":
            raise NotImplementedError(f"the {self.provider} model has no built-in web search")
        start = time.monotonic()
        try:
            reply = self._client.messages.create(
                model=self.model_name, max_tokens=1024, thinking={"type": "disabled"},
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
                messages=[{"role": "user", "content": f"Search the web for: {query}\nThen reply with only: done"}])
        except Exception as exc:
            usage.record(self.provider, self.model_name, None, _ms(start), ok=False, error=str(exc))
            raise
        usage.record(self.provider, self.model_name, usage.anthropic_usage(reply.usage), _ms(start), ok=True)
        found = [{"url": r.url, "title": getattr(r, "title", None)}
                 for b in reply.content if b.type == "web_search_tool_result" and isinstance(b.content, list)
                 for r in b.content if getattr(r, "url", None)]
        return found[:n]


def _reasoning(skills: list[str] | None) -> bool:
    """Whether any of these skills asks the model to reason first."""
    if not skills:
        return False
    try:
        from app.services.db.mongo import get_collection
        return get_collection("prompts").count_documents({"_id": {"$in": skills}, "reasoning": "on"}) > 0
    except Exception:  # the database is the source; without it, answer directly
        return False


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _anthropic_system(blocks: list[str] | None, system: str | None):
    """The system part: each fixed block marked for reuse (at most 4 marks, the
    provider's limit), then the per-call system text."""
    if not blocks:
        return system or ""
    parts = [{"type": "text", "text": b} for b in blocks if b]
    for part in parts[-4:]:
        part["cache_control"] = {"type": "ephemeral"}
    if system:
        parts.append({"type": "text", "text": system})
    return parts


try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:  # pragma: no cover — deep agents need langchain anyway
    BaseCallbackHandler = object


class _AgentUsage(BaseCallbackHandler):
    """Records a deep agent's model calls, labelled with the context the agent
    was built in (or the one current when the call ends, when there is one)."""

    def __init__(self, provider: str, model: str, context: dict):
        self.provider, self.model, self.context, self.started = provider, model, context, {}

    def _ctx(self) -> dict:
        return call_context.get() or self.context

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.started[run_id] = time.monotonic()

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self.started[run_id] = time.monotonic()

    def on_llm_end(self, response, *, run_id, **kwargs):
        start = self.started.pop(run_id, time.monotonic())
        for generations in response.generations:
            for g in generations:
                meta = getattr(getattr(g, "message", None), "usage_metadata", None)
                usage.record(self.provider, self.model, usage.langchain_usage(meta), _ms(start), ok=True,
                             context=self._ctx())

    def on_llm_error(self, error, *, run_id, **kwargs):
        start = self.started.pop(run_id, time.monotonic())
        usage.record(self.provider, self.model, None, _ms(start), ok=False, error=str(error), context=self._ctx())
