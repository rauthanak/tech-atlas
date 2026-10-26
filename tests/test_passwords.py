"""Passwords are kept only as slow salted hashes (PBKDF2-SHA256)."""

from app.services import accounts


def test_a_hash_checks_its_own_password_only():
    h = accounts.hash_password("Correct horse 1")
    assert accounts.check_password("Correct horse 1", h)
    assert not accounts.check_password("correct horse 1", h)
    assert not accounts.check_password("", h)


def test_each_hash_has_its_own_salt_and_never_holds_the_password():
    a, b = accounts.hash_password("Same words 1"), accounts.hash_password("Same words 1")
    assert a != b and a.startswith("pbkdf2_sha256$1000$")
    assert "Same words" not in a


def test_a_hash_records_its_rounds_so_older_ones_still_check(monkeypatch):
    h = accounts.hash_password("Kept 12345")
    monkeypatch.setattr(accounts, "ITERATIONS", 2000)
    assert accounts.check_password("Kept 12345", h)


def test_anything_that_isnt_a_hash_never_matches_and_never_raises():
    for stored in ("not-set", "", None, "pbkdf2_sha256$x$y$z", "md5$1$aa$bb", "pbkdf2_sha256$10$zz$00"):
        assert accounts.check_password("not-set", stored) is False
