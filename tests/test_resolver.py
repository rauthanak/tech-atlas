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
    """n new pages naming `raw`, as storing leaves them: waiting for the next Organize."""
    db["documents"].insert_many([
        {"technologies": [raw], "ignored_by": None, "is_stub": False, "end_url": f"https://x/{raw}/{i}", "to_organize": True,
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
        "technologies": ["edge ai", "quic"], "ignored_by": None, "is_stub": False, "end_url": "https://x/p", "to_organize": True,
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


def test_an_edit_relinks_only_its_pages_and_counts_in_the_database(organizer):
    """P2-7, P2-8: a rename or a moved alias re-links only the pages naming
    those names, and recounts only the technologies they touch; counts come
    from the database: a web-search page counts as its own site, a missing
    or empty category as "?"."""
    from app.api.technologies import AliasMove, claim_alias
    db = organizer
    _pages(db, "quic")
    _pages(db, "edge ai", 3)
    db["documents"].insert_many([
        {"technologies": ["quic"], "ignored_by": None, "is_stub": False, "end_url": f"https://www.{host}/a", "to_organize": True,
         "source_id": "web_search", "category": cat, "kind": None} for host, cat in (("arxiv.org", ""), ("ietf.org", None))])
    resolver.run_resolve_sync()
    quic = db["technologies"].find_one({"_id": "quic"})
    assert (quic["doc_count"], quic["page_count"], quic["source_count"]) == (4, 4, 3)   # s, arxiv.org, ietf.org
    assert quic["horizons"] == {"H1": 2, "?": 2} and quic["kinds"] == {"article": 4}

    edge_before = list(db["documents"].find({"technologies": "edge ai"}, {"technologies_resolved": 1}))
    db["documents"].update_many({"technologies": "edge ai"}, {"$set": {"untouched": True}})
    update_technology("quic", TechEdit(name="quic protocol", enabled=True), "America/Chicago")
    assert db["documents"].count_documents({"technologies": "quic", "technologies_resolved": ["quic protocol"]}) == 4
    assert list(db["documents"].find({"technologies": "edge ai"}, {"technologies_resolved": 1})) == edge_before
    assert db["technologies"].find_one({"_id": "quic"})["doc_count"] == 4

    claim_alias("edge-ai", AliasMove(alias="quic"))     # the pages that say "quic" move to Edge AI
    assert db["technologies"].find_one({"_id": "edge-ai"})["doc_count"] == 7
    assert db["technologies"].find_one({"_id": "quic"})["doc_count"] == 0


# ── an Organize works on the pages waiting for it (24 Oct scale plan, spec §6) ──

def _register(db) -> list:
    return sorted((t["_id"], t["name"], sorted(t["aliases"]), t["doc_count"], t["page_count"])
                  for t in db["technologies"].find())


def _links(db) -> list:
    return sorted((d["end_url"], d.get("technologies_resolved")) for d in db["documents"].find())


def test_with_no_new_pages_an_organize_reads_and_changes_nothing(organizer, monkeypatch):
    db = organizer
    _pages(db, "quic")
    resolver.run_resolve_sync()
    before, asked = _register(db), []
    monkeypatch.setattr(FakeLLM, "ask", lambda self, prompt, system=None, **kw: asked.append(prompt) or '{"groups": []}')
    resolve_id = resolver.run_resolve_sync()
    assert db["resolves"].find_one({"_id": resolve_id})["new_pages"] == 0
    assert _register(db) == before
    assert not [p for p in asked if '"labels"' not in p]   # no names to organize (a missing label is asked again, as before)
    assert not db["documents"].count_documents({"to_organize": {"$exists": True}})


def test_a_new_spelling_of_a_known_name_joins_it_with_no_model_call(organizer, monkeypatch):
    db = organizer
    _pages(db, "ml-kem")
    resolver.run_resolve_sync()
    asked = []
    monkeypatch.setattr(FakeLLM, "ask", lambda self, prompt, system=None, **kw: asked.append(prompt) or '{"groups": []}')
    db["documents"].insert_one({"technologies": ["ML KEM"], "ignored_by": None, "is_stub": False, "to_organize": True,
                                "end_url": "https://x/new", "source_id": "s", "category": "H1", "kind": "article"})
    resolver.run_resolve_sync()
    assert [(t["_id"], t["doc_count"]) for t in db["technologies"].find()] == [("ml-kem", 3)]
    assert "ML KEM" in db["technologies"].find_one()["aliases"]
    assert not [p for p in asked if "ML KEM" in p]


def test_a_name_reaching_the_floor_links_its_older_pages_too(organizer, monkeypatch):
    db = organizer
    monkeypatch.setattr(get_settings(), "min_docs_per_tech", 2)
    _pages(db, "quic", 1)
    resolver.run_resolve_sync()
    assert not db["technologies"].count_documents({})          # one page: under the floor
    db["documents"].insert_one({"technologies": ["quic"], "ignored_by": None, "is_stub": False, "to_organize": True,
                                "end_url": "https://x/second", "source_id": "s", "category": "H1", "kind": "article"})
    resolver.run_resolve_sync()
    assert db["documents"].count_documents({"technologies_resolved": "quic"}) == 2


def test_pages_set_aside_are_left_out(organizer):
    db = organizer
    _pages(db, "quic")
    db["documents"].update_one({}, {"$set": {"ignored_by": "job ad"}})
    _pages(db, "only set aside", 1)
    db["documents"].update_one({"technologies": "only set aside"}, {"$set": {"ignored_by": "job ad"}})
    resolver.run_resolve_sync()
    assert [(t["name"], t["doc_count"]) for t in db["technologies"].find()] == [("quic", 1)]


def test_organizing_each_collection_gives_what_one_organize_at_the_end_gives(organizer):
    db = organizer
    # (each spelling's lead is clear: on a tie, one Organize at the end could pick either as the display name)
    batches = [["quic", "edge ai"], ["alpha technology", "quic", "edge ai"], ["alpha tech", "Edge-AI", "new thing"]]
    for i, names in enumerate(batches):                    # one Organize after each collection
        for raw in names:
            db["documents"].insert_one({"technologies": [raw], "ignored_by": None, "is_stub": False, "to_organize": True,
                                        "end_url": f"https://x/{i}/{raw}", "source_id": "s", "category": "H1",
                                        "kind": "article"})
        resolver.run_resolve_sync()
    each = (_register(db), _links(db))
    db["documents"].update_many({}, {"$unset": {"technologies_resolved": ""}, "$set": {"to_organize": True}})
    db["technologies"].delete_many({})
    resolver.run_resolve_sync()                            # all of it in one Organize
    assert (_register(db), _links(db)) == each
