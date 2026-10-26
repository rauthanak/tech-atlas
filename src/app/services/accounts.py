"""Who may sign in: one record per person in `accounts`, its _id the email in
lower case, with a name, a role (admin or leader) and the password only as a
slow salted hash (PBKDF2-SHA256, Python's own hashlib). No sign-up: the first
accounts come from seeds/accounts.json, once, and admins add the rest on
Setup › People. A seeded or temporary password must be changed at the next
sign-in (`must_change`).

From the server (docker compose exec atlas python -m app.services.accounts ...):
  hash                  asks for a password and prints its hash, for seeds/accounts.json
  set-password <email>  sets a temporary password, as Setup › People does (for the day no admin can sign in)"""

import getpass
import hashlib
import hmac
import json
import os
import sys

from fastapi import HTTPException

from app.services.db import seeding
from app.services.db.mongo import get_collection
from app.services.timezone import now_utc

ITERATIONS = 600_000
MIN_LENGTH = 8
ROLES = ("admin", "leader")
SHORT = f"A password needs at least {MIN_LENGTH} characters."


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    """True when `password` makes `stored`. Anything that isn't a hash of this
    form (the seed file's placeholder) simply doesn't match."""
    try:
        scheme, iterations, salt, want = (stored or "").split("$")
        if scheme != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


def key(email: str) -> str:
    """An account's id: `Ankur.Jindal@` and `ankur.jindal@` are one person."""
    return (email or "").strip().lower()


def find(email: str) -> dict | None:
    return get_collection("accounts").find_one({"_id": key(email)})


def sign_out_everywhere(email: str, keep: str | None = None) -> None:
    """Delete the person's sessions (all of them, or all but `keep`, a session id)."""
    query: dict = {"email": key(email)}
    if keep:
        query["_id"] = {"$ne": keep}
    get_collection("sessions").delete_many(query)


def _new(email: str, name: str, role: str, password_hash: str, by: dict | None) -> dict:
    now = now_utc()
    return {"_id": key(email), "name": name.strip(), "role": role, "password_hash": password_hash,
            "must_change": True, "disabled": False, "wrong_tries": 0, "paused_until": None,
            "last_signed_in": None, "created_at": now, "created_by": by, "password_set_at": now}


# ── the first accounts ───────────────────────────────────────────────

def seed_if_empty() -> int:
    """At start-up: when no account exists yet, create the ones in
    seeds/accounts.json. Once only, so People edits are never overwritten;
    not part of Setup › Changes."""
    accounts = get_collection("accounts")
    if accounts.estimated_document_count():
        return 0
    path = seeding.SEEDS_DIR / "accounts.json"
    if not path.exists():
        return 0
    docs = [_new(a["email"], a["name"], a["role"], a["password_hash"], None)
            for a in json.loads(path.read_text())["accounts"]]
    if docs:
        accounts.insert_many(docs)
    return len(docs)


# ── Setup › People ───────────────────────────────────────────────────

def public(a: dict) -> dict:
    """An account as the People screen shows it: never its hash."""
    return {"email": a["_id"], "name": a["name"], "role": a["role"], "must_change": bool(a.get("must_change")),
            "disabled": bool(a.get("disabled")), "paused_until": a.get("paused_until"),
            "last_signed_in": a.get("last_signed_in"), "created_at": a.get("created_at"),
            "created_by": (a.get("created_by") or {}).get("name")}  # None: from the starting setup


def everyone() -> list[dict]:
    return [public(a) for a in get_collection("accounts").find().sort("name", 1)]


def _role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(status_code=422, detail=f"A role is admin or leader, not {role!r}.")


def add(email: str, name: str, role: str, password: str, by: dict | None) -> dict:
    email = key(email)
    if "@" not in email or not name.strip():
        raise HTTPException(status_code=422, detail="A person needs a name and an email address.")
    _role(role)
    if len(password) < MIN_LENGTH:
        raise HTTPException(status_code=422, detail=SHORT)
    if find(email):
        raise HTTPException(status_code=409, detail=f"{email} already has an account.")
    doc = _new(email, name, role, hash_password(password), by)
    get_collection("accounts").insert_one(doc)
    return public(doc)


def update(email: str, changes: dict, me: str) -> dict:
    """Name, role or switched off. A new role or a switch-off signs the person
    out, so it takes effect at once; nobody can change their own role or switch
    themselves off."""
    a = find(email)
    if a is None:
        raise HTTPException(status_code=404, detail=f"No account {key(email)}.")
    if not changes:
        return public(a)
    if a["_id"] == key(me) and (("role" in changes and changes["role"] != a["role"]) or changes.get("disabled")):
        raise HTTPException(status_code=422, detail="You can't change your own role or switch yourself off: "
                                                    "ask another admin.")
    if "role" in changes:
        _role(changes["role"])
    if "name" in changes and not (changes["name"] or "").strip():
        raise HTTPException(status_code=422, detail="A person needs a name.")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    get_collection("accounts").update_one({"_id": a["_id"]}, {"$set": changes})
    if set(changes) == {"name"}:  # only the name: their open sessions say "made by" with the new one
        get_collection("sessions").update_many({"email": a["_id"]}, {"$set": {"name": changes["name"]}})
    else:
        sign_out_everywhere(a["_id"])
    return public({**a, **changes})


def set_temporary(email: str, password: str) -> dict:
    """A temporary password, changed at the next sign-in; the pause is lifted
    and the person is signed out everywhere."""
    a = find(email)
    if a is None:
        raise HTTPException(status_code=404, detail=f"No account {key(email)}.")
    if len(password) < MIN_LENGTH:
        raise HTTPException(status_code=422, detail=SHORT)
    changes = {"password_hash": hash_password(password), "must_change": True, "wrong_tries": 0,
               "paused_until": None, "password_set_at": now_utc()}
    get_collection("accounts").update_one({"_id": a["_id"]}, {"$set": changes})
    sign_out_everywhere(a["_id"])
    return public({**a, **changes})


# ── from the server ──────────────────────────────────────────────────

def _ask() -> str:
    password = getpass.getpass("Password: ")
    if getpass.getpass("Again: ") != password:
        sys.exit("The two didn't match: nothing was changed.")
    if len(password) < MIN_LENGTH:
        sys.exit(SHORT)
    return password


def main(argv: list[str]) -> None:
    if argv[:1] == ["hash"]:
        print(hash_password(_ask()))
    elif argv[:1] == ["set-password"] and len(argv) == 2:
        try:
            a = set_temporary(argv[1], _ask())
        except HTTPException as exc:
            sys.exit(exc.detail)
        print(f"{a['name']} ({a['email']}) has a temporary password: they choose a new one when they sign in.")
    else:
        sys.exit(__doc__.split("From the server")[1].strip())


if __name__ == "__main__":
    main(sys.argv[1:])
