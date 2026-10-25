"""Which page a visit is of (services/pages): known by its tidied link, or by
the same site, title and text; each page's newest visit is marked."""

from app.services import evidence
from app.services.pages import link_key
from app.services.runs.store import save_document

SOURCE = {"source_id": "s", "url": "https://example.com"}


def read(url, text):
    return {"summary": "s", "technologies": ["edge ai"], "scout_take": "t", "signals": [], "ignored_by": None,
            "signals_hash": "h", "parts": None, "partial": False}


def store(url, text="the page", title="A page"):
    save_document("c", "H1", SOURCE, url, text, read, meta={"title": title})


def test_a_link_is_tidied():
    assert link_key("https://www.Example.com/a/?utm_source=x&b=2&a=1#top") == "example.com/a?a=1&b=2"
    assert link_key("http://example.com/a?share=linkedin") == link_key("https://example.com/a/") == "example.com/a"
    assert link_key("https://example.com/a?id=1") != link_key("https://example.com/a?id=2")
    assert link_key("upload:job1/file.pdf") == "upload:job1/file.pdf"  # not a web address: as it is


def test_the_same_site_title_and_text_is_one_page(db):
    store("https://arxiv.org/abs/2610.03713")
    store("https://arxiv.org/abs/2610.03713v1")
    assert len(db["documents"].distinct("page_key")) == 1


def test_a_shared_title_with_other_text_or_on_another_site_is_another_page(db):
    store("https://rbi.org.in/press?id=1", text="one release", title="Press Releases")
    store("https://rbi.org.in/press?id=2", text="another release", title="Press Releases")
    store("https://other.org/press", text="one release", title="Press Releases")
    assert len(db["documents"].distinct("page_key")) == 3


def test_the_newest_visit_is_marked_and_counts_the_visits(db):
    store("https://example.com/a")
    store("https://example.com/a")                      # unchanged: a stub
    store("https://example.com/a/", text="changed")     # a new version, same page
    visits = list(db["documents"].find({}, {"latest": 1, "visits": 1, "is_stub": 1}).sort("scraped_at", 1))
    assert [v.get("latest") for v in visits] == [False, False, True]
    assert [v["visits"] for v in visits] == [1, 2, 3]
    assert visits[1]["is_stub"] and not visits[2]["is_stub"]


def test_an_unchanged_revisit_arrives_linked(db):
    store("https://example.com/a")
    db["documents"].update_many({}, {"$set": {"technologies_resolved": ["edge ai"]}})  # as Organize links it
    store("https://example.com/a")
    stub = db["documents"].find_one({"is_stub": True})
    assert stub["technologies_resolved"] == ["edge ai"]
    assert [d["_id"] for d in evidence.newest_visits(["edge ai"])["edge ai"]] == [stub["_id"]]


def test_retention_keeps_the_newest_text_and_drops_superseded_older_ones(db, monkeypatch):
    from app.services import page_texts
    from app.services.runs import store as runs
    monkeypatch.setattr(runs.get_settings(), "keep_full_text_runs", 1)
    db["runs"].insert_many([{"_id": "old", "run_start_date_time": "2026-09-01"},
                            {"_id": "new", "run_start_date_time": "2026-09-02"}])
    save_document("old", "H1", SOURCE, "https://example.com/a", "first", read, meta={"title": "A"})
    save_document("new", "H1", SOURCE, "https://example.com/a", "second", read, meta={"title": "A"})
    runs.prune_old_text()
    old, new = (db["documents"].find_one({"run_id": r}) for r in ("old", "new"))
    assert page_texts.text(old["_id"]) is None and old["text_pruned"] and not old["has_text"]
    assert page_texts.text(new["_id"]) == "second" and new["has_text"]
