"""Stacked calls: built once per call, shared material once, reusable parts
first, each key checked by its own skill's rules, and the one rule for what
fails."""

import json

from app.services.prompts import recipe as recipes
from app.services.prompts.recipe import Failure, Task
from agent.analyzer import engine, stacked
from stacked_fakes import load_seeded

EVIDENCE = "- [article] Edge AI chips ship\n  url: https://a · summary: shipping now"


def _tasks(db):
    measures = list(db["measures"].find())
    tech = [m for m in measures if m["scope"] == "technology"]
    return [Task("fabric_relevance", "fabric_relevance", "Choose the fabrics", {"fabrics": "- cloud: Cloud"}),
            *(stacked._measure_task(m, None) for m in tech),
            Task("watch_metrics", "watch_metrics", "Suggest metrics to watch")], tech


def test_the_evidence_is_given_once_first_and_the_instructions_carry_none_of_it(db):
    load_seeded(db, "prompts", "measures", "recipes")
    tasks, tech = _tasks(db)
    built = recipes.build({"_id": "technology", "cache": "evidence"}, tasks,
                          {"technology": "edge ai", "evidence": EVIDENCE})
    whole = "\n".join(built.blocks + [built.user])
    assert whole.count("Edge AI chips ship") == 1 and built.blocks[0].startswith("TECHNOLOGY: edge ai")
    assert "edge ai" not in built.blocks[1] and "Edge AI chips" not in built.blocks[1]  # the same for every technology
    assert built.keys == ["fabric_relevance", *(f"measure:{m['_id']}" for m in tech), "watch_metrics"]
    assert set(built.skills) == {"fabric_relevance", "measure_scoring", "watch_metrics"}
    for m in tech:
        assert f"### measure:{m['_id']}: Score one measure: {m['name']}" in built.blocks[1]


def test_instructions_first_when_the_recipe_says_so(db):
    load_seeded(db, "prompts", "measures")
    tasks, _ = _tasks(db)
    built = recipes.build({"_id": "classify", "cache": "instructions"}, tasks, {"technology": "edge ai", "evidence": EVIDENCE})
    assert len(built.blocks) == 1 and "Edge AI chips" not in built.blocks[0] and "Edge AI chips" in built.user


def test_each_key_is_checked_by_its_own_rules(db):
    load_seeded(db, "prompts", "measures")
    tasks, tech = _tasks(db)
    built = recipes.build({"_id": "technology"}, tasks, {"technology": "t", "evidence": "e"})
    first, second = (f"measure:{m['_id']}" for m in tech[:2])
    reply = ('{"fabric_relevance": {"fabrics": ["cloud", "nowhere"]}, "%s": {"score": 14, "evidence_urls": ["u"]}, '
             '"%s": {"score": 6, "evidence_urls": []}, "watch_metrics": "soon"}' % (first, second))
    out = recipes.parse(reply, built, {"fabric_relevance": stacked._relevance_check([{"_id": "cloud"}]),
                                       "measure_scoring": stacked._measure_check, "watch_metrics": stacked._watch_check(None)})
    assert out["fabric_relevance"] == ["cloud"]
    assert out[first]["score"] == 10                                   # clamped to 0–10
    assert out[second]["score"] is None and out[second]["unscorable"]  # a score citing no pages doesn't count
    assert isinstance(out["watch_metrics"], Failure)
    assert isinstance(out[f"measure:{tech[2]['_id']}"], Failure)       # left out of the reply
    assert all(isinstance(v, Failure) for v in recipes.parse("no json", built, {}).values())


def test_no_json_is_asked_again_whole_then_a_failed_task_alone_then_it_takes_its_default(db):
    load_seeded(db, "prompts", "measures")
    tasks, tech = _tasks(db)
    built = recipes.build({"_id": "technology"}, tasks, {"technology": "t", "evidence": "e"})
    first = f"measure:{tech[0]['_id']}"
    answer = {"fabric_relevance": {"fabrics": ["cloud"]}, "watch_metrics": [],
              **{f"measure:{m['_id']}": {"score": 6, "evidence_urls": ["u"]} for m in tech[1:]}}  # first left out

    class Model:
        replies = ["no json", json.dumps(answer), "still no json"]

        def ask(self, prompt, system=None, *, blocks=None):
            return self.replies.pop(0)

    counted = []
    out, retries = recipes.ask(Model(), built, {"fabric_relevance": stacked._relevance_check([{"_id": "cloud"}]),
                                                "measure_scoring": stacked._measure_check,
                                                "watch_metrics": stacked._watch_check(None)},
                               {"measure_scoring": engine.unscored}, on_call=lambda: counted.append(1))
    assert len(counted) == 3 and retries == 1  # whole, whole again, the left-out measure alone
    assert out["fabric_relevance"] == ["cloud"] and out[f"measure:{tech[1]['_id']}"]["score"] == 6
    assert out[first]["score"] is None and "not valid JSON" in out[first]["missing"]  # unscored, saying why


def test_the_preview_shows_what_a_run_sends(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from factories import page, tech
    load_seeded(db, "prompts", "measures", "recipes", "scoring_config", "fabrics")
    tech(db)
    page(db, "a", 1, summary_text="Edge AI chips ship")
    body = TestClient(app).get("/api/recipes/fabric/preview", params={"technology": "edge-ai"}).json()
    assert [p["reused"] for p in body["parts"]] == [True, True, False]
    assert "Edge AI chips ship" in body["parts"][0]["text"] and body["fabric"]["id"] in body["parts"][2]["text"].lower() \
        or body["fabric"]["name"] in body["parts"][2]["text"]
    built = stacked.fabric_built(db["recipes"].find_one({"_id": "fabric"}), "edge ai",
                                 body["parts"][0]["text"].split("EVIDENCE:\n", 1)[1],
                                 list(db["measures"].find()), db["fabrics"].find_one({"_id": body["fabric"]["id"]}))
    assert [p["text"] for p in body["parts"]] == [*built.blocks, built.user]
