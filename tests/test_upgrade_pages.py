"""The once-only upgrade of page records stored before 24 Oct 2026
(services/db/upgrade_pages): it leaves them as storing them now would, and a
run stopped part-way finishes on the next start."""

import pytest

from app.services.db import upgrade_pages
from app.services.runs.store import save_document

SOURCE = {"source_id": "s", "url": "https://example.com"}


def read(url, text):
    return {"summary": "s", "technologies": [], "scout_take": "t", "signals": [], "ignored_by": None,
            "signals_hash": "h", "parts": None, "partial": False}


def _stored_now(db) -> dict:
    """A page stored three times (once unchanged), the same text under another link, and another page."""
    for run, url, text in (("c1", "https://example.com/a", "one"), ("c2", "https://example.com/a", "one"),
                           ("c3", "https://example.com/a/", "two"), ("c4", "https://example.com/a?v=1", "two"),
                           ("c4", "https://example.com/b", "other")):
        save_document(run, "H1", SOURCE, url, text, read, meta={"title": "A" if "/a" in url else "B"})
    return _shape(db)


def _shape(db) -> dict:
    return {"visits": sorted((d["end_url"], d["run_id"], d["page_key"], d["latest"], d["visits"], d["has_text"])
                             for d in db["documents"].find()),
            "texts": sorted((t["text"], t["superseded"]) for t in db["page_texts"].find())}


def _as_before(db) -> None:
    """Back to how records were stored before: text on the visit, no page key or marks."""
    texts = {t["_id"]: t["text"] for t in db["page_texts"].find()}
    for d in db["documents"].find():
        db["documents"].update_one({"_id": d["_id"]}, {
            "$set": {"extracted_text": texts.get(d["_id"])},
            "$unset": {"page_key": "", "latest": "", "visits": "", "has_text": ""}})
    db["page_texts"].delete_many({})


def test_upgraded_records_are_as_storing_them_now_leaves_them(db):
    now = _stored_now(db)
    _as_before(db)
    assert upgrade_pages.run() == 5
    assert _shape(db) == now
    assert not db["documents"].count_documents({"extracted_text": {"$exists": True}})
    assert upgrade_pages.run() == 0                       # once: nothing left the next time


def test_an_upgrade_stopped_part_way_finishes_on_the_next_start(db, monkeypatch):
    now = _stored_now(db)
    _as_before(db)
    real, calls = upgrade_pages._one, []

    def stops_after_two(d):
        if len(calls) == 2:
            raise RuntimeError("the service restarted")
        calls.append(d["_id"])
        real(d)
    monkeypatch.setattr(upgrade_pages, "_one", stops_after_two)
    with pytest.raises(RuntimeError):
        upgrade_pages.run()
    monkeypatch.setattr(upgrade_pages, "_one", real)
    assert upgrade_pages.run() == 3
    assert _shape(db) == now
