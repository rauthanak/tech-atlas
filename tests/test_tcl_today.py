"""Each fabric's TCL-today profile: editable like its definition, and given
to the scorer, so the measures about TCL's own position can be judged."""

from fastapi.testclient import TestClient

from agent.analyzer import engine
from app.main import app
from app.services.db import seeding

client = TestClient(app)  # no lifespan: nothing is seeded


def test_a_fabric_keeps_its_tcl_today_profile(db):
    db["fabrics"].insert_one({"_id": "media", "name": "Media", "definition": "d", "enabled": True})
    edit = {"name": "Media", "definition": "d", "tcl_today": "Media Fabric: video CDN. Source: https://x", "enabled": True}
    assert client.put("/api/scoring/fabrics/media", json=edit).status_code == 200
    assert db["fabrics"].find_one({"_id": "media"})["tcl_today"] == edit["tcl_today"]


def test_the_scorer_is_given_tcl_today(db, monkeypatch):
    skill = next(s for s in seeding.read_list("prompts") if s["name"] == "measure_scoring")
    db["prompts"].insert_one({**skill, "_id": skill["name"]})
    sent = []
    monkeypatch.setattr(engine, "_ask_json", lambda llm, prompt, run_id: sent.append(prompt) or None)
    measure = {"code": "S2", "name": "Portfolio adjacency", "definition": "d", "anchors": {"low": "l", "mid": "m", "high": "h"},
               "required_evidence": "r"}
    engine._score_measure(None, "run", measure, "edge ai", {"name": "Network", "definition": "nd",
                          "tcl_today": "IZO: 1,500+ PoPs. Source: https://www.tatacommunications.com/izo"}, "evidence")
    assert "IZO: 1,500+ PoPs" in sent[0] and "TCL TODAY IN THIS FABRIC" in sent[0]
    engine._score_measure(None, "run", measure, "edge ai", {"name": "Network", "definition": "nd"}, "evidence")
    assert "Not described." in sent[1]  # a fabric without a profile still renders
