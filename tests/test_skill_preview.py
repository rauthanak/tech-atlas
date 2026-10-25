"""Plan 8: what a skill turns into. The key promise: the Skills page's
example is exactly the prompt the run sends. Each test runs the real step
with a stand-in model that only records what it's sent, and compares that
with the preview built for the same case. Nothing here calls a model."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import agent.analyzer.agent as analyzer_agent
import agent.orchestrator.agent as orchestrator_agent
import agent.scout.agent as scout_agent
import agent.supervisor.agent as supervisor_agent
from agent.analyzer import engine
from agent.analyzer import pov as pov_composer
from agent.resolver import resolver
from agent.scout.tools import crawl, summarize
from agent.supervisor.tools.sources import collectable_query, fetch_sources
from app.api.prompts import EXPECTED_VARIABLES
from app.main import app
from app.services import page_texts
from app.services.db import seeding
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM
from app.services.prompts import PromptStore
from app.services.prompts import preview as skill_preview
from app.services.prompts.store import Prompt
from app.services.signals import snapshot
from app.settings import get_settings
from factories import at, with_text

client = TestClient(app)  # no lifespan: nothing is seeded
REPLY = '{"fabrics": ["cloud"], "score": 5, "justification": "j", "evidence_urls": ["u"], ' \
        '"summary": "s", "technologies": [], "scout_take": "t", "signals": [], "ignore": null, ' \
        '"groups": [], "labels": {}}'


class Recorder:
    """A stand-in model: records every prompt, answers one reply that every step can read."""
    def __init__(self):
        self.prompts: list[str] = []

    def ask(self, prompt, system=None, **kw):
        self.prompts.append(prompt)
        return REPLY

    def chat_model(self):
        return None


class Stop(Exception):
    pass


def shown(name: str, **choices) -> str:
    """The preview's example as one string — what the page shows, uncut."""
    out = skill_preview.preview(name, choices)
    assert all(p.get("cut", 0) == 0 for p in out["example"]["parts"])
    text = "".join(p["text"] for p in out["example"]["parts"])
    assert len(text) == out["example"]["characters"]
    return text


def blank(name: str, field: str, **choices) -> str:
    out = skill_preview.preview(name, choices)
    return next(p["text"] for p in out["example"]["parts"] if p.get("blank") == field)


def capture_agent(monkeypatch, module) -> dict:
    """Swap the agent builder in `module` for one that records the instructions and stops."""
    seen: dict = {}

    def fake(**kwargs):
        seen["system_prompt"] = kwargs["system_prompt"]
        raise Stop()
    monkeypatch.setattr(module, "create_deep_agent", fake)
    return seen


@pytest.fixture
def world(db):
    """Seeds, plus one collection (two pages from a website), one technology and one assessment."""
    seeding.load_if_new()
    website = get_collection("sources").find_one({**collectable_query(), "access": "crawl"}, sort=[("name", 1)])
    for i, url in enumerate(["https://example.com/a", "https://example.com/b"], 1):
        with_text(db, {
            "_id": f"doc{i}", "run_id": "c1", "category": website["horizon"], "source_id": website["source_id"],
            "end_url": url, "title": f"Page {i}", "scraped_at": at(i), "is_stub": False, "ref_doc_id": None,
            "extracted_text": f"Edge AI news {i}.", "summary_text": f"summary {i}", "scout_take": f"take {i}",
            "technologies": ["edge ai", "tinyml"], "technologies_resolved": ["edge ai"],
            "ignored_by": None, "parts": None})
    db["runs"].insert_one({"_id": "c1", "status": "completed", "run_start_date_time": at(3), "params": {},
                           "sources": [{"category": website["horizon"], "source_id": website["source_id"]}]})
    db["technologies"].insert_one({"_id": "edge-ai", "name": "edge ai", "label": "Edge AI", "enabled": True,
                                   "aliases": ["edge ai"], "doc_count": 2})
    recorder = Recorder()
    run_id = engine.create_scoring_run({"technologies": ["edge-ai"], "engine": "per_measure"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        engine.assess_technology(run_id, "edge-ai", recorder, pool)
    return {"website": website, "run_id": run_id, "scoring": recorder.prompts}


# ── 1 · the example is exactly what the run sends ───────────────────

def test_assessment_skills_match_the_run(world):
    prompts = world["scoring"]
    m1 = get_collection("measures").find_one({"code": "M1"})
    assert shown("fabric_relevance", technology="edge-ai") == prompts[0]   # the gate goes first
    assert shown("measure_scoring", technology="edge-ai", fabric="cloud", measure=m1["_id"]) in prompts
    assert shown("watch_metrics", technology="edge-ai") == prompts[-1]     # watch metrics go last


def test_point_of_view_matches_the_run(world, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(pov_composer.LLM, "initialize", lambda *a, **k: recorder)
    monkeypatch.setattr(Recorder, "ask", lambda self, prompt, system=None:
                        self.prompts.append(prompt) or '{"headline": "h"}')
    pov_composer.compose_pov(world["run_id"], "edge-ai")
    assert shown("pov", technology="edge-ai") == recorder.prompts[0]


def test_page_summary_matches_the_run(world, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    recorder = Recorder()
    # what the model gets: the reused opening (a block), then the page
    monkeypatch.setattr(Recorder, "ask", lambda self, prompt, system=None, blocks=None:
                        self.prompts.append("".join([*(blocks or []), prompt])) or REPLY)
    doc = get_collection("documents").find_one({"_id": "doc2"})
    summarize.summarize_page(recorder, doc["end_url"], page_texts.text("doc2"), snapshot.build())
    assert shown("article_summary", source=world["website"]["source_id"], page="doc2") == recorder.prompts[0]


def test_link_selection_matches_the_run(world):
    recorder = Recorder()
    source = world["website"]["source_id"]
    links = blank("link_selection", "links", source=source).split("\n")
    budget = int(blank("link_selection", "budget", source=source))
    names = blank("link_selection", "never_miss_names", source=source)
    crawl.select_links(recorder, PromptStore.get("link_selection"), links, budget, names)
    assert shown("link_selection", source=source) == recorder.prompts[0]


def test_organizing_skills_match_the_run(world):
    recorder = Recorder()
    names = json.loads(blank("technology_resolve", "tech_list"))
    register = json.loads(blank("technology_resolve", "known_list"))
    resolver._llm_groups(recorder, PromptStore.get("technology_resolve"), names, register)
    assert shown("technology_resolve") == recorder.prompts[0]

    get_collection("technologies").update_one({"_id": "edge-ai"}, {"$set": {"label": None}})
    recorder = Recorder()
    resolver.label_missing(recorder)
    assert shown("technology_label") == recorder.prompts[0]


def test_agent_instructions_match_the_run(world, monkeypatch):
    seen = capture_agent(monkeypatch, orchestrator_agent)
    with pytest.raises(Stop):
        orchestrator_agent.build_orchestrator(Recorder())
    assert shown("orchestrator") == seen["system_prompt"]

    seen = capture_agent(monkeypatch, supervisor_agent)
    with pytest.raises(Stop):
        supervisor_agent.Supervisor("H2", Recorder()).build_agent()
    assert shown("supervisor", horizon="H2") == seen["system_prompt"]

    seen = capture_agent(monkeypatch, scout_agent)
    batch = fetch_sources("H1")[:get_settings().sources_per_scout]
    with pytest.raises(Stop):
        scout_agent.run_scout("no-such-run", "H1", batch, Recorder())
    assert shown("scout", horizon="H1") == seen["system_prompt"]

    seen = capture_agent(monkeypatch, analyzer_agent)  # the run catches the stop, then sweeps nothing
    monkeypatch.setattr(analyzer_agent.LLM, "initialize", lambda *a, **k: Recorder())
    get_collection("scoring_runs").insert_one({"_id": "empty", "status": "running", "stage": "preparing",
                                               "stage_history": [], "params": {}, "technologies": [],
                                               "progress": {}, "started_at": at(9)})
    analyzer_agent.run_scoring("empty")
    assert shown("analyzer") == seen["system_prompt"]


# ── 2–4 · blanks, parts, no model calls ─────────────────────────────

def test_every_skill_has_a_view_and_says_where_each_blank_comes_from(db):
    seeding.load_if_new()
    skills = {s["name"] for s in seeding.read_list("prompts")}
    assert skills == set(skill_preview.VIEWS) == set(EXPECTED_VARIABLES)
    for name in skills:
        assert set(skill_preview.BLANKS[name]) == EXPECTED_VARIABLES[name], name


def test_marked_parts_join_back_to_the_exact_prompt():
    template = Prompt(name="t", description="", system="System {not a blank}",
                      prompt="JSON {{\"a\": {x}}} then {y!r} and {z:>4}", variables=["x", "y", "z"], version=1)
    values = {"x": "1", "y": "two", "z": "3"}
    parts = skill_preview._parts(template, values)
    assert "".join(p["text"] for p in parts) == template.render(**values)
    assert [p["blank"] for p in parts if "blank" in p] == ["x", "y", "z"]


def test_no_preview_calls_a_model(world, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a preview called the model")
    monkeypatch.setattr(LLM, "initialize", refuse)
    monkeypatch.setattr(LLM, "ask", refuse)
    for module in (orchestrator_agent, supervisor_agent, scout_agent, analyzer_agent):
        monkeypatch.setattr(module, "create_deep_agent", refuse)
    for name in skill_preview.VIEWS:
        params = {"source": world["website"]["source_id"]} if name in ("article_summary", "link_selection") else {}
        out = client.get(f"/api/prompts/{name}/preview", params=params)
        assert out.status_code == 200, (name, out.text)
        assert out.json()["example"]["parts"], name


# ── 5 · edge cases ──────────────────────────────────────────────────

def test_unknown_skill_and_unknown_choice(world):
    assert client.get("/api/prompts/nope/preview").status_code == 404
    out = client.get("/api/prompts/measure_scoring/preview", params={"technology": "zzz"})
    assert out.status_code == 422 and "no technology 'zzz'" in out.json()["detail"]


def test_with_nothing_collected_the_example_says_why(db):
    seeding.load_if_new()
    out = client.get("/api/prompts/article_summary/preview").json()
    assert out["example"]["parts"] == [] and "run a collection" in out["example"]["why_missing"]
    assert out["versions"]["sentence"]  # today's numbers still show


def test_a_switched_off_skill_still_previews(world):
    get_collection("prompts").update_one({"_id": "watch_metrics"}, {"$set": {"enabled": False}})
    out = client.get("/api/prompts/watch_metrics/preview").json()
    assert out["enabled"] is False and out["example"]["parts"]


def test_a_very_long_blank_is_cut_for_display_only(world):
    get_collection("documents").update_many({}, {"$set": {"summary_text": "x" * 120_000}})
    out = skill_preview.preview("watch_metrics", {"technology": "edge-ai"})
    evidence = next(p for p in out["example"]["parts"] if p.get("blank") == "evidence")
    assert len(evidence["text"]) == skill_preview.CUT and evidence["cut"] > 0
    assert out["example"]["characters"] > skill_preview.CUT  # the size counts everything the model gets


# ── 6 · an unsaved edit ─────────────────────────────────────────────

def test_a_draft_is_previewed_and_refused_exactly_as_save_would_refuse_it(world):
    before = get_collection("prompts").find_one({"_id": "watch_metrics"})
    bad = {"description": "d", "system": None, "prompt": "Only {technology}", "enabled": True}
    refused = client.post("/api/prompts/watch_metrics/preview", json=bad)
    saved = client.put("/api/prompts/watch_metrics", json=bad)
    assert refused.status_code == saved.status_code == 422
    assert refused.json()["detail"] == saved.json()["detail"]

    good = client.post("/api/prompts/watch_metrics/preview",
                       json={"system": None, "prompt": "Say {technology}! {evidence} {previous}", "technology": "edge-ai"})
    assert good.status_code == 200 and good.json()["draft"] is True
    assert "".join(p["text"] for p in good.json()["example"]["parts"]).startswith("Say edge ai! ")
    assert get_collection("prompts").find_one({"_id": "watch_metrics"}) == before  # nothing stored
