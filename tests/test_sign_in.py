"""Signing in, out and changing a password, through the real check on every
call (services/auth). A wrong email or password says the same either way and
is a 400: only "not signed in" is a 401."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import accounts, auth

pytestmark = pytest.mark.real_sign_in


def person(db, email="hasan@example.org", role="admin", password="Right pass 1", must_change=False, **extra):
    accounts.add(email, email.split("@")[0].title(), role, password, None)
    db["accounts"].update_one({"_id": email}, {"$set": {"must_change": must_change, **extra}})


def signed_in(email="hasan@example.org", password="Right pass 1") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/sign-in", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_sign_in_sets_the_session_cookie_and_answers_who(db):
    person(db)
    c = TestClient(app)
    r = c.post("/api/auth/sign-in", json={"email": "Hasan@Example.org ", "password": "Right pass 1"})
    assert r.status_code == 200
    assert r.json() == {"email": "hasan@example.org", "name": "Hasan", "role": "admin", "must_change": False}
    header = r.headers["set-cookie"]
    assert header.startswith("radar_session=admin.") and "HttpOnly" in header and "SameSite=Lax" in header
    assert "Max-Age=43200" in header and "Secure" not in header
    assert c.get("/api/auth/me").json()["email"] == "hasan@example.org"
    s = db["sessions"].find_one()
    assert isinstance(s["expires_at"], dt.datetime)              # a date, for the TTL clean-up
    token = c.cookies["radar_session"].split(".", 1)[1]
    assert token not in str(s)                                     # only its hash is stored
    assert db["accounts"].find_one()["last_signed_in"]


def test_secure_cookies_when_set(db, monkeypatch):
    person(db)
    monkeypatch.setattr(auth.get_settings(), "secure_cookies", True)
    r = TestClient(app).post("/api/auth/sign-in", json={"email": "hasan@example.org", "password": "Right pass 1"})
    assert "; Secure" in r.headers["set-cookie"]


def test_wrong_email_or_password_say_the_same_and_are_not_a_401(db):
    person(db)
    c = TestClient(app)
    wrong_pw = c.post("/api/auth/sign-in", json={"email": "hasan@example.org", "password": "nope nope"})
    no_one = c.post("/api/auth/sign-in", json={"email": "nobody@example.org", "password": "nope nope"})
    assert wrong_pw.status_code == no_one.status_code == 400
    assert wrong_pw.json() == no_one.json() == {"detail": auth.WRONG}


def test_five_wrong_in_a_row_pause_the_account_and_a_right_one_resets(db):
    person(db)
    c = TestClient(app)
    for _ in range(3):
        c.post("/api/auth/sign-in", json={"email": "hasan@example.org", "password": "wrong one"})
    signed_in()
    assert db["accounts"].find_one()["wrong_tries"] == 0
    for n in range(auth.TRIES):
        r = c.post("/api/auth/sign-in", json={"email": "hasan@example.org", "password": "wrong one"})
    assert r.status_code == 429 and r.json()["detail"] == auth.PAUSED
    r = c.post("/api/auth/sign-in", json={"email": "hasan@example.org", "password": "Right pass 1"})
    assert r.status_code == 429                                    # paused, even with the right one
    db["accounts"].update_one({}, {"$set": {"paused_until": "2000-01-01T00:00:00+00:00"}})
    assert signed_in()                                             # the pause is over


def test_a_switched_off_account_is_told_so(db):
    person(db, disabled=True)
    r = TestClient(app).post("/api/auth/sign-in", json={"email": "hasan@example.org", "password": "Right pass 1"})
    assert r.status_code == 403 and r.json()["detail"] == auth.OFF


def test_no_or_an_expired_session_is_a_401_that_clears_the_cookie(db):
    person(db)
    r = TestClient(app).get("/api/technologies")
    assert r.status_code == 401 and r.json()["detail"] == auth.SIGN_IN
    assert "radar_session=;" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    c = signed_in()
    db["sessions"].update_one({}, {"$set": {"expires_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)}})
    assert c.get("/api/technologies").status_code == 401
    c.cookies.set("radar_session", "admin.made-up")                # a forged cookie
    assert c.get("/api/technologies").status_code == 401


def test_sign_out_ends_the_session_and_works_without_one(db):
    person(db)
    c = signed_in()
    r = c.post("/api/auth/sign-out")
    assert r.status_code == 200 and r.json() == {"signed_out": True} and "Max-Age=0" in r.headers["set-cookie"]
    assert db["sessions"].count_documents({}) == 0
    assert TestClient(app).post("/api/auth/sign-out").json() == {"signed_out": True}


def test_a_password_to_change_opens_only_the_own_calls(db):
    person(db, password="Welcome 123", must_change=True)
    c = signed_in(password="Welcome 123")
    assert c.get("/api/auth/me").json()["must_change"] is True
    r = c.get("/api/technologies")
    assert r.status_code == 403 and r.json()["detail"] == auth.CHANGE_FIRST
    r = c.post("/api/auth/password", json={"current": "Welcome 123", "new": "Mine now 12"})
    assert r.status_code == 200 and r.json()["must_change"] is False
    assert c.get("/api/technologies").status_code == 200
    assert not db["accounts"].find_one()["must_change"]


def test_change_password_rules(db):
    person(db)
    c = signed_in()
    wrong = c.post("/api/auth/password", json={"current": "not it", "new": "Mine now 12"})
    assert wrong.status_code == 400 and wrong.json()["detail"] == auth.WRONG_CURRENT   # stays on the form
    assert c.post("/api/auth/password", json={"current": "Right pass 1", "new": "short"}).status_code == 422
    assert c.post("/api/auth/password", json={"current": "Right pass 1", "new": "Right pass 1"}).json()["detail"] == auth.SAME


def test_changing_the_password_signs_out_everywhere_else(db):
    person(db)
    here, elsewhere = signed_in(), signed_in()
    assert here.post("/api/auth/password", json={"current": "Right pass 1", "new": "Mine now 12"}).status_code == 200
    assert here.get("/api/auth/me").status_code == 200
    assert elsewhere.get("/api/auth/me").status_code == 401
    assert signed_in(password="Mine now 12")
