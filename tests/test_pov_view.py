"""A Point of View's page: what it shows beside the text, numbered in one
list of sources; a person's override stated with its reason; its model calls
recorded under its own compose job; and switched-off technologies left out
of the list and of Rewrite all."""

import json
import threading

from fastapi.testclient import TestClient

from agent.analyzer import pov
from app.main import app
from app.services.llm.context import call_context
from factories import assessment, page, run, tech
from factories import pov as written
from stacked_fakes import SEEDS, load_seeded

client = TestClient(app)


class Writer:
    """Writes a Point of View, keeping each prompt and what each call was recorded under."""

    def __init__(self):
        self.prompts, self.contexts = [], []

    def ask(self, prompt, system=None, **kw):
        self.prompts.append(prompt)
        self.contexts.append(dict(call_context.get()))
        return json.dumps({"headline": "h", "summary": "It ships [1].", "maturity": "TRL 6 [1]."})


def _world(db, monkeypatch, writer):
    load_seeded(db, "prompts", "measures", "scoring_config", "availability", "domains", "subdomains", "trl_levels",
                "path_steps", "mechanisms", "fabrics")
    tech(db)
    a1 = page(db, "https://lightreading.com/a", 1, source_name="Light Reading", title="Edge AI ships")
    a2 = page(db, "https://ietf.org/b", 2, source_name="IETF", title="A draft")
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[a1], scores=[7, None, 5])
    db["assessments"].update_one({}, {"$set": {"measures.m1.evidence_urls": ["https://lightreading.com/a"],
                                               "measures.m1.justification": "A $4B market in 2026."}})
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"classification": {
        "trl": {"level": 6, "reason": "a field trial", "pages": [a1], "at": "2026-09-02"}}}})
    r = client.post("/api/decisions", json={"kind": "override", "tech_id": "edge-ai", "fabric_id": "cloud",
                                            "value": "P1", "reason": "the board asked for it"})
    assert r.status_code == 201, r.text
    monkeypatch.setattr(pov.LLM, "initialize", classmethod(lambda cls, *a, **k: writer))
    return a1, a2


def test_the_page_numbers_everything_in_one_list_and_states_the_override(db, monkeypatch):
    w = Writer()
    a1, a2 = _world(db, monkeypatch, w)
    pov.compose_pov("r1", "edge-ai")
    # the writer is told the priority is a person's, with the computed one and their reason
    assert "Priority P1 (set by a person; the scores give P2; their reason: the board asked for it)" in w.prompts[0]

    # classified again after it was written: availability now rests on a page the text never cited
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"classification.availability": {
        "value_id": "pilot", "reason": "a pilot", "pages": [a2], "at": "2026-09-03"}}})
    got = client.get("/api/scoring/runs/r1/pov/edge-ai").json()
    assert [(s["n"], s["url"]) for s in got["sources"]] == [(1, "https://lightreading.com/a"), (2, "https://ietf.org/b")]
    assert got["classification"]["trl"]["refs"] == [1] and got["classification"]["availability"]["refs"] == [2]
    f = got["fabrics"][0]
    assert (f["priority"], f["computed_priority"], f["override"]["reason"]) == ("P1", "P2", "the board asked for it")
    assert f["measures"]["m1"]["refs"] == [1] and f["measures"]["m2"]["refs"] == []
    assert f["finance"]["needed"] is False and f["path_step"] is None
    assert {m["_id"] for m in got["measures"]} >= {"growth"}  # the run's own measures, for their names


def test_a_value_from_tatas_catalog_is_said_to_be_tatas_with_what_the_radar_judged(db, monkeypatch):
    _, a2 = _world(db, monkeypatch, Writer())
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"classification.availability": {
        "value_id": "research", "reason": "lab work only", "pages": [a2], "at": "2026-09-03"}}})
    r = client.post("/api/decisions", json={"kind": "move", "tech_id": "edge-ai", "field": "availability",
                                            "value": "pilot", "reason": "Imported from tata.xlsx"})
    assert r.status_code == 201, r.text
    data = pov.pov_inputs("r1", "edge-ai")[1]["assessment_data"]
    assert "- Commercial availability: Pilot, from Tata's catalog (tata.xlsx); the radar judged Research" in data
    assert "set by a person" not in data.split("- Readiness")[0]


def test_the_bottlenecks_and_the_step_reached_go_to_the_writer_and_the_page(db, monkeypatch):
    _world(db, monkeypatch, Writer())
    blocker = db["fabrics"].find_one({"_id": "cloud"})["bottlenecks"][0]
    for kind, value in (("bottlenecks", {"picked": [blocker]}), ("path_step", "proof_of_concept")):
        r = client.post("/api/decisions", json={"kind": kind, "tech_id": "edge-ai", "fabric_id": "cloud", "value": value})
        assert r.status_code == 201, r.text
    data = pov.pov_inputs("r1", "edge-ai")[1]["assessment_data"]
    assert "- Cloud: step reached on the path to scale: Proof of concept (step 3 of 7)" in data
    assert f"blockers that could stop it scaling: {blocker}. Commitment: No owner yet." in data
    f = client.get("/api/scoring/runs/r1/pov/edge-ai")
    assert f.status_code == 404  # none written yet
    pov.compose_pov("r1", "edge-ai")
    f = client.get("/api/scoring/runs/r1/pov/edge-ai").json()["fabrics"][0]
    assert f["path_step"] == "Proof of concept" and f["finance"]["bottlenecks"]["picked"] == [blocker]


def test_tatas_plan_goes_to_the_writer_in_full(db, monkeypatch):
    _world(db, monkeypatch, Writer())
    for kind, value, reason in (
            ("path_step", "customer_zero", "Our own service desk runs it."),
            ("finance", {"cost_per_outcome": "$2.80 a request against $6.90.", "buyer": "A bank.", "price": 0.45}, None),
            ("bottlenecks", {"other": "Data must stay in India."}, None),
            ("commitment", {"owner": "Head of product", "next_action": "Sign the pilot.", "due": "2026-12-15",
                            "budget": "$240k"}, None)):
        r = client.post("/api/decisions", json={"kind": kind, "tech_id": "edge-ai", "fabric_id": "cloud",
                                                "value": value, "reason": reason})
        assert r.status_code == 201, r.text
    data = pov.pov_inputs("r1", "edge-ai")[1]["assessment_data"]
    line = next(x for x in data.splitlines() if x.startswith("- Cloud: step reached"))
    assert line == ("- Cloud: step reached on the path to scale: Customer zero (step 2 of 7); the reason recorded: Our own service desk "
                    "runs it. proof Tata has recorded: measured cost per outcome against the current process: $2.80 a "
                    "request against $6.90; a named buyer: A bank; an indicative price: $0.45 a unit. next step Proof of "
                    "concept, which still needs: a budget or willingness to pay. blockers that could stop it scaling: Data "
                    "must stay in India. owner: Head of product; next action: Sign the pilot, due 15 Dec 2026; budget "
                    "committed: $240k. Commitment: Integrated.")


def test_a_section_nested_in_another_goes_back_to_its_place(db, monkeypatch):
    w = Writer()
    w.ask = lambda prompt, system=None, **kw: json.dumps({"headline": "h", "tora_analysis": {
        "market_potential": "m", "recommendation": "Pilot it.", "evidence_gaps": [{"fabric": "Cloud", "missing": ["x"]}]}})
    _world(db, monkeypatch, w)
    s = pov.compose_pov("r1", "edge-ai")["sections"]
    assert s["recommendation"] == "Pilot it." and s["evidence_gaps"][0]["fabric"] == "Cloud"
    assert s["tora_analysis"] == {"market_potential": "m"}


def test_its_calls_are_recorded_under_its_own_compose_job(db, monkeypatch):
    w = Writer()
    _world(db, monkeypatch, w)
    doc = pov.compose_pov("r1", "edge-ai")
    assert w.contexts[0]["run_kind"] == "pov" and w.contexts[0]["run_id"] == doc["compose_job_id"] != "r1"
    assert doc["scoring_run_id"] == "r1"  # the link to the assessment stays, as data

    job = pov.start_compose_all([{"scoring_run_id": "r1", "tech_id": "edge-ai"}])
    for t in threading.enumerate():
        if t.name == f"pov-batch-{job}":
            t.join(10)
    assert w.contexts[1]["run_id"] == job
    assert db["povs"].find_one()["compose_job_id"] == job


def test_switched_off_technologies_are_left_out_of_the_list_and_rewrite_all(db, monkeypatch):
    tech(db)
    tech(db, "quic", "quic", enabled=False)
    run(db, "r1", 2, techs=("edge-ai", "quic"))
    for t in ("edge-ai", "quic"):
        assessment(db, "r1", 2, pages=[page(db, f"https://{t}.example/a", 1, tech=t.replace("-", " "))], tech_id=t)
        written(db, "r1", 2, tech_id=t)
    body = client.get("/api/scoring/povs").json()
    assert [p["tech_id"] for p in body["povs"]] == ["edge-ai"]
    assert body["switched_off"] == 1 and body["assessed"] == 1
    started = []
    monkeypatch.setattr(pov, "start_compose_all", lambda targets, recompose=False, tz=None: started.append(targets) or "j")
    assert client.post("/api/scoring/povs/compose_all", json={"recompose": True}).status_code == 202
    assert started == [[{"scoring_run_id": "r1", "tech_id": "edge-ai"}]]


def test_a_sign_to_watch_cites_its_page():
    a = {"fabric": "Cloud", "doc_count": 1, "tora": {}, "placement": {}, "measures": {},
         "watch_metrics": [{"metric": "Paying customers", "current_value": "300", "inflection_threshold": "1,000",
                            "implication": "proven", "source": "https://blogs.cisco.com/a"}]}
    text = pov._assessment_digest([a], {}, None, cite=lambda urls: " [4]" if urls == ["https://blogs.cisco.com/a"] else "")
    assert "| source: [4]" in text


def test_the_skill_states_overrides_and_sources_every_number():
    skill = next(p for p in json.loads((SEEDS / "prompts.json").read_text())["prompts"] if p["name"] == "pov")
    assert "A priority set by a person" in skill["system"] and "guesstimate" in skill["system"]
    assert "Where a person set a priority" in skill["prompt"]
