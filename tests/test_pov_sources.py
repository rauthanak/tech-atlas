"""A Point of View's numbered sources: built by code from the pages its
answers rest on, and every [n] it writes checked against them."""

import json

from agent.analyzer import pov
from factories import assessment, page, run, tech
from stacked_fakes import load_seeded


class Writer:
    def __init__(self, cite):
        self.cite, self.calls = cite, 0

    def ask(self, prompt, system=None, **kw):
        self.calls += 1
        return json.dumps({"headline": "h", "summary": f"It is shipping {self.cite}.", "maturity": "TRL 6 [1]."})


def _world(db, monkeypatch, writer):
    load_seeded(db, "prompts", "measures", "scoring_config", "availability", "domains", "subdomains", "trl_levels",
                "path_steps", "mechanisms", "fabrics")
    tech(db)
    a1 = page(db, "https://lightreading.com/a", 1, summary_text="s", source_name="Light Reading", title="Edge AI ships")
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1], scores=[7, None, 5])
    db["assessments"].update_one({}, {"$set": {"measures.m1.evidence_urls": ["https://lightreading.com/a"]}})
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"classification": {
        "trl": {"level": 6, "reason": "a field trial", "pages": [a1], "at": "2026-09-02"}}}})
    monkeypatch.setattr(pov.LLM, "initialize", classmethod(lambda cls, *a, **k: writer))


def test_sources_are_numbered_from_the_pages_and_given_to_the_writer(db, monkeypatch):
    w = Writer("[1]")
    _world(db, monkeypatch, w)
    _, values, sources = pov.pov_inputs("r1", "edge-ai", with_sources=True)
    assert [s["n"] for s in sources] == [1] and sources[0]["source"] == "Light Reading"
    assert "TRL 6 (A prototype shown in a real setting), judged from its pages: a field trial [1]" in values["assessment_data"]
    assert "SOURCES (cite only these numbers):\n[1] Light Reading" in values["assessment_data"]
    doc = pov.compose_pov("r1", "edge-ai")
    assert doc["sources"][0]["url"] == "https://lightreading.com/a" and "citation_problems" not in doc and w.calls == 1


def test_a_citation_that_isnt_in_the_sources_is_asked_again_then_noted(db, monkeypatch):
    w = Writer("[7]")
    _world(db, monkeypatch, w)
    doc = pov.compose_pov("r1", "edge-ai")
    assert w.calls == 2 and doc["citation_problems"] == "cites [7], which aren't in its sources"


def test_sources_are_labelled_by_the_sources_name(db):
    """A stored id ("cx_today") reads as the source's name, old Points of View included."""
    from fastapi.testclient import TestClient
    from app.main import app
    db["sources"].insert_one({"_id": "cx_today", "name": "CX Today"})
    db["scoring_runs"].insert_one({"_id": "r1"})
    db["povs"].insert_one({"_id": "r1:quic", "scoring_run_id": "r1", "tech_id": "quic",
                           "sources": [{"n": 1, "source": "cx_today"}, {"n": 2, "source": "new.example (web search)"}]})
    got = TestClient(app).get("/api/scoring/runs/r1/pov/quic").json()["sources"]
    assert [x["source"] for x in got] == ["CX Today", "new.example (web search)"]
