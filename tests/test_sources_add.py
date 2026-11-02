"""R3 (28 Oct review): an admin adds a source in the portal. It is live at
once, refused with its reason when it can't be saved, and listed on Setup ›
Changes as added, where Keep as defaults writes it into the seeding data."""

from fastapi.testclient import TestClient

from app.main import app
from app.services.db import seeding
from app.services.db.mongo import get_collection

WEBSITE = {"name": "Example Optics News", "url": "https://optics.example", "horizon": "H1",
           "cluster": "analysts_trade_press", "cost": "free", "enabled": True, "access": "crawl",
           "entry_urls": ["https://optics.example/data-center/"]}


def _add(**changes):
    return TestClient(app).post("/api/sources", json={**WEBSITE, **changes})


def test_add_a_website(db, seeds):
    seeding.load_if_new()
    r = _add()
    assert r.status_code == 201
    doc = get_collection("sources").find_one({"_id": "example_optics_news"})
    assert doc["source_id"] == "example_optics_news" and doc["access"] == "crawl" and doc["enabled"] is True
    assert doc["entry_urls"] == WEBSITE["entry_urls"] and "adapter" not in doc and "searches" not in doc
    assert doc["updated_by"]


def test_add_a_data_source(db, seeds):
    seeding.load_if_new()
    r = _add(name="Research trends: test", url="https://openalex.org", access="query", adapter="openalex_trends",
             entry_urls=None, searches=["quantum networking", "quantum networking"])
    assert r.status_code == 201
    doc = get_collection("sources").find_one({"_id": "research_trends_test"})
    assert doc["adapter"] == "openalex_trends" and doc["searches"] == ["quantum networking"]


def test_refusals_say_why(db, seeds):
    seeding.load_if_new()
    assert _add().status_code == 201
    taken = _add()
    assert taken.status_code == 409 and "example_optics_news exists" in taken.json()["detail"]
    cases = [
        (dict(name="X1", access="query", adapter="openalex_works"), "website sources only"),
        (dict(name="X2", entry_urls=None, searches=["a"]), "data sources only"),
        (dict(name="X3", access="query", adapter="nope", entry_urls=None), "connector"),
        (dict(name="X4", adapter="openalex_works"), "A website has no connector"),
        (dict(name="X5", cost="licensed"), "paid sources"),
        (dict(name="!!!"), "letters or digits"),
    ]
    for changes, words in cases:
        r = _add(**changes)
        assert r.status_code == 422 and words in r.json()["detail"], (changes, r.json())


def test_listed_as_added_and_kept_as_default(db, seeds):
    seeding.load_if_new()
    _add()
    assert ("sources", "example_optics_news", "added") in {(r["collection"], r["id"], r["kind"])
                                                         for r in seeding.changes()["items"]}
    seeding.update_seeding_data([{"collection": "sources", "id": "example_optics_news"}])
    kept = seeding.read_list("sources")[-1]
    assert kept["source_id"] == "example_optics_news" and kept["entry_urls"] == WEBSITE["entry_urls"]
    assert seeding.changes()["count"] == 0


def test_editing_keeps_its_rules(db, seeds):
    seeding.load_if_new()
    _add()
    body = {k: v for k, v in WEBSITE.items() if k != "access"}
    r = TestClient(app).put("/api/sources/example_optics_news", json={**body, "entry_urls": []})
    assert r.status_code == 200 and "entry_urls" not in r.json()
    r = TestClient(app).put("/api/sources/example_optics_news", json={**body, "searches": ["a"]})
    assert r.status_code == 422 and "data sources only" in r.json()["detail"]


def test_why_its_off_is_kept_and_goes_when_switched_on(db, seeds):
    seeding.load_if_new()
    _add()
    body = {k: v for k, v in WEBSITE.items() if k != "access"}
    off = TestClient(app).put("/api/sources/example_optics_news",
                              json={**body, "enabled": False, "note": "Its robots.txt asks crawlers not to read it."})
    assert off.status_code == 200 and off.json()["note"] == "Its robots.txt asks crawlers not to read it."
    on = TestClient(app).put("/api/sources/example_optics_news", json={**body, "enabled": True, "note": ""})
    assert on.status_code == 200 and "note" not in on.json()


def test_a_source_s_own_page_budget_is_kept_and_blank_means_the_default(db, seeds):
    seeding.load_if_new()
    _add()
    body = {k: v for k, v in WEBSITE.items() if k != "access"}
    own = TestClient(app).put("/api/sources/example_optics_news", json={**body, "pages": 300})
    assert own.status_code == 200 and own.json()["pages"] == 300
    preview = TestClient(app).get("/api/runs/preview").json()
    assert preview["pages_in_all"] == preview["pages_per_source"] * (preview["websites"] - 1) + 300
    blank = TestClient(app).put("/api/sources/example_optics_news", json={**body, "pages": 0})
    assert blank.status_code == 200 and "pages" not in blank.json()
