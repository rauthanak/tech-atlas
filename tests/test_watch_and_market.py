"""What the 21 Oct sync asked for: metrics to watch checked at the next
assessment, market size as a band from a named page, and how often leaders
open and print each Point of View."""

from fastapi.testclient import TestClient

from agent.analyzer import engine
from app.main import app
from app.services import market
from factories import assessment, page, run, tech

client = TestClient(app)
ARR = {"metric": "Agentforce ARR", "current_value": "$2.3B", "inflection_threshold": "$2B", "crossed": True,
       "previous_value": "$1.5B", "source": "https://a.example/q3"}


def test_a_crossing_counts_only_from_a_page_the_assessment_read():
    kept = engine.watch_result([ARR, {"metric": "x", "crossed": False}, {"no": "metric"}], {"https://a.example/q3"})
    assert [m["crossed"] for m in kept] == [True, False]
    moved = engine.watch_result([ARR], {"https://other.example"})[0]
    assert moved["crossed"] is None and "didn't read" in moved["crossed_note"]


def test_the_next_assessment_gets_the_metrics_to_check(db):
    assert engine.previous_watch("edge-ai", "r2") == engine.NO_PREVIOUS
    assessment(db, "r1", 1)
    db["assessments"].update_one({}, {"$set": {"watch_metrics": [{**ARR, "current_value": "$1.5B"}]}})
    text = engine.previous_watch("edge-ai", "r2")
    assert text.startswith("Set on 2026-09-01") and "Agentforce ARR | then: $1.5B | threshold: $2B" in text
    assert engine.previous_watch("edge-ai", "r1") == engine.NO_PREVIOUS  # never its own run's


def test_a_market_figure_needs_a_page_the_measure_cites():
    ok = engine.measure_result({"score": 7, "evidence_urls": ["https://m.example"],
                                "figure": {"amount_usd_bn": "7.2", "year": 2026, "scope": "worldwide", "url": "https://m.example"}})
    assert ok["figure"] == {"amount_usd_bn": 7.2, "year": 2026, "scope": "worldwide", "url": "https://m.example"}
    for bad in ({"amount_usd_bn": 7, "url": "https://not-cited.example"}, {"amount_usd_bn": "lots", "url": "https://m.example"},
                {"amount_usd_bn": 0, "url": "https://m.example"}, None):
        assert engine.measure_result({"score": 7, "evidence_urls": ["https://m.example"], "figure": bad})["figure"] is None


def test_the_bands():
    assert [market.band(x) for x in (0.4, 1, 4.9, 5, 19, 20, 99, 100, 4400)] == [
        "under $1B", "$1–5B", "$1–5B", "$5–20B", "$5–20B", "$20–100B", "$20–100B", "over $100B", "over $100B"]
    assert market.market_size({}) is None  # assessed before figures were asked
    assert market.market_size({market.MEASURE: {"score": None, "figure": None}}) == {"band": None}
    size = market.market_size({market.MEASURE: {"figure": {"amount_usd_bn": 7.2, "year": 2026, "scope": "w", "url": "u"}}})
    assert size["band"] == "$5–20B"


def test_the_briefing_lists_crossings_from_each_latest_assessment(db):
    tech(db, "edge-ai", "edge ai")
    tech(db, "quic", "quic")
    assessment(db, "r1", 1)
    assessment(db, "r1", 1, tech_id="quic")
    db["assessments"].update_many({}, {"$set": {"watch_metrics": [ARR]}})
    assessment(db, "r2", 2, tech_id="quic")  # newer, and it crossed nothing
    rows = client.get("/api/scoring/crossed").json()["crossed"]
    assert [(r["tech_id"], r["metric"], r["previous_value"]) for r in rows] == [("edge-ai", "Agentforce ARR", "$1.5B")]


def test_leaders_opens_and_prints_are_counted(db, call_as):
    tech(db, "edge-ai", "edge ai")
    call_as("leader")  # only leaders' visits count (sign-in, 25 Oct)
    for kind in ("opened", "opened", "printed"):
        assert client.post("/api/frontier/pov/edge-ai/seen", json={"kind": kind}).status_code == 204
    assert client.post("/api/frontier/pov/edge-ai/seen", json={"kind": "liked"}).status_code == 422
    call_as("admin")
    v = client.get("/api/editions/pov/edge-ai").json()["views"]
    assert v["opened"] == 2 and v["printed"] == 1 and v["last_opened"]
    assert client.get("/api/editions/pov/quic").json()["views"] is None


def test_the_point_of_view_shows_the_band_and_its_page(db, monkeypatch):
    from agent.analyzer import pov
    tech(db, "edge-ai", "edge ai")
    run(db, "r1", 2)
    p = page(db, "https://m.example", 1)
    assessment(db, "r1", 2, pages=[p])
    db["assessments"].update_one({}, {"$set": {"measures": {market.MEASURE: {
        "score": 7, "evidence_urls": ["https://m.example"],
        "figure": {"amount_usd_bn": 7.2, "year": 2026, "scope": "worldwide", "url": "https://m.example"}}}}})
    view = pov.pov_view({"tech_id": "edge-ai", "scoring_run_id": "r1", "sources": []})
    assert view["market_size"]["band"] == "$5–20B" and view["market_size"]["refs"] == [1]
    assert view["sources"][0]["url"] == "https://m.example"


def test_a_fabric_people_worked_on_is_always_assessed_again(db):
    fabrics = [{"_id": f} for f in ("cloud", "interaction", "iot", "network")]
    assert engine.keep_worked_on("agentic-ai", ["cloud"], fabrics) == ["cloud"]
    db["decisions"].insert_many([
        {"_id": "d1", "tech_id": "agentic-ai", "fabric_id": "interaction", "kind": "path_step", "active": True},
        {"_id": "d2", "tech_id": "agentic-ai", "fabric_id": "iot", "kind": "override", "active": False},  # undone
        {"_id": "d3", "tech_id": "agentic-ai", "fabric_id": None, "kind": "move", "active": True},
        {"_id": "d4", "tech_id": "quic", "fabric_id": "network", "kind": "path_step", "active": True}])
    assert engine.keep_worked_on("agentic-ai", ["cloud"], fabrics) == ["cloud", "interaction"]
