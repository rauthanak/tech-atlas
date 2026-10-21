"""A Point of View records the writer's time zone."""

from fastapi.testclient import TestClient

from app.main import app
from factories import assessment, page, run, tech

client = TestClient(app)


class Replies:
    def ask(self, prompt, system=None, **kw):
        return '{"headline": "h", "summary": "s"}'


def test_the_writers_zone_is_stored_and_a_bad_or_missing_one_uses_the_default(db, monkeypatch):
    from agent.analyzer import pov
    monkeypatch.setattr(pov.LLM, "initialize", classmethod(lambda cls, *a, **k: Replies()))
    db["prompts"].insert_one({"_id": "pov", "name": "pov", "prompt": "{technology} {assessment_data}",
                              "system": None, "variables": ["technology", "assessment_data"], "enabled": True,
                              "version": 1, "description": ""})
    tech(db)
    run(db, "r1", 2)
    assessment(db, "r1", 2, pages=[page(db, "a", 1)])
    for header, expected in [({"X-Time-Zone": "Asia/Kolkata"}, "Asia/Kolkata"),
                             ({"X-Time-Zone": "nowhere"}, "America/Chicago"), ({}, "America/Chicago")]:
        body = client.post("/api/scoring/runs/r1/pov/edge-ai", headers=header).json()
        assert body["composed_tz"] == expected
