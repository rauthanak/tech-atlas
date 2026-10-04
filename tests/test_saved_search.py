"""Saved-search windows: results already collected are skipped and don't
count toward the limit; `through` moves only when the window is done;
too broad is flagged; an error leaves `through` unchanged."""

from datetime import date, timedelta

import pytest

from agent.scout.tools.adapters import base
from agent.scout.tools.adapters.base import Adapter, Item
from app.services.db import seeding
from app.services.db.mongo import get_collection

TODAY = date.today()


class FakeAdapter(Adapter):
    name = "fake"

    def __init__(self, items, total=None, fail=False):
        self.items, self.total, self.fail = items, total, fail

    def window(self, query, since, until):
        if self.fail:
            raise RuntimeError("API down")
        return list(self.items), self.total if self.total is not None else len(self.items)


class FakeCtx:
    """Stores like the real path (a document per new URL), without a model."""
    max_pages = 5
    settings = {"lookback_days": 30}

    def cancelled(self):
        return False

    def visited(self, outcome, source):
        outcome.pages += 1

    def save(self, outcome, source, url, text, depth=0, meta=None):
        get_collection("documents").insert_one({"end_url": url, "is_stub": False})
        outcome.docs += 1
        outcome.new_docs += 1
        return {}


@pytest.fixture
def source(db):
    seeding.load_if_new()
    get_collection("sources").update_one({"_id": "openalex_works"}, {"$set": {"searches": ["q"]}})
    return {"source_id": "openalex_works", "adapter": "fake", "searches": ["q"]}


def run(adapter, source):
    return base.collect(FakeCtx(), source, {"fake": adapter})


def progress():
    return get_collection("sources").find_one({"_id": "openalex_works"})["progress"][0]


def test_same_date_results_never_hold_a_search_back(source):
    same_day = (TODAY - timedelta(days=3)).isoformat()
    items = [Item(f"https://x/{i:02d}", "t", "text", same_day, "paper") for i in range(30)]
    adapter = FakeAdapter(items)
    out = run(adapter, source)
    assert out.docs == 5 and progress()["remaining"] == 25
    assert out.incomplete_note == "25 still to collect (q: 25)"
    first_through = progress()["through"]
    for n in range(5):
        out = run(adapter, source)
    assert get_collection("documents").count_documents({}) == 30      # all 30, no duplicates
    assert progress()["remaining"] == 0 and out.incomplete_note is None
    assert progress()["through"] == TODAY.isoformat() != first_through


def test_oldest_first(source):
    items = [Item(f"https://x/{d}", "t", "", (TODAY - timedelta(days=d)).isoformat(), "paper")
             for d in range(1, 11)]
    run(FakeAdapter(items), source)
    stored = {d["end_url"] for d in get_collection("documents").find()}
    assert stored == {f"https://x/{d}" for d in range(6, 11)}           # the 5 oldest


def test_too_broad_and_errors(source):
    out = run(FakeAdapter([Item("https://x/1", "t", "", None, "paper")], total=2500), source)
    assert progress()["too_broad"] is True and "too broad" in out.incomplete_note
    assert progress()["through"] == (TODAY - timedelta(days=30)).isoformat()   # not moved
    before = progress()["through"]
    out = run(FakeAdapter([], fail=True), source)
    assert progress()["through"] == before and "API down" in out.error
