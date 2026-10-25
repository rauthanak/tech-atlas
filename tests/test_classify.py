"""Classify: a bounded, numbered evidence pack, findings first; incremental
calls; a page visited twice no longer waits once classified; each answer
checked; the budget stop says why; switched-off skipped;
the effective order (a person, the assessment, the pages, the catch-all)."""

import json

from agent.classifier import classify
from agent.classifier.evidence import pack
from app.services import classify_effective, decisions
from factories import page, tech
from stacked_fakes import load_seeded


def _world(db, pages=4):
    load_seeded(db, "prompts", "recipes", "availability", "domains", "subdomains", "trl_levels")
    db["sources"].insert_one({"_id": "s", "name": "Light Reading", "cluster": "analysts_trade_press"})
    tech(db)
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"page_count": pages}})
    for n in range(pages):
        page(db, f"p{n}", n + 1, summary_text=f"summary {n}", source_name="Light Reading")
    page(db, "finding", 1, summary_text="a trial", source_name="Light Reading",
         signals=[{"signal_id": "trial", "label": "Field trial", "quote": "the first field trial began",
                   "technologies_resolved": ["edge ai"]}])


class Model:
    """Answers the Classify call by its keys; `bad` makes those keys fail their rules."""
    def __init__(self, bad=(), flag=False):
        self.bad, self.flag, self.calls = set(bad), flag, []

    def answer(self, key):
        if key in self.bad:
            return {"oops": True}
        return {"evidence_strength": {"verdict": "enough", "reason": "two trade sources", "pages": [1, 2]},
                "domain_subdomain": {"domain_id": "ai", "subdomain": "Edge AI", "reason": "on-device models", "pages": [1]},
                "commercial_availability": {"value_id": "pilot", "reason": "a named trial", "pages": [1]},
                "trl_level": {"level": 6, "reason": "a field trial", "pages": [1]},
                "possible_nascent": ({"flag": True, "reason": "first trial", "quote": "the first field trial began", "page": 1}
                                     if self.flag else {"flag": False})}[key]

    def ask(self, prompt, system=None, *, blocks=None):
        self.calls.append({"prompt": prompt, "blocks": blocks})
        text = "\n".join([*(blocks or []), prompt])
        if "Its keys are exactly" in text:
            keys = text.split("Its keys are exactly: ")[1].split(". Under")[0].split(", ")
            return json.dumps({k: self.answer(k) for k in keys})
        return json.dumps(self.answer(next(k for k in ("evidence_strength", "domain_subdomain", "commercial_availability",
                                                          "trl_level", "possible_nascent") if k in self.bad)).copy()
                          | {"verdict": "thin", "reason": "asked alone", "domain_id": "ai", "value_id": "research",
                             "level": 3, "flag": False})


def test_the_pack_is_bounded_numbered_and_findings_first(db):
    _world(db, pages=12)
    ev = pack("edge ai", 5)
    assert ev["read"] == 5 and ev["of"] == 13 and len(ev["pages"]) == 5 and ev["sources"] == 1
    assert ev["text"].startswith("[1] Light Reading (analysts trade press)") and "the first field trial began" in ev["text"].split("[2]")[0]
    assert "13 pages about it in all, from 1 independent source" in ev["facts"]
    assert pack("edge ai", 5, seen=set(ev["pages"]))["pages"] and set(pack("edge ai", 5, seen=set(ev["pages"]))["pages"]).isdisjoint(ev["pages"])


def test_one_call_writes_every_answer_with_its_pages_and_the_lists_lead(db):
    _world(db)
    model = Model(flag=True)
    ls = classify.lists()
    r = classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c1", ls, 10)
    assert r["status"] == "classified" and len(model.calls) == 1
    assert "summary 0" not in model.calls[0]["blocks"][0]  # the tasks and lists lead, the same for every technology
    assert "summary 0" in model.calls[0]["prompt"]
    c = db["technologies"].find_one({"_id": "edge-ai"})["classification"]
    assert c["evidence"]["verdict"] == "enough" and len(c["evidence"]["pages"]) == 2 and c["evidence"]["of"] == 5
    assert c["domain"]["domain_id"] == "ai" and c["availability"]["value_id"] == "pilot" and c["trl"]["level"] == 6
    assert c["nascent"]["quote"] == "the first field trial began" and c["nascent"]["page"]
    assert c["domain"]["subdomain_id"] is None or c["domain"]["subdomain_id"].startswith("ai--")


def test_a_failed_answer_is_asked_alone_and_an_unknown_subdomain_is_proposed(db):
    _world(db)
    model = Model(bad={"trl_level"})
    classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c1", classify.lists(), 10)
    assert len(model.calls) == 2  # the stacked call, then TRL alone
    assert db["technologies"].find_one({"_id": "edge-ai"})["classification"]["trl"]["level"] == 3
    checks = classify.validators(classify.lists(), ["d1"])
    out = checks["domain_subdomain"]({"domain_id": "ai", "subdomain": "Agent memory", "reason": "r", "pages": [1, 9]}, None)
    assert out["subdomain_new"] == "Agent memory" and out["pages"] == ["d1"]
    for bad in ({"domain_id": "nowhere", "reason": "r"}, {"level": 12}, {"value_id": "soon", "reason": "r"}):
        key = "domain_subdomain" if "domain_id" in bad else "trl_level" if "level" in bad else "commercial_availability"
        try:
            checks[key](bad, None)
            raise AssertionError("expected a refusal")
        except ValueError:
            pass


def test_incremental_calls_send_current_answers_and_only_new_pages(db):
    _world(db)
    model = Model()
    classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c1", classify.lists(), 10)
    assert classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c2", classify.lists(), 10) \
        == {"status": "unchanged"}
    page(db, "new", 9, summary_text="a launch", source_name="Light Reading")
    assert "edge-ai" in classify.pending()
    classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c3", classify.lists(), 10)
    sent = model.calls[-1]["prompt"]
    assert sent.startswith("CURRENT ANSWERS") and "a launch" in sent and "summary 0" not in sent


def test_a_page_visited_twice_is_not_pending_once_classified_nor_after_nothing_new(db):
    _world(db, pages=0)
    db["documents"].delete_many({})  # only the one page, visited twice, its content changed
    old, new = page(db, "p", 1, summary_text="the old text"), page(db, "p", 2, summary_text="the new text")
    model = Model()
    classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c1", classify.lists(), 10)
    assert "the new text" in model.calls[0]["prompt"] and "the old text" not in model.calls[0]["prompt"]
    assert "edge-ai" not in classify.pending()  # the older visit is known, though only the newer was read
    # as runs before this fix left it: only the newer visit recorded; a call with nothing new clears it
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"pages_seen": [new]}})
    assert "edge-ai" in classify.pending()
    assert classify.classify_one(model, db["technologies"].find_one({"_id": "edge-ai"}), "c2", classify.lists(), 10) \
        == {"status": "unchanged"} and len(model.calls) == 1
    assert "edge-ai" not in classify.pending()
    assert set(db["technologies"].find_one({"_id": "edge-ai"})["pages_seen"]) == {old, new}


def test_the_run_skips_switched_off_and_judges_all_it_was_given(db, monkeypatch):
    _world(db)
    tech(db, "quic", "quic", enabled=False)
    monkeypatch.setattr(classify.LLM, "initialize", classmethod(lambda cls, *a, **k: Model()))
    run_id = classify.start(["edge-ai", "quic"], wait=True)
    run = db["classify_runs"].find_one({"_id": run_id})
    assert run["status"] == "completed" and run["done"] == 2 and run["unchanged"] == 1
    assert "quic" not in classify.pending()
    assert "budget" not in run and "stopped_reason" not in run  # no token limit: a run judges everything


def test_catalog_technologies_are_judged_first_then_the_most_pages(db):
    tech(db, "a", "a")
    tech(db, "b", "b")
    tech(db, "c", "c")
    db["technologies"].update_one({"_id": "c"}, {"$set": {"origin": "imported"}})  # in the catalog
    for n in range(3):
        page(db, f"b{n}", n + 1, tech="b")
    page(db, "a0", 1, tech="a")
    page(db, "c0", 1, tech="c")
    assert classify.pending() == ["c", "b", "a"]


def test_a_person_then_the_assessment_then_the_pages_then_the_catch_all(db):
    _world(db)
    lists = classify_effective.names()
    t = db["technologies"].find_one({"_id": "edge-ai"})
    assert classify_effective.effective(t, [], lists)["availability"]["id"] == "unclassified"
    t["classification"] = {"availability": {"value_id": "pilot", "reason": "a trial", "pages": ["a"]}}
    assert classify_effective.effective(t, [], lists)["availability"]["source"] == "pages"
    t["assessed_classification"] = {"availability": {"value_id": "early_commercial", "reason": "sold"}}
    e = classify_effective.effective(t, [], lists)["availability"]
    assert (e["id"], e["source"], e["emerging"]) == ("early_commercial", "assessment", True)
    move = decisions.create("move", "edge-ai", field="availability", value="mature", tz="UTC")
    e = classify_effective.effective(t, [move], lists)["availability"]
    assert (e["id"], e["source"], e["emerging"]) == ("mature", "person", False)


def test_nascent_yes_moves_availability_and_no_holds_until_a_new_page(db):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    _world(db)
    classify.classify_one(Model(flag=True), db["technologies"].find_one({"_id": "edge-ai"}), "c1", classify.lists(), 10)
    lists = classify_effective.names()
    t = lambda: db["technologies"].find_one({"_id": "edge-ai"})
    assert classify_effective.effective(t(), decisions.active(["edge-ai"]), lists)["nascent"]["flag"]
    client.post("/api/decisions", json={"kind": "nascent", "tech_id": "edge-ai", "value": "yes"})
    e = classify_effective.effective(t(), decisions.active(["edge-ai"]), lists)
    assert e["nascent"]["decision"] == "yes" and (e["availability"]["id"], e["availability"]["source"]) == ("pilot", "person")
    client.post("/api/decisions", json={"kind": "nascent", "tech_id": "edge-ai", "value": "no"})
    assert classify_effective.effective(t(), decisions.active(["edge-ai"]), lists)["nascent"]["decision"] == "no"
    # a page it hadn't seen flags it again
    db["technologies"].update_one({"_id": "edge-ai"}, {"$set": {"classification.nascent.page": "brand-new-page"}})
    assert classify_effective.effective(t(), decisions.active(["edge-ai"]), lists)["nascent"]["decision"] is None


def test_removing_a_list_item_moves_its_technologies_to_the_flagged_catch_all(db):
    from fastapi.testclient import TestClient
    from app.main import app
    _world(db)
    classify.classify_one(Model(), db["technologies"].find_one({"_id": "edge-ai"}), "c1", classify.lists(), 10)
    db["availability"].update_many({}, {"$set": {"catch_all": False}})  # the catch-all is an editable flag
    db["availability"].insert_one({"_id": "not_judged", "availability_id": "not_judged", "name": "Not judged",
                                   "catch_all": True})
    assert TestClient(app).delete("/api/lists/availability/pilot").json()["moved_to_catch_all"] == 1
    t = db["technologies"].find_one({"_id": "edge-ai"})
    assert t["classification"]["availability"]["value_id"] == "not_judged" and t["classification_stale"]


def test_a_classify_running_at_start_up_is_marked_and_no_longer_blocks(db):
    from agent.classifier import classify

    db["classify_runs"].insert_one({"_id": "c1", "status": "running", "started_at": "2026-10-22T10:00:00+00:00"})
    assert classify.active_run()
    classify.reconcile_stale()
    run = db["classify_runs"].find_one({"_id": "c1"})
    assert run["status"] == "terminated" and "restarted" in run["error"]
    assert classify.active_run() is None


def test_who_waits_for_classify_is_read_from_the_answers_kept_ready_or_the_pages_for_marked_ones(db, monkeypatch):
    """The same list whether a technology's answers are worked out (read from them) or marked (read from its pages)."""
    from app.services import tech_status
    test_catalog_technologies_are_judged_first_then_the_most_pages(db)       # the stored answers, worked out
    monkeypatch.setattr(tech_status, "ALWAYS_FRESH", False)
    tech_status.touch(["a", "b", "c"])                                         # marked: their pages just changed
    monkeypatch.setattr(tech_status, "FRESH_MAX", 0)                          # nothing worked out at once
    assert classify.pending() == ["c", "b", "a"]
