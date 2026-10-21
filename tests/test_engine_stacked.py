"""The stacked engine: a technology call, then one call per fabric; the
technology's measures copied into each fabric; Tata's measures waiting; a
task left out asked again alone."""

from concurrent.futures import ThreadPoolExecutor

from agent.analyzer import engine, stacked
from agent.analyzer.placement import compute_placement
from factories import page, tech
from stacked_fakes import StackedModel, load_seeded


def _run(db, fabrics=("cloud", "network", "iot")):
    load_seeded(db, "prompts", "measures", "recipes", "scoring_config", "fabrics")
    db["fabrics"].update_many({}, {"$set": {"enabled": False}})
    db["fabrics"].update_many({"_id": {"$in": list(fabrics)}}, {"$set": {"enabled": True}})
    tech(db)
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"doc_count": 2}})
    page(db, "a", 1, summary_text="Edge AI chips ship")
    page(db, "b", 2, summary_text="A pilot in Singapore",
         signals=[{"signal_id": "deploy", "technologies_resolved": ["edge ai"]}])
    return engine.create_scoring_run({"technologies": ["edge-ai"], "engine": "stacked"})


def test_calls_are_one_per_technology_plus_one_per_fabric(db):
    run_id = _run(db)
    model = StackedModel(gates=("cloud", "network"))
    with ThreadPoolExecutor(2) as ex:
        engine.assess_technology(run_id, "edge-ai", model, ex)
    assert len(model.calls) == 1 + 2
    rows = {a["fabric_id"]: a for a in db["assessments"].find({"scoring_run_id": run_id})}
    assert set(rows) == {"cloud", "network"}
    measures = list(db["measures"].find())
    for a in rows.values():
        for m in measures:
            r = a["measures"][m["_id"]]
            assert r["scope"] == m["scope"]
            if m["scope"] == "tata":
                assert r["score"] is None and r["waiting_for_tata"] and "waiting for Tata" in r["missing"]
            else:
                assert r["score"] == 6
        assert a["engine"] == "stacked" and a["watch_metrics"] == [{"metric": "m", "current_value": "v"}]
        assert a["placement"] == compute_placement(a["measures"], list(db["scoring_config"].find()))
    # the technology's evidence leads every call, the same text each time (reused by the provider)
    assert len({c["blocks"][0] for c in model.calls}) == 1
    assert model.calls[0]["blocks"][0].index("A pilot in Singapore") < model.calls[0]["blocks"][0].index("Edge AI chips")


def test_a_task_left_out_is_asked_again_alone_and_resume_doesnt_re_ask(db):
    run_id = _run(db)
    fit = "measure:fabric-fit"
    model = StackedModel(gates=("cloud",), drop={fit})
    with ThreadPoolExecutor(2) as ex:
        engine.assess_technology(run_id, "edge-ai", model, ex)
    assert len(model.calls) == 1 + 1 + 1  # the fit measure, alone
    a = db["assessments"].find_one({"scoring_run_id": run_id})
    assert a["measures"]["fabric-fit"]["score"] == 6 and a["calls"]["retries"] == 1
    again = StackedModel()
    with ThreadPoolExecutor(2) as ex:
        engine.assess_technology(run_id, "edge-ai", again, ex)
    assert again.calls == []  # nothing owed, and the technology call isn't re-asked


def test_the_estimate_follows_the_engine(db):
    from agent.analyzer.estimate import estimate
    load_seeded(db, "measures", "fabrics", "scoring_config")
    tech(db)
    enabled = db["fabrics"].count_documents({"enabled": True})
    db["scoring_config"].update_one({"_id": "engine"}, {"$set": {"mode": "per_measure"}})
    assert estimate(["edge-ai"])["calls"] == 2 + 12 * enabled
    db["scoring_config"].update_one({"_id": "engine"}, {"$set": {"mode": "stacked"}})
    assert estimate(["edge-ai"])["calls"] == 1 + enabled
