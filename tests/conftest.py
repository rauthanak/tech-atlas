"""Tests run against a throwaway database on the local MongoDB, never the
real one: MONGO_DB is pinned before the app's settings are first read.
TEST_MONGO_DB gives a separate throwaway database (tech_atlas_test_<name>),
so test runs side by side don't share one."""

import os

os.environ["MONGO_DB"] = os.environ.get("TEST_MONGO_DB", "tech_atlas_test")
os.environ["MONGO_URI"] = os.environ.get("TEST_MONGO_URI", "mongodb://127.0.0.1:27017")

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from app.services.db import seeding  # noqa: E402
from app.services.db.mongo import get_db  # noqa: E402


@pytest.fixture
def db():
    database = get_db()
    assert database.name.startswith("tech_atlas_test")
    database.client.drop_database(database.name)
    yield database
    database.client.drop_database(database.name)


@pytest.fixture
def seeds(tmp_path, monkeypatch) -> Path:
    """A private copy of seeds/, so tests can write seed files freely."""
    copy = tmp_path / "seeds"
    shutil.copytree(seeding.SEEDS_DIR, copy)
    monkeypatch.setattr(seeding, "SEEDS_DIR", copy)
    return copy


@pytest.fixture(autouse=True)
def stored_answers_always_fresh(monkeypatch):
    """Tests write straight to the database, with no background updater:
    screens work out every technology's stored answers, and polled answers,
    on each read."""
    from app.api import pipeline
    from app.services import briefing_days, editions, tech_status
    monkeypatch.setattr(tech_status, "ALWAYS_FRESH", True)
    monkeypatch.setattr(briefing_days, "ALWAYS_NOW", True)  # the Briefing's changed days, worked out on each read
    monkeypatch.setattr(pipeline, "CACHE_S", 0)   # each read works its answer out again
    monkeypatch.setattr(editions, "SINCE_S", 0)


@pytest.fixture(autouse=True)
def quick_password_hashes(monkeypatch):
    """Real hashes, fewer rounds: the suite stays fast (a hash records its own rounds, so checks still work)."""
    from app.services import accounts
    monkeypatch.setattr(accounts, "ITERATIONS", 1000)


# every test call is made as this admin, so each test tests what it did before sign-in; the sign-in tests
# use the real check instead (@pytest.mark.real_sign_in)
TEST_ADMIN = {"_id": "test-session", "email": "admin@test.example", "name": "Test admin", "role": "admin",
              "must_change": False}


def pytest_configure(config):
    config.addinivalue_line("markers", "real_sign_in: run the real sign-in check, not the test admin")


@pytest.fixture(autouse=True)
def signed_in_as_admin(request):
    from app.main import app
    from app.services import auth
    if request.node.get_closest_marker("real_sign_in"):
        yield
        return

    async def as_admin():
        auth.CURRENT.set(TEST_ADMIN)
    app.dependency_overrides[auth.guard] = as_admin
    yield
    app.dependency_overrides.pop(auth.guard, None)


@pytest.fixture
def call_as():
    """call_as("leader") makes the test's next calls as a leader; call_as("admin") goes back."""
    from app.main import app
    from app.services import auth

    def switch(role: str):
        person = TEST_ADMIN if role == "admin" else {**TEST_ADMIN, "email": f"{role}@test.example",
                                                     "name": f"Test {role}", "role": role}

        async def as_person():
            auth.CURRENT.set(person)
        app.dependency_overrides[auth.guard] = as_person
    return switch
