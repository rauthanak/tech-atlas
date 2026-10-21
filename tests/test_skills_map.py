"""Where each skill is used: every skill once, in its step, switched-off ones
marked, with its last run's calls."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_every_seeded_skill_appears_once_in_its_step(db):
    prompts = json.loads((Path(__file__).parents[1] / "seeds/prompts.json").read_text())["prompts"]
    db["prompts"].insert_many([{"_id": p["name"], **p} for p in prompts])
    db["prompts"].update_one({"_id": "watch_metrics"}, {"$set": {"enabled": False}})
    body = client.get("/api/skills/map").json()
    placed = [s["name"] for st in body["stages"] for s in st["skills"]]
    assert sorted(placed) == sorted(p["name"] for p in prompts) and body["unplaced"] == []
    assessing = next(st for st in body["stages"] if st["id"] == "assess")
    watch = next(s for s in assessing["skills"] if s["name"] == "watch_metrics")
    assert watch["enabled"] is False and watch["title"] == "Suggest metrics to watch"
    assert next(s for s in assessing["skills"] if s["name"] == "analyzer")["agent"] is True


def _call(run_id, at, kind, skills, recipe=None, n=1):
    return [{"run_id": run_id, "run_kind": kind, "at": at, "skills": skills, "recipe": recipe, "input_tokens": 100,
             "output_tokens": 10, "cache_read_tokens": 50, "cache_write_tokens": 0} for _ in range(n)]


def test_numbers_come_from_the_steps_last_full_run(db):
    db["prompts"].insert_one({"_id": "pov", "name": "pov", "stage": "pov", "title": "Write the Point of View"})
    db["prompts"].insert_one({"_id": "article_summary", "name": "article_summary", "stage": "collect"})
    db["llm_calls"].insert_many(
        _call("r1", "2026-10-01", "pov", ["pov"], n=4) + _call("r2", "2026-10-02", "pov", ["pov"], n=2)
        + _call("t3", "2026-10-03", "pov", ["pov"])                         # a test run: too small to count
        + _call("c1", "2026-10-02", "collection", ["article_summary"], n=3)
        + _call("fe", "2026-10-04", "find_evidence", ["article_summary"]))  # another kind of run
    stages = {s["id"]: s for s in client.get("/api/skills/map").json()["stages"]}
    assert stages["pov"]["run"]["run_id"] == "r2" and stages["pov"]["run"]["calls"] == 2
    assert stages["pov"]["skills"][0]["alone"] == {"calls": 2, "tokens_in": 300, "tokens_out": 20, "reused": 100}
    assert stages["collect"]["run"]["run_id"] == "c1" and stages["collect"]["skills"][0]["alone"]["calls"] == 3
    assert stages["classify"]["run"] is None


def test_a_stacked_call_keeps_its_tokens_and_skills_are_named(db):
    db["prompts"].insert_many([{"_id": s, "name": s, "stage": "classify", "title": s.title()}
                               for s in ("trl_level", "domain_subdomain")])
    db["recipes"].insert_many([{"_id": "classify", "name": "Classify call", "stage": "classify",
                                "skills": ["trl_level", "domain_subdomain"]},
                               {"_id": "technology", "name": "Technology call", "stage": "assess",
                                "skills": ["domain_subdomain"]}])
    both = ["trl_level", "domain_subdomain"]
    db["llm_calls"].insert_many(_call("k1", "2026-10-02", "classify", both, "classify", n=3)
                                + _call("k1", "2026-10-02", "classify", ["trl_level"]))  # one task asked alone
    classify = next(s for s in client.get("/api/skills/map").json()["stages"] if s["id"] == "classify")
    box = classify["recipes"][0]
    assert box["name"] == "Classify call" and box["used"]["calls"] == 3
    assert box["alone"] == {"trl_level": {"calls": 1, "tokens_in": 150, "tokens_out": 10, "reused": 50}}
    skills = {s["name"]: s for s in classify["skills"]}
    assert skills["domain_subdomain"]["alone"] is None                 # the call's tokens aren't its own
    assert [r["name"] for r in skills["domain_subdomain"]["recipes"]] == ["Classify call", "Technology call"]
