"""The view counter counts leaders only, says which leaders, and starts from
zero: visits from before sign-in (no one named) are kept but not counted."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import editions
from factories import tech

client = TestClient(app)


def _seen(kind="opened", tech_id="edge-ai"):
    assert client.post(f"/api/frontier/pov/{tech_id}/seen", json={"kind": kind}).status_code == 204


def test_an_admin_looking_at_the_leaders_view_isnt_counted(db):
    tech(db, "edge-ai", "edge ai")
    _seen()
    assert db["pov_views"].count_documents({}) == 0
    assert client.get("/api/editions/pov/edge-ai").json()["views"] is None


def test_each_leaders_visits_are_counted_with_their_name(db, call_as):
    tech(db, "edge-ai", "edge ai")
    call_as("leader")
    _seen(), _seen(), _seen("printed")
    v = editions.views(["edge-ai"])["edge-ai"]
    assert (v["opened"], v["printed"]) == (2, 1)
    assert v["leaders"] == [{"name": "Test leader", "opened": 2, "printed": 1, "last_opened": v["last_opened"]}]
    assert db["pov_views"].find_one()["by"] == {"email": "leader@test.example", "name": "Test leader"}


def test_two_leaders_the_most_recent_first(db):
    tech(db, "edge-ai", "edge ai")
    rows = [("a@x.org", "Ankur", "opened", "2026-10-26T10:00:00+00:00"), ("b@x.org", "Bea", "opened", "2026-10-26T11:00:00+00:00"),
            ("a@x.org", "Ankur", "opened", "2026-10-26T09:00:00+00:00")]
    db["pov_views"].insert_many([{"_id": str(n), "tech_id": "edge-ai", "kind": k, "by": {"email": e, "name": name}, "at": at}
                                 for n, (e, name, k, at) in enumerate(rows)])
    v = editions.views(["edge-ai"])["edge-ai"]
    assert v["opened"] == 3 and v["last_opened"] == "2026-10-26T11:00:00+00:00"
    assert [(w["name"], w["opened"]) for w in v["leaders"]] == [("Bea", 1), ("Ankur", 2)]


def test_visits_from_before_sign_in_arent_counted(db):
    tech(db, "edge-ai", "edge ai")
    db["pov_views"].insert_many([{"_id": "old1", "tech_id": "edge-ai", "kind": "opened", "at": "2026-10-20T10:00:00+00:00"},
                                 {"_id": "old2", "tech_id": "edge-ai", "kind": "printed", "at": "2026-10-20T10:01:00+00:00"}])
    assert editions.views(["edge-ai"]) == {}
    assert db["pov_views"].count_documents({}) == 2               # kept, not deleted
