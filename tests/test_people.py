"""Setup › People: admins add people, change roles, switch accounts off and
set temporary passwords. Any change signs the person out; nobody can change
their own role or switch themselves off."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import accounts

pytestmark = pytest.mark.real_sign_in


def _signed_in(db, email, role="admin", password="Right pass 1"):
    if not accounts.find(email):
        accounts.add(email, email.split("@")[0].title(), role, password, None)
        db["accounts"].update_one({"_id": email}, {"$set": {"must_change": False}})
    c = TestClient(app)
    assert c.post("/api/auth/sign-in", json={"email": email, "password": password}).status_code == 200
    return c


def test_add_a_person_who_must_choose_a_password(db):
    admin = _signed_in(db, "hasan@example.org")
    r = admin.post("/api/accounts", json={"email": "Ankur@Example.org", "name": "Ankur Jindal", "role": "leader",
                                          "password": "Temporary 1"})
    assert r.status_code == 200 and r.json()["email"] == "ankur@example.org" and r.json()["must_change"]
    assert "password_hash" not in r.json()
    made = db["accounts"].find_one({"_id": "ankur@example.org"})
    assert made["created_by"] == {"email": "hasan@example.org", "name": "Hasan"}
    assert r.json()["created_by"] == "Hasan"                         # the People screen says who added them
    listed = admin.get("/api/accounts").json()["accounts"]
    assert {a["email"] for a in listed} == {"hasan@example.org", "ankur@example.org"}
    assert all("password_hash" not in a for a in listed)


def test_adding_refuses_a_duplicate_a_short_password_and_a_bad_role(db):
    admin = _signed_in(db, "hasan@example.org")
    base = {"email": "hasan@example.org", "name": "Again", "role": "admin", "password": "Temporary 1"}
    assert admin.post("/api/accounts", json=base).status_code == 409
    assert admin.post("/api/accounts", json={**base, "email": "n@example.org", "password": "short"}).status_code == 422
    assert admin.post("/api/accounts", json={**base, "email": "n@example.org", "role": "owner"}).status_code == 422
    assert admin.post("/api/accounts", json={**base, "email": "no-at-sign"}).status_code == 422


def test_a_role_change_or_a_switch_off_signs_the_person_out(db):
    admin = _signed_in(db, "hasan@example.org")
    ankur = _signed_in(db, "ankur@example.org", role="leader")
    assert admin.put("/api/accounts/ankur@example.org", json={"role": "admin"}).json()["role"] == "admin"
    assert ankur.get("/api/auth/me").status_code == 401
    ankur = _signed_in(db, "ankur@example.org")
    assert ankur.get("/api/technologies").status_code == 200       # signed in again: now an admin
    assert admin.put("/api/accounts/ankur@example.org", json={"disabled": True}).json()["disabled"]
    assert ankur.get("/api/auth/me").status_code == 401
    r = TestClient(app).post("/api/auth/sign-in", json={"email": "ankur@example.org", "password": "Right pass 1"})
    assert r.status_code == 403
    admin.put("/api/accounts/ankur@example.org", json={"disabled": False})
    assert _signed_in(db, "ankur@example.org")


def test_nobody_can_change_their_own_role_or_switch_themselves_off(db):
    admin = _signed_in(db, "hasan@example.org")
    for change in ({"role": "leader"}, {"disabled": True}):
        r = admin.put("/api/accounts/hasan@example.org", json=change)
        assert r.status_code == 422 and "ask another admin" in r.json()["detail"]
    assert admin.put("/api/accounts/hasan@example.org", json={"name": "Hasan Pasha"}).json()["name"] == "Hasan Pasha"
    assert admin.put("/api/accounts/hasan@example.org", json={}).status_code == 200


def test_a_temporary_password_must_be_changed_and_lifts_the_pause(db):
    admin = _signed_in(db, "hasan@example.org")
    _signed_in(db, "ankur@example.org", role="leader")
    db["accounts"].update_one({"_id": "ankur@example.org"}, {"$set": {"wrong_tries": 3,
                                                                     "paused_until": "2099-01-01T00:00:00+00:00"}})
    r = admin.post("/api/accounts/ankur@example.org/password", json={"password": "Temporary 2"})
    assert r.status_code == 200 and r.json()["must_change"] and r.json()["paused_until"] is None
    assert db["sessions"].count_documents({"email": "ankur@example.org"}) == 0
    ankur = _signed_in(db, "ankur@example.org", password="Temporary 2")
    assert ankur.get("/api/frontier").status_code == 403           # a new password first
    assert admin.post("/api/accounts/nobody@example.org/password", json={"password": "Temporary 2"}).status_code == 404


def test_a_leader_cant_reach_people(db):
    leader = _signed_in(db, "ankur@example.org", role="leader")
    assert leader.get("/api/accounts").status_code == 403
    assert leader.post("/api/accounts", json={"email": "x@example.org", "name": "X", "role": "admin",
                                              "password": "Temporary 1"}).status_code == 403


def test_a_new_name_keeps_the_person_signed_in(db):
    admin = _signed_in(db, "hasan@example.org")
    ankur = _signed_in(db, "ankur@example.org", role="leader")
    admin.put("/api/accounts/ankur@example.org", json={"name": "Ankur Jindal"})
    assert ankur.get("/api/auth/me").json()["name"] == "Ankur Jindal"
