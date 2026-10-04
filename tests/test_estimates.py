"""Cost estimates shown before anything starts: model calls for an
assessment, and what a collection would cover."""

from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings

client = TestClient(app)  # no lifespan: nothing is seeded


def _scoring_setup(db) -> None:
    db["measures"].insert_many([{"_id": f"m{i}"} for i in range(3)])
    db["fabrics"].insert_many([{"_id": "network", "enabled": True},
                               {"_id": "cloud", "enabled": True},
                               {"_id": "iot", "enabled": False}])
    db["technologies"].insert_many([{"_id": "a", "name": "a", "enabled": True, "doc_count": 5},
                                    {"_id": "b", "name": "b", "enabled": True, "doc_count": 1},
                                    {"_id": "c", "name": "c", "enabled": False, "doc_count": 9}])


def test_the_last_recorded_gate_sets_the_estimate(db):
    _scoring_setup(db)
    db["scoring_runs"].insert_many([
        {"_id": "old", "started_at": "2026-09-01", "gates": {"a": ["network", "cloud"]}},
        {"_id": "new", "started_at": "2026-09-02", "gates": {"a": ["cloud", "iot"]}}])  # iot is off now
    body = client.get("/api/scoring/preview", params={"min_docs": 3}).json()
    # gate + 3 measures in 1 fabric + watch metrics = 5; at most 2 + 3 x 2 fabrics = 8
    assert body == {"technologies": 1, "calls": 5, "calls_max": 8}


def test_without_a_gate_every_enabled_fabric_counts(db):
    _scoring_setup(db)
    body = client.get("/api/scoring/preview").json()
    assert body == {"technologies": 2, "calls": 16, "calls_max": 16}  # a and b; c is switched off


def test_an_estimate_for_a_list_of_ids(db):
    _scoring_setup(db)
    db["scoring_runs"].insert_one({"_id": "r", "started_at": "2026-09-01", "gates": {"b": ["network"]}})
    body = client.get("/api/scoring/preview", params={"technologies": "b,c"}).json()
    assert body == {"technologies": 1, "calls": 5, "calls_max": 8}


def test_the_collection_preview_counts_only_sources_a_run_collects(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "include_paid_sources", False)
    db["settings"].insert_one({"_id": "crawl", "pages_per_source": 25})
    db["sources"].insert_many([
        {"_id": "w1", "enabled": True, "access": "crawl", "cost": "free"},
        {"_id": "w2", "enabled": True, "access": "crawl", "cost": "licensed"},  # paid: left out
        {"_id": "w3", "enabled": False, "access": "crawl", "cost": "free"},     # switched off
        {"_id": "n", "enabled": True, "access": "none", "cost": "free"},        # never collected
        {"_id": "q", "enabled": True, "access": "query", "cost": "free_tier"}])
    assert client.get("/api/runs/preview").json() == {
        "websites": 1, "data_sources": 1, "pages_per_source": 25}  # from Crawl settings


def test_an_empty_list_of_technologies_starts_nothing(db):
    _scoring_setup(db)
    # [] used to fall through to every enabled technology
    response = client.post("/api/scoring/runs", json={"technologies": []})
    assert response.status_code == 422 and "at least 1" in response.text
    assert db["scoring_runs"].count_documents({}) == 0
