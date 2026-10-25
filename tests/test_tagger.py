"""Link known names: names given once per known technology, a free match on
the stored pages (a one-word name only as written), a check of each match,
pages about it filed as its evidence, pages naming it in passing counted
apart, each page checked once, failures said, and the collection's record."""

import json

from fastapi.testclient import TestClient

from agent.tagger import tagger
from app.main import app
from factories import as_if_relinked_in_full, tech, with_text
from stacked_fakes import load_seeded

client = TestClient(app)


class Model:
    """Names for each technology; and a verdict per passage, from its words."""
    def __init__(self):
        self.prompts = []

    def ask(self, prompt, system=None, **kw):
        self.prompts.append(prompt)
        if "Reply with JSON only, one key per id" in prompt:
            rows = json.loads(prompt.split("Technologies:\n", 1)[1].split("\n\nReply", 1)[0])
            names = {"flexe": ["Flex Ethernet", "FlexE"], "matter": ["Matter protocol"]}
            return json.dumps({r["id"]: {"names": names.get(r["id"], []),
                                         "not_a_technology": "an application area" if r["id"] == "ai-in-finance" else None}
                               for r in rows})
        out = {}
        for part in prompt.split("Passages:\n", 1)[1].split("\n\n["):
            n = part.lstrip("[").split("]", 1)[0]
            out[n] = "about" if "trial" in part else "mention"
        return json.dumps(out)


def _doc(db, doc_id, text, **extra):
    with_text(db, {"_id": doc_id, "end_url": f"https://{doc_id}.example", "title": doc_id, "is_stub": False,
                   "ignored_by": None, "extracted_text": text, "technologies": [],
                   "technologies_resolved": [], "source_id": "s", "run_id": "c1", **extra})


def _world(db, monkeypatch):
    load_seeded(db, "prompts")
    for tid, name in (("flexe", "flex ethernet (flexe)"), ("matter", "matter (iot protocol)"), ("ai-in-finance", "ai in finance")):
        tech(db, tid, name)
        db["technologies"].update_one({"_id": tid}, {"$set": {"origin": "imported"}})  # in the catalog
    model = Model()
    monkeypatch.setattr(tagger.LLM, "initialize", classmethod(lambda cls, *a, **k: model))
    return model


def test_one_word_names_match_only_as_written():
    idx = tagger.index([{"_id": "flexe", "name": "x", "look_for": ["Flex Ethernet", "FlexE"]},
                        {"_id": "did", "name": "y", "look_for": ["DID"]}])
    found = tagger.matches("We did a trial of flex-ethernet; FLEXE and FlexE both appear. DID wallets too.", idx)
    assert found["flexe"][0] == 2 and found["did"][0] == 1  # "flex-ethernet" and "FlexE"; not "FLEXE", not "did"


def test_names_then_match_then_check_then_file(db, monkeypatch):
    model = _world(db, monkeypatch)
    _doc(db, "a", "Operators began a FlexE trial on 400G links. " * 5)
    _doc(db, "b", "Among Ethernet options (FlexE, LAG, MLAG) the vendor lists many.")
    _doc(db, "c", "It doesn't matter what the protocol is.")  # "matter" alone is never a name
    _doc(db, "d", "A FlexE trial set aside.", ignored_by="event")
    run_id = tagger.start(wait=True)
    run = db["tag_runs"].find_one({"_id": run_id})
    assert run["status"] == "completed" and run["pages_about"] == 1 and run["pages_mention"] == 1, run
    flexe = db["technologies"].find_one({"_id": "flexe"})
    assert flexe["look_for"][:3] == ["flex ethernet (flexe)", "Flex Ethernet", "FlexE"] and flexe["page_count"] == 1
    assert db["technologies"].find_one({"_id": "ai-in-finance"})["not_a_technology"] == "an application area"
    assert "flex ethernet (flexe)" in db["documents"].find_one({"_id": "a"})["technologies_resolved"]
    b = db["documents"].find_one({"_id": "b"})
    assert b["mentions"] == ["flex ethernet (flexe)"] and not b["technologies_resolved"]  # in passing: not evidence
    assert "name_checks" not in db["documents"].find_one({"_id": "c"})
    assert "name_checks" not in db["documents"].find_one({"_id": "d"})  # a set-aside page is never filed
    calls = len(model.prompts)
    tagger.start(wait=True)  # each page and technology is checked once
    assert len(model.prompts) == calls
    as_if_relinked_in_full(db)


def test_a_failed_check_is_said_and_tried_again(db, monkeypatch):
    _world(db, monkeypatch)
    _doc(db, "a", "A FlexE trial began.")

    class Broken(Model):
        def ask(self, prompt, system=None, **kw):
            if "Passages:" in prompt:
                raise RuntimeError("Overloaded")
            return super().ask(prompt, system, **kw)
    monkeypatch.setattr(tagger.LLM, "initialize", classmethod(lambda cls, *a, **k: Broken()))
    run = db["tag_runs"].find_one({"_id": tagger.start(wait=True)})
    assert run["status"] == "completed" and "Overloaded" in run["failed"][0]
    assert "name_checks" not in db["documents"].find_one({"_id": "a"})  # unchecked: the next run tries again


def test_a_person_sets_the_names_and_the_api_starts_a_catch_up(db, monkeypatch):
    _world(db, monkeypatch)
    r = client.put("/api/technologies/flexe/look-for", json={"names": ["FlexE", "  flexe ", "Flex Ethernet"]})
    assert r.json()["look_for"] == ["flex ethernet (flexe)", "FlexE", "Flex Ethernet"]
    assert db["technologies"].find_one({"_id": "flexe"})["look_for_by"] == "person"
    pre = client.get("/api/tagging").json()
    assert pre["technologies"] == 3 and pre["without_names"] == 2 and pre["naming_calls"] == 1
    monkeypatch.setattr(tagger, "start", lambda *a, **k: None)
    import app.api.tagging as api
    monkeypatch.setattr(api.tagger, "start", lambda *a, **k: None)
    assert client.post("/api/tagging").status_code == 409


def test_a_collection_says_what_linking_found(db):
    db["runs"].insert_one({"_id": "c9", "status": "completed", "sources": [], "run_start_date_time": "2026-10-22T10:00:00+00:00"})
    db["tag_runs"].insert_one({"_id": "t1", "trigger": "after collection c9", "status": "completed", "started_at": "x",
                               "pages_about": 4, "pages_mention": 9, "linked_techs": ["a", "b"], "failed": []})
    link = client.get("/api/runs/c9").json()["link"]
    assert (link["pages_about"], link["pages_mention"], link["linked"]) == (4, 9, 2)


def test_a_run_cut_off_by_a_restart_is_said_and_does_not_block(db, monkeypatch):
    _world(db, monkeypatch)
    db["tag_runs"].insert_one({"_id": "old", "status": "running", "started_at": "2026-10-22T10:00:00+00:00",
                               "heartbeat_at": "2026-10-22T10:05:00+00:00"})
    assert tagger.start(wait=True) is not None
    old = db["tag_runs"].find_one({"_id": "old"})
    assert old["status"] == "failed" and "server restarted" in old["error"]
