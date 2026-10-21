"""The organizer keeps one record per technology: a renamed technology keeps
the id it was created with, and a new name whose id is taken gets a number."""

import json

import pytest

from agent.resolver import resolver
from app.api.technologies import TechEdit, update_technology
from app.services.db import seeding
from app.settings import get_settings


class FakeLLM:
    """Folds "alpha technology" into the name "alpha tech"; merges nothing else."""
    @classmethod
    def initialize(cls, *args, **kwargs):
        return cls()

    def ask(self, prompt, system=None, **kw):
        groups = [{"name": "alpha tech", "members": ["alpha technology"]}] \
            if '"alpha technology"' in prompt else []
        return json.dumps({"groups": groups})


@pytest.fixture
def organizer(db, monkeypatch):
    seeding.load_if_new()                       # the technology_resolve skill
    monkeypatch.setattr(resolver, "LLM", FakeLLM)
    monkeypatch.setattr(get_settings(), "min_docs_per_tech", 1)
    return db


def _pages(db, raw: str, n: int = 2) -> None:
    db["documents"].insert_many([
        {"technologies": [raw], "ignored_by": None, "is_stub": False, "end_url": f"https://x/{raw}/{i}",
         "source_id": "s", "category": "H1", "kind": "article"} for i in range(n)])


def test_a_renamed_technology_stays_one_technology(organizer):
    db = organizer
    _pages(db, "post quantum crypto")
    resolver.run_resolve_sync()
    assert [t["_id"] for t in db["technologies"].find()] == ["post-quantum-crypto"]

    update_technology("post-quantum-crypto", TechEdit(name="post-quantum cryptography", enabled=True), "America/Chicago")
    resolver.run_resolve_sync()                 # organizing again after the rename

    techs = list(db["technologies"].find())
    assert len(techs) == 1
    assert techs[0]["_id"] == "post-quantum-crypto" and techs[0]["name"] == "post-quantum cryptography"
    assert "post quantum crypto" in techs[0]["aliases"]
    assert techs[0]["doc_count"] == 2


def test_a_new_name_whose_id_is_taken_gets_a_number(organizer):
    db = organizer
    _pages(db, "alpha tech")
    resolver.run_resolve_sync()
    update_technology("alpha-tech", TechEdit(name="beta tech", enabled=True), "America/Chicago")

    _pages(db, "alpha technology")              # the model names this new group "alpha tech"
    resolver.run_resolve_sync()

    by_id = {t["_id"]: t["name"] for t in db["technologies"].find()}
    assert by_id == {"alpha-tech": "beta tech", "alpha-tech-2": "alpha tech"}


class LabelLLM(FakeLLM):
    """Writes labels: QUIC in capitals, "edge ai" with changed words (ignored)."""
    asked: list[list[str]] = []

    def ask(self, prompt, system=None, **kw):
        if "Names:\n" not in prompt:                # the technology_resolve skill
            return super().ask(prompt, system)
        names = json.loads(prompt.rsplit("Names:\n", 1)[1])
        LabelLLM.asked.append(names)
        return json.dumps({"labels": {n: "QUIC" if n == "quic" else "Edge chips" if n == "edge ai"
                                      else n.capitalize() for n in names}})


def test_labels_change_capitals_only_and_only_missing_ones_are_asked(organizer, monkeypatch):
    db = organizer
    monkeypatch.setattr(resolver, "LLM", LabelLLM)
    LabelLLM.asked = []
    for raw in ("quic", "edge ai", "post quantum crypto"):
        _pages(db, raw)
    resolver.run_resolve_sync()
    labels = {t["name"]: t.get("label") for t in db["technologies"].find()}
    assert labels == {"quic": "QUIC", "edge ai": None, "post quantum crypto": "Post quantum crypto"}
    resolver.run_resolve_sync()                 # organizing again asks only for the missing one
    assert LabelLLM.asked == [["edge ai", "post quantum crypto", "quic"], ["edge ai"]]
    assert client_labels(db) == {"quic": "QUIC", "post quantum crypto": "Post quantum crypto"}


def client_labels(db) -> dict:
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app).get("/api/technologies/labels").json()


def test_a_findings_own_technologies_are_stamped(organizer):
    db = organizer
    db["documents"].insert_one({
        "technologies": ["edge ai", "quic"], "ignored_by": None, "is_stub": False, "end_url": "https://x/p",
        "source_id": "s", "category": "H1", "kind": "article",
        "signals": [{"signal_id": "launch", "technologies": ["quic"]}, {"signal_id": "other"},
                    {"signal_id": "funding", "technologies": ["never a page tag"]}]})
    resolver.run_resolve_sync()
    d = db["documents"].find_one({"end_url": "https://x/p"})
    assert d["technologies_resolved"] == ["edge ai", "quic"]
    assert d["signals"][0]["technologies_resolved"] == ["quic"]
    assert "technologies_resolved" not in d["signals"][1]     # none of its own: readers use the page's
    assert "technologies_resolved" not in d["signals"][2]     # none of its names resolve


def test_a_rename_typed_with_capitals_is_how_the_name_shows(organizer):
    db = organizer
    _pages(db, "quic")
    resolver.run_resolve_sync()
    update_technology("quic", TechEdit(name="QUIC", enabled=True), "America/Chicago")
    t = db["technologies"].find_one({"_id": "quic"})
    assert (t["name"], t["label"]) == ("quic", "QUIC")
    update_technology("quic", TechEdit(name="quic", enabled=False), "America/Chicago")          # switching off keeps it
    assert db["technologies"].find_one({"_id": "quic"})["label"] == "QUIC"
    update_technology("quic", TechEdit(name="quic protocol", enabled=True), "America/Chicago")  # renamed in lowercase
    assert "label" not in db["technologies"].find_one({"_id": "quic"})
