"""Find evidence as a vertical search (1 Nov): the places come from the
radar's own sources, each saying why it can't be searched; a data source is
searched once by the technology's names, most-cited first for papers; the
results are filed under the source they came from; and the cost is shown
before anything runs."""

import httpx
from fastapi.testclient import TestClient

from agent.find_evidence import job as finder
from agent.scout.tools.adapters import base, openalex
from app.main import app
from app.services import places, websearch
from test_find_evidence import TRIAL, _world

client = TestClient(app)

SOURCES = [
    {"_id": "openalex_works", "source_id": "openalex_works", "name": "OpenAlex: papers", "url": "https://api.openalex.org",
     "access": "query", "adapter": "openalex_works", "enabled": True, "cost": "free", "horizon": "H3", "searches": ["x"]},
    {"_id": "espacenet", "source_id": "espacenet", "name": "Espacenet", "url": "https://worldwide.espacenet.com",
     "access": "query", "adapter": "epo_ops", "enabled": True, "cost": "free", "horizon": "H3", "searches": ["x"]},
    {"_id": "sec", "source_id": "sec", "name": "SEC EDGAR", "url": "https://www.sec.gov",
     "access": "query", "adapter": "sec_edgar", "enabled": True, "cost": "free", "horizon": "H2", "searches": ["1"]},
    {"_id": "grants", "source_id": "grants", "name": "OpenAlex: grants", "url": "https://api.openalex.org/awards",
     "access": "query", "adapter": "openalex_awards", "enabled": False, "cost": "free", "horizon": "H3",
     "note": "kept off for now"},
    {"_id": "lightwave", "source_id": "lightwave", "name": "Lightwave", "url": "https://www.lightwaveonline.com",
     "access": "crawl", "enabled": True, "cost": "free", "horizon": "H2"},
]


def test_each_place_says_why_it_cant_be_searched(db, monkeypatch):
    db["sources"].insert_many(SOURCES)
    monkeypatch.setattr(websearch, "configured", lambda: False)
    by_id = {p["id"]: p for p in places.places()}
    assert by_id["openalex_works"]["available"] and by_id["openalex_works"]["kind"] == "search"
    assert "the patent office's free key" in by_id["espacenet"]["why"]      # no keys
    assert "sec" not in by_id                                                # searched by company: not a place
    assert by_id["grants"]["why"] == "switched off in Sources: kept off for now"
    assert by_id["openalex_works"]["label"] == "Research papers" and "most-cited" in by_id["openalex_works"]["gives"]
    assert by_id["radar_websites"]["why"].startswith("not set up yet") and "all 1 websites" in by_id["radar_websites"]["gives"]
    assert [p["id"] for p in places.places()][:3] == ["openalex_works", "grants", "espacenet"]  # research, then patents
    assert places.hosts() == {"lightwaveonline.com": "lightwave"}


def test_papers_are_asked_for_most_cited_in_one_request(monkeypatch):
    asked = {}

    def handler(request: httpx.Request) -> httpx.Response:
        asked.update(dict(request.url.params))
        return httpx.Response(200, json={"results": [{"id": "W1", "display_name": "A QKD field trial",
                                                      "publication_date": "2025-01-01"}]})
    real = httpx.Client
    monkeypatch.setattr(openalex.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    items = openalex.WORKS.top("quantum key distribution", 7)
    assert asked["sort"] == "cited_by_count:desc" and asked["per_page"] == "7"
    assert 'title_and_abstract.search:"quantum key distribution"' in asked["filter"]
    assert [i.title for i in items] == ["A QKD field trial"]


def test_names_are_the_label_name_and_aliases_once_each():
    assert places.names({"label": "QKD", "name": "qkd", "aliases": ["quantum key distribution", "qkd"]}) == \
        ["QKD", "quantum key distribution"]


def test_a_search_of_two_places_files_each_page_under_where_it_came_from(db, monkeypatch):
    _world(db, monkeypatch)
    db["sources"].insert_many(SOURCES)
    monkeypatch.setattr(websearch, "configured", lambda: True)
    paper = base.Item(url="https://doi.org/10.1/edge", title="Edge AI at scale", text=TRIAL, published_date="2025-02-01",
                      kind="paper")
    monkeypatch.setattr(openalex.WORKS, "top", lambda query, n: [paper])
    db["find_evidence_jobs"].insert_one({"_id": "v1", "gap": {"kind": "technology", "tech_id": "edge-ai",
                                                              "places": ["openalex_works", "web", "sec"], "per_place": 3},
                                         "query": "edge ai", "at": "2026-11-01T00:00:00+00:00", "tz": "UTC",
                                         "results": [], "searched": True})
    finder.run("v1", fetch=lambda url: (TRIAL, {}, None),
               search=lambda q, n: [{"url": "https://news.example/edge", "title": "News"}])
    j = db["find_evidence_jobs"].find_one({"_id": "v1"})
    assert {r["url"]: (r["place"], r["status"]) for r in j["results"]} == {
        "https://doi.org/10.1/edge": ("openalex_works", "filed"), "https://news.example/edge": ("web", "filed")}
    assert db["documents"].find_one({"end_url": "https://doi.org/10.1/edge"})["source_id"] == "openalex_works"
    assert db["documents"].find_one({"end_url": "https://news.example/edge"})["source_id"] == "web_search"
    done = {d["place"]: d for d in j["places_done"]}
    assert done["openalex_works"]["found"] == 1 and done["sec"]["why"] == "not one of the places that can be searched"


def test_the_preview_chooses_every_place_that_can_be_searched_and_shows_the_cost(db, monkeypatch):
    _world(db, monkeypatch)
    db["sources"].insert_many(SOURCES)
    monkeypatch.setattr(websearch, "configured", lambda: True)
    pre = client.get("/api/find-evidence/preview", params={"kind": "technology", "tech_id": "edge-ai"}).json()
    assert [p["id"] for p in pre["places"] if p["chosen"]] == ["openalex_works", "radar_websites", "web"]
    assert pre["cost"] == {"pages": 15, "searches": 2, "calls": 18} and pre["per_place"] == 5  # + 2 searches + 1 redo
    one = client.get("/api/find-evidence/preview", params={"kind": "technology", "tech_id": "edge-ai",
                                                           "places": "openalex_works", "per_place": 20}).json()
    assert one["cost"] == {"pages": 20, "searches": 0, "calls": 21}
    none = client.get("/api/find-evidence/preview", params={"kind": "technology", "tech_id": "edge-ai", "places": "sec"}).json()
    assert none["why_not"] == "Choose at least one place that can be searched."


def test_a_place_can_take_its_own_number_and_the_rest_take_the_shared_one(db, monkeypatch):
    _world(db, monkeypatch)
    db["sources"].insert_many(SOURCES)
    monkeypatch.setattr(websearch, "configured", lambda: True)
    pre = client.get("/api/find-evidence/preview", params={"kind": "technology", "tech_id": "edge-ai",
                                                           "places": "openalex_works,web", "per_place": 5,
                                                           "counts": "openalex_works:20"}).json()
    assert pre["counts"] == {"openalex_works": 20} and pre["cost"] == {"pages": 25, "searches": 1, "calls": 27}
    asked = []
    monkeypatch.setattr(openalex.WORKS, "top", lambda query, n: asked.append(n) or [])
    db["find_evidence_jobs"].insert_one({"_id": "v2", "gap": {"kind": "technology", "tech_id": "edge-ai",
                                                              "places": ["openalex_works"], "per_place": 5,
                                                              "counts": {"openalex_works": 20}},
                                         "query": "edge ai", "at": "2026-11-01T00:00:00+00:00", "tz": "UTC",
                                         "results": [], "searched": True})
    finder.run("v2", fetch=lambda url: (TRIAL, {}, None), search=lambda q, n: [])
    assert asked and set(asked) == {20}
