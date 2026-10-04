"""New evidence and readiness: what an assessment read, which pages are new
since, and the one state every screen and batch reads."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from agent.analyzer import engine
from agent.analyzer import pov as pov_composer
from app.main import app
from app.services import evidence
from app.services.db import seeding
from factories import assessment, at, page, pov, run, tech

client = TestClient(app)  # no lifespan: nothing is seeded


def new_urls(tech_id: str = "edge-ai") -> list[str]:
    return [d["end_url"] for d in evidence.state(tech_id)["new"]]


class FakeLLM:
    """One reply that serves the gate (cloud only), every measure and the
    watch metrics."""
    def ask(self, prompt, system=None):
        return '{"fabrics": ["cloud"], "score": 5, "justification": "j", "evidence_urls": ["u"]}'


# ── what an assessment records ──────────────────────────────────────

def test_an_assessment_records_the_page_versions_it_read(db):
    seeding.load_if_new()  # measures, fabrics, scoring config and skills
    tech(db)
    a1 = page(db, "a", 1, summary_text="s")
    page(db, "a", 3, stub_of=a1)  # an unchanged revisit counts as the version it repeats
    b1 = page(db, "b", 2, summary_text="s")
    run_id = engine.create_scoring_run({"technologies": ["edge-ai"]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        engine.assess_technology(run_id, "edge-ai", FakeLLM(), pool)
    row = db["assessments"].find_one({"scoring_run_id": run_id})
    assert row["dossier_pages"] == [a1, b1] and row["doc_count"] == 2
    assert "dossier_from" not in row  # the size guard didn't trip


def test_the_size_guard_records_where_it_cut_and_counts_only_what_it_read(db):
    page(db, "old", 1, summary_text="x" * 400)
    kept = page(db, "kept", 2, summary_text="x" * 400)
    built = engine.build_dossier("edge ai", max_tokens=150)  # room for one entry
    assert built["pages"] == [kept] and built["from"] == at(2)
    assert "1 oldest entries omitted" in built["text"]


# ── which pages are new ─────────────────────────────────────────────

def test_unchanged_revisits_are_not_new_and_changed_pages_are(db):
    tech(db)
    a1, b1 = page(db, "a", 1), page(db, "b", 1)
    page(db, "a", 2, stub_of=a1)  # revisited unchanged before the assessment
    run(db, "r1", 3)
    assessment(db, "r1", 3, pages=[a1, b1])
    page(db, "a", 4, stub_of=a1)  # and after it
    page(db, "b", 4)              # b changed
    assert new_urls() == ["b"]
    assert evidence.state("edge-ai")["state"] == "new_evidence"


def test_pages_the_size_guard_dropped_are_not_new_until_an_unchanged_revisit_lifts_one(db):
    tech(db)
    old, kept = page(db, "old", 1), page(db, "kept", 2)
    run(db, "r1", 3)
    assessment(db, "r1", 3, pages=[kept], dossier_from=at(2))
    assert new_urls() == []
    page(db, "old", 4, stub_of=old)  # now above the cutoff, and its version wasn't read
    assert new_urls() == ["old"]


def test_set_aside_pages_never_count(db):
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    page(db, "job-ad", 3, tech=None, ignored_by="single-job-ad")  # set aside: never linked
    assert new_urls() == []


def test_assessments_from_before_page_versions_compare_dates(db):
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2)          # no dossier_pages recorded
    page(db, "a", 3, stub_of=a1)     # its version was collected before the assessment
    page(db, "b", 3)                 # collected after it
    assert new_urls() == ["b"]


# ── the readiness rule ──────────────────────────────────────────────

def test_reassessed_after_its_pov_it_is_ready_for_a_new_one_everywhere(db, monkeypatch):
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    pov(db, "r1", 2)
    assert evidence.state("edge-ai")["state"] == "current"

    run(db, "r2", 3)
    assessment(db, "r2", 3, pages=[a1])
    s = evidence.state("edge-ai")
    assert s["state"] == "no_pov" and s["assessment"]["scoring_run_id"] == "r2"

    # the technology page, the waiting count, the list and compose-all agree
    summary = client.get("/api/technologies/edge-ai/summary").json()
    assert summary["state"] == "no_pov" and summary["pov"]["from_latest_assessment"] is False
    assert client.get("/api/pipeline").json()["pov"]["pending"] == 1
    assert [u["scoring_run_id"] for u in client.get("/api/scoring/povs").json()["uncomposed"]] == ["r2"]
    started = []
    monkeypatch.setattr(pov_composer, "start_compose_all",
                        lambda targets, recompose=False: started.append(targets) or "job")
    assert client.post("/api/scoring/povs/compose_all", json={}).status_code == 202
    assert started == [[{"scoring_run_id": "r2", "tech_id": "edge-ai"}]]


def test_a_run_that_stopped_partway_keeps_the_previous_assessment(db):
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    run(db, "r2", 3, status="terminated", gates={"edge-ai": ["cloud", "network"]})
    assessment(db, "r2", 3, pages=[a1])  # cloud scored, network never was
    s = evidence.state("edge-ai")
    assert s["state"] == "stopped_partway"
    assert s["assessment"]["scoring_run_id"] == "r1" and s["unfinished"]["scoring_run_id"] == "r2"

    states = evidence.states()  # only on the resume list
    assert [(r["scoring_run_id"], r["tech_ids"]) for r in evidence.stopped_runs(states)] == [("r2", ["edge-ai"])]
    assert evidence.with_new_evidence(states) == [] and evidence.pov_targets(states) == []


def test_new_evidence_without_a_pov_waits_to_be_assessed_not_written(db):
    tech(db)
    a1 = page(db, "a", 1)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1])
    page(db, "b", 3)
    states = evidence.states()
    assert [(t["tech_id"], t["new_pages"]) for t in evidence.with_new_evidence(states)] == [("edge-ai", 1)]
    assert evidence.pov_targets(states) == []


def test_the_remaining_states(db):
    tech(db, "off", "off tech", enabled=False)
    tech(db, "fresh", "fresh tech")
    tech(db, "live", "live tech")
    tech(db, "done", "done tech")
    d1 = page(db, "d", 1, tech="done tech")
    run(db, "r1", 2, techs=("off", "done"))
    assessment(db, "r1", 2, pages=[], tech_id="off")
    assessment(db, "r1", 2, pages=[d1], tech_id="done")
    pov(db, "r1", 2, tech_id="done")
    run(db, "r2", 3, status="running", techs=("live",))
    states = evidence.states(["off", "fresh", "live", "done"])
    assert {k: v["state"] for k, v in states.items()} == {
        "off": "off", "fresh": "not_assessed", "live": "assessing", "done": "current"}


def test_waiting_lists_skip_switched_off_and_deleted_technologies(db):
    tech(db, "off", "off tech", enabled=False)
    page(db, "o", 1, tech="off tech")
    page(db, "g", 1, tech="gone tech")  # its technology was deleted
    run(db, "r1", 2, techs=("off", "gone"))
    assessment(db, "r1", 2, pages=[], tech_id="off")
    assessment(db, "r1", 2, pages=[], tech_id="gone")
    states = evidence.states()
    assert list(states) == ["off"] and evidence.with_new_evidence(states) == []
