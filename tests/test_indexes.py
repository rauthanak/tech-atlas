"""Every index lives in seeds/indexes.json: the upkeep creates the missing
ones and never drops one, so a fresh install and the live database match."""

from app.services.db import bootstrap
from app.services.db.mongo import COLLECTIONS


def _keys(info: dict) -> list[list]:
    return [[field, int(direction)] for field, direction in info["key"]]


def test_every_declared_index_is_created_and_an_extra_one_is_kept(db, caplog):
    db["documents"].create_index([("title", 1)])          # one the file doesn't list
    bootstrap.ensure_database()
    bootstrap.ensure_indexes()
    for ix in bootstrap.declared_indexes():
        assert ix["collection"] in COLLECTIONS, ix
        made = [_keys(info) for info in db[ix["collection"]].index_information().values()]
        assert ix["keys"] in made, ix
    assert any("title" in str(info["key"]) for info in db["documents"].index_information().values())
    assert "isn't in seeds/indexes.json (kept)" in caplog.text


def test_it_runs_again_without_change(db):
    bootstrap.ensure_database()
    bootstrap.ensure_indexes()
    before = {c: sorted(db[c].index_information()) for c in COLLECTIONS}
    bootstrap.ensure_database()
    bootstrap.ensure_indexes()
    assert {c: sorted(db[c].index_information()) for c in COLLECTIONS} == before


def test_each_index_says_what_it_is_for():
    assert all(ix.get("why") for ix in bootstrap.declared_indexes())


def test_start_up_does_not_wait_for_indexes(db):
    """The API answers at once: the upkeep (services/jobs.upkeep) builds them in the background."""
    bootstrap.ensure_database()
    assert list(db["documents"].index_information()) == ["_id_"]
