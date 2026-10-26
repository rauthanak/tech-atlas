"""The first accounts come from seeds/accounts.json, once, each with a password
to change at first sign-in; after that, people are managed on Setup › People,
never in Setup › Changes. From the server, set-password sets a temporary one."""

import json

import pytest

from app.services import accounts
from app.services.db import seeding


def _seed_file(seeds, *people):
    (seeds / "accounts.json").write_text(json.dumps({"accounts": [
        {"email": e, "name": n, "role": r, "password_hash": accounts.hash_password("Welcome 123")} for e, n, r in people]}))


def test_the_shipped_file_lists_the_agreed_people():
    shipped = json.loads((seeding.SEEDS_DIR / "accounts.json").read_text())["accounts"]
    roles = {a["email"]: a["role"] for a in shipped}
    assert len(roles) == 9 and list(roles.values()).count("leader") == 2
    assert roles["ankur.jindal@tatacommunications.com"] == roles["rauthanak@gmail.com"] == "leader"
    assert all(a["email"] == a["email"].lower() and a["password_hash"].startswith("pbkdf2_sha256$") for a in shipped)


def test_the_first_start_creates_them_to_change_their_password(db, seeds):
    _seed_file(seeds, ("Hasan@Example.org", "Hasan", "admin"), ("ankur@example.org", "Ankur", "leader"))
    assert accounts.seed_if_empty() == 2
    hasan = db["accounts"].find_one({"_id": "hasan@example.org"})
    assert hasan["must_change"] and hasan["role"] == "admin" and not hasan["disabled"]
    assert accounts.check_password("Welcome 123", hasan["password_hash"])


def test_a_later_start_changes_nothing(db, seeds):
    _seed_file(seeds, ("hasan@example.org", "Hasan", "admin"))
    accounts.seed_if_empty()
    db["accounts"].update_one({"_id": "hasan@example.org"}, {"$set": {"name": "Hasan Pasha"}})
    _seed_file(seeds, ("hasan@example.org", "Hasan", "admin"), ("new@example.org", "New", "leader"))
    assert accounts.seed_if_empty() == 0
    assert db["accounts"].count_documents({}) == 1
    assert db["accounts"].find_one()["name"] == "Hasan Pasha"


def test_accounts_never_show_in_changes(db, seeds):
    seeding.load_if_new()
    _seed_file(seeds, ("hasan@example.org", "Hasan", "admin"))
    accounts.seed_if_empty()
    assert seeding.changes()["count"] == 0
    assert "accounts" not in seeding.ID_FIELDS


def test_a_placeholder_hash_lets_no_one_in(db, seeds):
    (seeds / "accounts.json").write_text(json.dumps({"accounts": [
        {"email": "a@example.org", "name": "A", "role": "admin", "password_hash": "not-set"}]}))
    accounts.seed_if_empty()
    assert not accounts.check_password("not-set", db["accounts"].find_one()["password_hash"])


def test_set_password_from_the_server(db, seeds, monkeypatch, capsys):
    _seed_file(seeds, ("hasan@example.org", "Hasan", "admin"))
    accounts.seed_if_empty()
    db["accounts"].update_one({"_id": "hasan@example.org"}, {"$set": {"must_change": False, "wrong_tries": 5,
                                                                      "paused_until": "2099-01-01T00:00:00+00:00"}})
    db["sessions"].insert_one({"_id": "s1", "email": "hasan@example.org"})
    monkeypatch.setattr(accounts.getpass, "getpass", lambda prompt="": "Temporary 1")
    accounts.main(["set-password", "Hasan@example.org"])
    a = db["accounts"].find_one()
    assert accounts.check_password("Temporary 1", a["password_hash"])
    assert a["must_change"] and a["wrong_tries"] == 0 and a["paused_until"] is None
    assert db["sessions"].count_documents({}) == 0
    assert "has a temporary password" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="No account nobody@example.org"):
        accounts.main(["set-password", "nobody@example.org"])
