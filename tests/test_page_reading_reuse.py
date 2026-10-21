"""Reading a page sends the prompt's fixed opening (instructions and the
signal list) as a block the provider reuses, and the page itself after it;
the text the model gets is unchanged."""

import json

from agent.scout.tools import summarize
from agent.scout.tools.summarize import article_summary_values, split_fixed, summarize_page
from app.services.db import seeding
from app.services.llm.llm import LLM
from app.services.prompts import PromptStore
from app.services.signals import snapshot
from app.services.signals.snapshot import prompt_lines
from test_usage import FakeAnthropic

REPLY = json.dumps({"summary": "s", "technologies": ["edge ai"], "scout_take": "t", "signals": [], "ignore": None})


def test_the_fixed_opening_and_the_page_join_into_the_same_prompt(db):
    seeding.load_if_new()
    prompt = PromptStore.get("article_summary")
    values = article_summary_values("https://example.com/a", "Page text {not a blank}", prompt_lines(
        snapshot.build()["signal_list"]))
    fixed, rest = split_fixed(prompt, values, ("url", "text"))
    assert fixed + rest == prompt.render(**values)
    assert fixed.startswith(prompt.system) and "Never miss:" in fixed and "Can ignore:" in fixed
    assert "example.com" not in fixed and rest.startswith("URL: https://example.com/a")
    assert len(fixed) // 4 > 512        # about 4 characters a token: over Haiku 5.5's minimum to reuse


def test_a_page_call_marks_the_opening_for_reuse(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    seeding.load_if_new()
    fake = FakeAnthropic(REPLY)
    out = summarize_page(LLM("anthropic", "claude-haiku-5-5", fake), "https://example.com/b", "alpha " * 50,
                         snapshot.build())
    assert out["analysis_error"] is None
    sent = fake.sent[0]
    assert [("cache_control" in p) for p in sent["system"]] == [True]
    assert "Never miss:" in sent["system"][0]["text"]
    assert sent["messages"][0]["content"].startswith("URL: https://example.com/b")
