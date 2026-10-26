"""Every API call is checked: open, the person's own, a leader's, or the
radar team's. The walk covers every route, so a new one can't slip through."""

import asyncio
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import accounts, auth

pytestmark = pytest.mark.real_sign_in


def _client(db, email, role):
    accounts.add(email, role.title(), role, "Right pass 1", None)
    db["accounts"].update_one({"_id": email}, {"$set": {"must_change": False}})
    c = TestClient(app)
    assert c.post("/api/auth/sign-in", json={"email": email, "password": "Right pass 1"}).status_code == 200
    return c


def _calls():
    """Every API route and method (from the app's own route table, as its schema lists it), with a value in
    place of each path parameter."""
    calls = [(method.upper(), re.sub(r"\{[^}]+\}", "x", path))
             for path, methods in app.openapi()["paths"].items() for method in methods]
    assert len(calls) > 100
    return calls


def test_every_route_needs_sign_in_except_the_open_ones(db):
    anyone = TestClient(app)
    for method, path in _calls():
        if (method, path) in auth.OPEN:
            continue
        assert anyone.request(method, path).status_code == 401, (method, path)


def test_a_leader_gets_only_the_leaders_calls(db):
    leader = _client(db, "ankur@example.org", "leader")
    allowed = 0
    for method, path in _calls():
        if (method, path) == ("POST", "/api/auth/sign-out"):
            continue                                                # would end the walk's own session
        status = leader.request(method, path).status_code
        if (method, path) in auth.OPEN | auth.OWN or auth.leader_may(method, path):
            allowed += 1
            assert status not in (401, 403), (method, path, status)
        else:
            assert status == 403, (method, path, status)
    assert allowed >= len(auth.LEADER_CALLS)
    r = leader.get("/api/lists/availability")                     # a sibling of the leaders' mechanisms list
    assert r.status_code == 403 and r.json()["detail"] == auth.TEAM_ONLY
    assert leader.get("/api/lists/mechanisms").status_code == 200


def test_a_forged_role_in_the_cookie_changes_nothing(db):
    leader = _client(db, "ankur@example.org", "leader")
    token = leader.cookies["radar_session"].split(".", 1)[1]
    leader.cookies.set("radar_session", f"admin.{token}")
    assert leader.get("/api/technologies").status_code == 403


def test_an_admin_may_make_every_call(db):
    admin = _client(db, "hasan@example.org", "admin")
    assert admin.get("/api/technologies").status_code == 200
    assert admin.get("/api/accounts").status_code == 200


def test_a_slow_session_read_doesnt_hold_up_other_calls(db, monkeypatch):
    real = auth.session_for

    def slow(token):
        time.sleep(1.0)  # blocking, as a slow database read would be
        return real(token)
    monkeypatch.setattr(auth, "session_for", slow)

    async def both():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.cookies.set("radar_session", "admin.anything")
            slow_call = asyncio.create_task(c.get("/api/technologies"))
            await asyncio.sleep(0.1)
            started = time.monotonic()
            health = await c.get("/api/health")
            took = time.monotonic() - started
            assert (await slow_call).status_code == 401
            return health.status_code, took
    status, took = asyncio.run(both())
    assert status == 200 and took < 0.5
