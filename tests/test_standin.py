"""The scale test's stand-in model (MODEL_PROVIDER=standin) answers every
step in the shape it asks for, so the radar's own work can be timed with no
model cost: a page is read, a technology classified and assessed, and its
Point of View written, each passing its step's own checks."""

from concurrent.futures import ThreadPoolExecutor

from agent.analyzer import engine
from agent.classifier import classify
from agent.scout.tools.summarize import summarize_page
from app.services.db import seeding
from app.services.llm import LLM
from app.services.llm.standin import StandIn
from app.services.signals import snapshot
from app.settings import get_settings
import test_classify
import test_engine_stacked


def test_initialize_gives_the_stand_in_only_when_asked(monkeypatch):
    monkeypatch.setattr(get_settings(), "model_provider", "standin")
    assert isinstance(LLM.initialize(), StandIn)


def test_a_page_is_read_and_a_technology_classified(db, monkeypatch):
    seeding.load_if_new()
    out = summarize_page(StandIn(), "https://example.com/a", "Edge AI news " * 50, snapshot.build())
    assert out["summary"] and out["technologies"] and out["analysis_error"] is None
    db.drop_collection("technologies")
    for name in seeding.ID_FIELDS:  # a fresh world for the Classify part
        db.drop_collection(name)
    test_classify._world(db)
    monkeypatch.setattr(classify.LLM, "initialize", classmethod(lambda cls, *a, **k: StandIn()))
    run = db["classify_runs"].find_one({"_id": classify.start(["edge-ai"], wait=True)})
    assert run["status"] == "completed" and run["done"] == 1 and not run["failed"]


def test_a_technology_is_assessed(db):
    run_id = test_engine_stacked._run(db)
    with ThreadPoolExecutor(2) as ex:
        engine.assess_technology(run_id, "edge-ai", StandIn(), ex)
    a = db["assessments"].find_one({"scoring_run_id": run_id})
    assert a and a["measures"] and a["placement"]["timeline"]["score"] is not None


def test_a_point_of_view_is_written(db, monkeypatch):
    import test_pov_view
    from agent.analyzer import pov
    test_pov_view._world(db, monkeypatch, StandIn())
    s = pov.compose_pov("r1", "edge-ai")["sections"]
    assert s["headline"] and s["recommendation"]
