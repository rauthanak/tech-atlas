"""Model calls are tried again only when that can help: a throttled or
overloaded provider, a network error, a reply cut off. A wrong key, a refused
request or a bug fails at once, with its reason."""

import anthropic
import httpx
import httpx2
import openai
import pytest
from pymongo.errors import AutoReconnect

from app.services.llm import llm
from agent.scout.tools.adapters import base

REQ = httpx2.Request("POST", "https://api.example")


def _anthropic(cls, status, body=None):
    return cls("from the provider", response=httpx2.Response(status, request=REQ), body=body)


def _openai(cls, status):
    request = httpx.Request("POST", "https://api.example")
    return cls("from the provider", response=httpx.Response(status, request=request), body=None)


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(llm.time, "sleep", waited.append)
    return waited


def _failing(exc, times=1):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) <= times:
            raise exc
        return "ok"
    return fn, calls


@pytest.mark.parametrize("exc", [
    _anthropic(anthropic.BadRequestError, 400),
    _anthropic(anthropic.AuthenticationError, 401),
    _anthropic(anthropic.NotFoundError, 404),
    _openai(openai.BadRequestError, 400),
    KeyError("prompt"),
    ValueError("the reply is not valid JSON"),
])
def test_an_error_retrying_wont_fix_fails_at_once(sleeps, exc):
    fn, calls = _failing(exc)
    with pytest.raises(type(exc)):
        llm.call_with_backoff(fn)
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("exc", [
    _anthropic(anthropic.RateLimitError, 429),
    _anthropic(anthropic.InternalServerError, 500),
    _anthropic(anthropic.APIStatusError, 529),
    _anthropic(anthropic.APIStatusError, 200, {"error": {"type": "overloaded_error"}}),  # sent mid-reply
    anthropic.APIConnectionError(request=REQ),
    anthropic.APITimeoutError(request=REQ),
    _openai(openai.RateLimitError, 429),
    openai.APIConnectionError(request=httpx.Request("POST", "https://api.example")),
    httpx2.ReadTimeout("slow"),
    httpx.ConnectError("refused"),
    AutoReconnect("primary stepped down"),
    llm.CutOff("the reply was cut off at the 64,000-token limit"),
])
def test_temporary_errors_are_tried_again(sleeps, exc):
    fn, calls = _failing(exc)
    assert llm.call_with_backoff(fn) == "ok"
    assert len(calls) == 2 and sleeps == [llm.BACKOFFS[0]]


def test_a_temporary_error_that_persists_is_raised_after_the_schedule(sleeps):
    fn, calls = _failing(_anthropic(anthropic.RateLimitError, 429), times=99)
    with pytest.raises(anthropic.RateLimitError):
        llm.call_with_backoff(fn)
    assert sleeps == list(llm.BACKOFFS) and len(calls) == len(llm.BACKOFFS) + 1


def test_a_stop_ends_the_retries(sleeps):
    fn, calls = _failing(_anthropic(anthropic.RateLimitError, 429), times=99)
    with pytest.raises(anthropic.RateLimitError):
        llm.call_with_backoff(fn, cancelled=lambda: True)
    assert len(calls) == 1 and sleeps == []


def test_adapter_throttling_is_still_tried_again(sleeps):
    answers = iter([429, 200])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(next(answers))))
    assert base.fetch(client, "GET", "https://data.example/x").status_code == 200
    assert sleeps == [llm.BACKOFFS[0]]

    missing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(httpx.HTTPStatusError):
        base.fetch(missing, "GET", "https://data.example/y")
    assert sleeps == [llm.BACKOFFS[0]]
