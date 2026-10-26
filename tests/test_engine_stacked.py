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
    # Rule 3: the technology call's answers in a record of their own, not on the run
    assert "tech_calls" not in db["scoring_runs"].find_one({"_id": run_id})
    assert db["scoring_tech_calls"].count_documents({"run_id": run_id, "tech_id": "edge-ai"}) == 1
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
    asked = db["measures"].count_documents({"scope": {"$ne": "tata"}})  # Tata's own measures are never asked
    assert estimate(["edge-ai"])["calls"] == 2 + asked * enabled
    db["scoring_config"].update_one({"_id": "engine"}, {"$set": {"mode": "stacked"}})
    assert estimate(["edge-ai"])["calls"] == 1 + enabled


# ── a run's outcome is truthful (code review CR02) ───────────────────

def _two(db, monkeypatch, model):
    from agent.analyzer import agent
    run_id = _run(db)
    tech(db, "quic", "quic")
    db["technologies"].update_one({"_id": "quic"}, {"$set": {"doc_count": 1}})
    page(db, "q", 3, tech="quic", summary_text="QUIC ships in browsers")
    db["scoring_runs"].delete_one({"_id": run_id})
    run_id = engine.create_scoring_run({"technologies": ["edge-ai", "quic"], "engine": "stacked"})
    monkeypatch.setattr(agent.LLM, "initialize", classmethod(lambda cls, *a, **k: model))
    return agent, run_id


def test_a_run_without_failures_completes(db, monkeypatch):
    agent, run_id = _two(db, monkeypatch, StackedModel())
    agent.run_scoring(run_id)
    run = db["scoring_runs"].find_one({"_id": run_id})
    assert (run["status"], run["error"]) == ("completed", None) and not run.get("failed")


def test_a_technology_that_fails_fails_the_run_and_says_why(db, monkeypatch):
    agent, run_id = _two(db, monkeypatch, StackedModel())
    real = engine.assess_technology

    def flaky(run_id, tech_id, *a):
        if tech_id == "quic":
            raise RuntimeError("the model service refused the request")
        return real(run_id, tech_id, *a)
    monkeypatch.setattr(engine, "assess_technology", flaky)
    agent.run_scoring(run_id)
    run = db["scoring_runs"].find_one({"_id": run_id})
    assert run["status"] == "failed"
    assert run["error"] == "1 of 2 technologies failed: quic: the model service refused the request"
    assert run["failed"] == [{"tech_id": "quic", "name": "quic", "error": "the model service refused the request"}]
    assert db["assessments"].count_documents({"scoring_run_id": run_id, "tech_id": "edge-ai"}) == 2  # kept


def test_resume_does_only_the_failed_work(db, monkeypatch):
    model = StackedModel()
    agent, run_id = _two(db, monkeypatch, model)
    real = engine.assess_technology
    monkeypatch.setattr(engine, "assess_technology",
                        lambda r, t, *a: (_ for _ in ()).throw(RuntimeError("down")) if t == "quic" else real(r, t, *a))
    agent.run_scoring(run_id)
    first = {a["_id"]: a["created_at"] for a in db["assessments"].find({"tech_id": "edge-ai"})}
    monkeypatch.setattr(engine, "assess_technology", real)
    monkeypatch.setattr(agent.jobs, "start", lambda *a: None)
    model.calls.clear()
    assert agent.resume_scoring_run(run_id)
    agent.run_scoring(run_id)
    run = db["scoring_runs"].find_one({"_id": run_id})
    assert (run["status"], run["failed"]) == ("completed", [])
    assert len(model.calls) == 1 + 2  # quic's technology call and its two fabrics; edge-ai isn't asked again
    assert {a["_id"]: a["created_at"] for a in db["assessments"].find({"tech_id": "edge-ai"})} == first


def test_a_fabric_that_fails_keeps_the_others(db, monkeypatch):
    run_id = _run(db)
    real = stacked.fabric_call

    def flaky(llm, run, entry, dossier, measures, fabric, pages):
        if fabric["_id"] == "network":
            raise RuntimeError("overloaded")
        return real(llm, run, entry, dossier, measures, fabric, pages)
    monkeypatch.setattr(stacked, "fabric_call", flaky)
    model = StackedModel(gates=("cloud", "network"))
    with ThreadPoolExecutor(2) as ex:
        try:
            engine.assess_technology(run_id, "edge-ai", model, ex)
            raise AssertionError("expected the failed fabric to be reported")
        except RuntimeError as exc:
            assert "Network" in str(exc) and "overloaded" in str(exc)
    assert [a["fabric_id"] for a in db["assessments"].find({"scoring_run_id": run_id})] == ["cloud"]
    monkeypatch.setattr(stacked, "fabric_call", real)
    model.calls.clear()
    with ThreadPoolExecutor(2) as ex:
        engine.assess_technology(run_id, "edge-ai", model, ex)
    assert len(model.calls) == 1  # only the network fabric, asked again


# ── Tata's own measures are never sent to the model (code review CR06) ──

def test_the_per_measure_engine_never_asks_for_tata_measures(db, monkeypatch):
    run_id = _run(db)
    db["scoring_runs"].delete_one({"_id": run_id})
    run_id = engine.create_scoring_run({"technologies": ["edge-ai"], "engine": "per_measure"})
    db["scoring_runs"].update_one({"_id": run_id}, {"$set": {"params.engine": "per_measure"}})
    db["scoring_config"].update_one({"_id": "engine"}, {"$set": {"mode": "per_measure"}})
    asked, real = [], engine._score_measure
    monkeypatch.setattr(engine, "_score_measure", lambda llm, r, m, *a: asked.append(m["_id"]) or real(llm, r, m, *a))
    with ThreadPoolExecutor(4) as ex:
        engine._assess_per_measure(run_id, "edge-ai", StackedModel(gates=("cloud",)), ex)
    tata = {m["_id"] for m in db["measures"].find({"scope": "tata"})}
    assert tata and not tata & set(asked)
    a = db["assessments"].find_one({"scoring_run_id": run_id, "fabric_id": "cloud"})
    for mid in tata:
        r = a["measures"][mid]
        assert r["score"] is None and r["waiting_for_tata"] and r["scope"] == "tata"
        assert r["missing"] == stacked.WAITING_FOR_TATA


def test_a_score_citing_invented_pages_is_not_placed(db):
    """Code review CR05: links the model wasn't given don't count, so nothing is placed on them."""
    class Inventing(StackedModel):
        def measure(self):
            return {**super().measure(), "evidence_urls": ["https://invented.example/report"]}
    run_id = _run(db)
    with ThreadPoolExecutor(2) as ex:
        engine.assess_technology(run_id, "edge-ai", Inventing(gates=("cloud",)), ex)
    a = db["assessments"].find_one({"scoring_run_id": run_id})
    scored = [r for r in a["measures"].values() if r["score"] is not None]
    assert scored == []
    assert {r["missing"] for r in a["measures"].values() if not r.get("waiting_for_tata")} == {engine.NOT_GIVEN}
