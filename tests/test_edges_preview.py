"""Weights & Grid › Save the edges says first what would move: each
technology's latest assessment in each fabric, placed with today's edges and
with the new ones, by arithmetic."""

from fastapi.testclient import TestClient

from app.main import app
from stacked_fakes import load_seeded

client = TestClient(app)


def _assessed(db, tech: str, soon: float, big: float, at: str, fabric: str = "cloud") -> None:
    db["assessments"].insert_one({"_id": f"{tech}-{fabric}-{at}", "tech_id": tech, "fabric_id": fabric, "created_at": at,
                                  "placement": {"timeline": {"score": soon}, "potential": {"score": big}}})


def test_preview_counts_moves_on_the_latest_assessment(db):
    load_seeded(db, "scoring_config")
    _assessed(db, "a", 7.5, 7.5, "2026-10-20")   # near × high
    _assessed(db, "b", 6.5, 7.5, "2026-10-20")   # mid × high
    _assessed(db, "b", 1.0, 1.0, "2026-10-01")   # older: ignored
    _assessed(db, "c", 2.0, None, "2026-10-20")  # not placed

    same = client.post("/api/scoring/edges/preview", json={"timeline_cutpoints": [4, 7], "potential_cutpoints": [4, 7]}).json()
    assert same == {"placed": 2, "moves": []}

    grid = db["scoring_config"].find_one({"_id": "priority_grid"})["grid"]
    out = client.post("/api/scoring/edges/preview", json={"timeline_cutpoints": [4, 6], "potential_cutpoints": [4, 7]}).json()
    assert out == {"placed": 2, "moves": [{"from": grid["mid_high"], "to": grid["near_high"], "count": 1}]}
