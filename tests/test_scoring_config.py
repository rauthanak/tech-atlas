"""Scoring settings are checked before they're saved (code review CR11): every
save the portal makes still saves; anything placement couldn't use is refused,
saying why, and nothing changes."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import tech_status
from factories import tech
from stacked_fakes import load_seeded

client = TestClient(app)


def _put(name, body):
    return client.put(f"/api/scoring/config/{name}", json=body)


@pytest.fixture
def config(db):
    load_seeded(db, "scoring_config", "measures")
    return db["scoring_config"]


def test_every_save_the_portal_makes_still_saves(config):
    for name, body in [("tora", {"open_question": None}), ("priority_grid", {"open_question": None}),
                       ("priority_grid", {"timeline_cutpoints": [3.5, 7], "potential_cutpoints": [4, 8]}),
                       ("evidence", {"open_question": None}), ("evidence", {"max_dossier_tokens": 400000}),
                       ("engine", {"mode": "per_measure"}), ("engine", {"mode": "stacked"}),
                       ("horizons", {"open_question": "which band is near?"})]:
        before = config.find_one({"_id": name}).get("version", 0)
        r = _put(name, body)
        assert r.status_code == 200, (name, body, r.json())
        assert config.find_one({"_id": name})["version"] == before + 1


@pytest.mark.parametrize("edges", [[], [7, 4], [4, 11], [4, "7"], [True, 7], [4, 7, 9], "4,7"])
def test_bad_band_edges_are_refused_and_nothing_changes(config, edges):
    before = config.find_one({"_id": "priority_grid"})
    r = _put("priority_grid", {"timeline_cutpoints": edges})
    assert r.status_code == 422 and "the How soon band edges are two numbers from 0 to 10" in r.json()["detail"]
    assert config.find_one({"_id": "priority_grid"}) == before


def test_an_unknown_measure_or_cell_is_refused(config):
    r = _put("priority_grid", {"timeline_from": ["maturity-trl", "nope"]})
    assert r.status_code == 422 and r.json()["detail"] == "unknown measure 'nope' in How soon"
    grid = dict(config.find_one({"_id": "priority_grid"})["grid"], near_high="P9")
    assert _put("priority_grid", {"grid": grid}).status_code == 422


@pytest.mark.parametrize("tokens", [0, -1, 1.5, "500000", True])
def test_the_token_limit_is_a_whole_number_above_zero(config, tokens):
    r = _put("evidence", {"max_dossier_tokens": tokens})
    assert r.status_code == 422 and "a whole number of tokens above 0" in r.json()["detail"]


def test_the_engine_mode_is_one_of_two(config):
    assert _put("engine", {"mode": "fast"}).status_code == 422


def test_an_unknown_setting_is_refused(config):
    r = _put("priority_grid", {"cutpoints": [4, 7]})
    assert r.status_code == 422 and r.json()["detail"] == "'cutpoints' isn't a setting of priority_grid"
    assert _put("nothing", {"open_question": None}).status_code == 404


def test_a_refused_save_marks_no_technology(config, db):
    load_seeded(db, "availability", "domains", "subdomains", "trl_levels", "settings")
    tech(db)
    tech_status.refresh(["edge-ai"])
    assert _put("priority_grid", {"timeline_cutpoints": []}).status_code == 422
    assert tech_status.pending() == 0
