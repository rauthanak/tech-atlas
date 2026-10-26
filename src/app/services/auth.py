"""Signing in, and the one check every API call goes through (`guard`).

A session is a random token: the browser keeps it in the `radar_session`
cookie (HttpOnly, as `<role>.<token>`: the role is only a hint for the
portal's landing page), and `sessions` keeps its SHA-256 with the person and
their role. A session lasts 12 hours from sign-in. The API reads the role from
the session, never from the cookie.

`guard` lets through the two open calls (health, sign-in, and sign-out, which
works even with an old cookie), then needs a session; a password to change
allows only the person's own calls; a leader may make only the calls the
leaders' view makes; an admin may make every call. The person is kept for the
call in CURRENT, so what they save can say who made it (`by()`)."""

import hashlib
import re
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from app.services import accounts
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc
from app.settings import get_settings

SESSION_HOURS = 12
TRIES = 5
PAUSE_MINUTES = 15
COOKIE = "radar_session"

WRONG = "That email and password don't match."
PAUSED = f"Too many wrong passwords. Try again in {PAUSE_MINUTES} minutes, or ask a radar admin."
OFF = "This account is switched off. Ask a radar admin."
SIGN_IN = "Sign in to continue."
CHANGE_FIRST = "Choose a new password first."
TEAM_ONLY = "This is for the radar team."
WRONG_CURRENT = "Your current password isn't right."
SAME = "Choose a password different from the one you have."

# the signed-in session for this call (None: no one, as in a test, the command line or the radar's own work)
CURRENT: ContextVar[dict | None] = ContextVar("signed_in", default=None)

OPEN = {("GET", "/api/health"), ("POST", "/api/auth/sign-in"), ("POST", "/api/auth/sign-out")}
OWN = {("GET", "/api/auth/me"), ("POST", "/api/auth/password")}
# what the leaders' view calls (moved here from the portal's proxy.ts): the grid, a Point of View as the
# published edition holds it, the names beside its text, and "a leader opened or printed it"
LEADER_CALLS = [
    ("GET", re.compile(r"^/api/frontier$")),
    ("GET", re.compile(r"^/api/frontier/pov/[\w.~-]+$")),
    ("GET", re.compile(r"^/api/scoring/fabrics$")),
    ("GET", re.compile(r"^/api/lists/mechanisms$")),
    ("GET", re.compile(r"^/api/technologies/labels$")),
    ("POST", re.compile(r"^/api/frontier/pov/[\w.~-]+/seen$")),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sid(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def cookie(value: str, max_age: int) -> str:
    """The Set-Cookie header for the session (an empty value and 0 clear it)."""
    secure = "; Secure" if get_settings().secure_cookies else ""
    return f"{COOKIE}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=Lax{secure}"


def token_of(request: Request) -> str | None:
    _, _, token = (request.cookies.get(COOKIE) or "").partition(".")
    return token or None


def me(s: dict) -> dict:
    return {k: s[k] for k in ("email", "name", "role", "must_change")}


# ── sign in, out, change password ────────────────────────────────────

def sign_in(email: str, password: str) -> tuple[str, dict]:
    """The new session's token and record. A wrong email or password says the
    same either way; 5 wrong in a row pause the account for 15 minutes."""
    coll = get_collection("accounts")
    a = accounts.find(email)
    now = _now()
    if a and a.get("paused_until") and datetime.fromisoformat(a["paused_until"]) > now:
        raise HTTPException(status_code=429, detail=PAUSED)
    if a is None or not accounts.check_password(password, a.get("password_hash")):
        if a:
            tries = coll.find_one_and_update({"_id": a["_id"]}, {"$inc": {"wrong_tries": 1}},
                                             return_document=True)["wrong_tries"]
            if tries >= TRIES:
                coll.update_one({"_id": a["_id"]}, {"$set": {
                    "wrong_tries": 0, "paused_until": (now + timedelta(minutes=PAUSE_MINUTES)).isoformat()}})
                raise HTTPException(status_code=429, detail=PAUSED)
        raise HTTPException(status_code=400, detail=WRONG)
    if a.get("disabled"):
        raise HTTPException(status_code=403, detail=OFF)
    coll.update_one({"_id": a["_id"]}, {"$set": {"wrong_tries": 0, "paused_until": None, "last_signed_in": now_utc()}})
    token = secrets.token_urlsafe(32)
    session = {"_id": _sid(token), "email": a["_id"], "name": a["name"], "role": a["role"],
               "must_change": bool(a.get("must_change")), "at": now_utc(),
               "expires_at": now + timedelta(hours=SESSION_HOURS)}  # a date, so MongoDB's TTL clean-up can read it
    get_collection("sessions").insert_one(session)
    return token, session


def session_for(token: str) -> dict | None:
    s = get_collection("sessions").find_one({"_id": _sid(token)})
    if s is None:
        return None
    ends = s["expires_at"] if s["expires_at"].tzinfo else s["expires_at"].replace(tzinfo=timezone.utc)
    return s if ends > _now() else None


def sign_out(token: str) -> None:
    get_collection("sessions").delete_one({"_id": _sid(token)})


def change_password(s: dict, current: str, new: str) -> dict:
    """The person's own change: this session stays, every other one ends."""
    a = accounts.find(s["email"])
    if a is None or not accounts.check_password(current, a.get("password_hash")):
        raise HTTPException(status_code=400, detail=WRONG_CURRENT)
    if len(new) < accounts.MIN_LENGTH:
        raise HTTPException(status_code=422, detail=accounts.SHORT)
    if new == current:
        raise HTTPException(status_code=422, detail=SAME)
    get_collection("accounts").update_one({"_id": a["_id"]}, {"$set": {
        "password_hash": accounts.hash_password(new), "must_change": False, "password_set_at": now_utc()}})
    accounts.sign_out_everywhere(a["_id"], keep=s["_id"])
    get_collection("sessions").update_one({"_id": s["_id"]}, {"$set": {"must_change": False}})
    return me({**s, "must_change": False})


# ── the check on every call ──────────────────────────────────────────

def leader_may(method: str, path: str) -> bool:
    return any(m == method and pattern.match(path) for m, pattern in LEADER_CALLS)


async def guard(request: Request) -> None:
    """Added to the whole API (main.create_app), so no endpoint can be left out.
    Async, so the person it sets reaches the endpoint; its database read runs in
    the threadpool, so the loop every request shares never waits on it."""
    method, path = request.method, request.url.path
    if (method, path) in OPEN:
        return
    token = token_of(request)
    s = await run_in_threadpool(session_for, token) if token else None
    if s is None:
        raise HTTPException(status_code=401, detail=SIGN_IN, headers={"set-cookie": cookie("", 0)})
    if s["must_change"] and (method, path) not in OWN:
        raise HTTPException(status_code=403, detail=CHANGE_FIRST)
    if s["role"] != "admin" and (method, path) not in OWN and not leader_may(method, path):
        raise HTTPException(status_code=403, detail=TEAM_ONLY)
    CURRENT.set(s)


# ── who did it ───────────────────────────────────────────────────────

def by() -> dict | None:
    """Who is making this call, as saved records say it ("made by"); None when no one is."""
    s = CURRENT.get()
    return {"email": s["email"], "name": s["name"]} if s else None


def role() -> str | None:
    s = CURRENT.get()
    return s.get("role") if s else None


@contextmanager
def acting_as(person: dict | None):
    """A background job records the person who started it (services/jobs)."""
    token = CURRENT.set({**person, "role": None} if person else None)
    try:
        yield
    finally:
        CURRENT.reset(token)
