"""A collection records, before its first source, how many sources it will
read in all, so its page shows "X of N" from the start instead of counting
only the groups started so far."""

from app.services.runs import runner


def test_the_run_knows_how_many_sources_it_will_read_before_it_starts(db, monkeypatch):
    db["sources"].insert_many([
        {"_id": "a", "source_id": "a", "name": "A", "horizon": "H1", "enabled": True, "access": "open"},
        {"_id": "b", "source_id": "b", "name": "B", "horizon": "H2", "enabled": True, "access": "open"},
        {"_id": "c", "source_id": "c", "name": "C", "horizon": "H3", "enabled": True, "access": "open"},
        {"_id": "d", "source_id": "d", "name": "D", "horizon": "H3", "enabled": False, "access": "open"}])
    db["runs"].insert_one({"_id": "r1", "status": "running", "totals": {"sources": 0}})
    seen = []

    class FirstGroupOnly:
        def __init__(self, category, llm):
            pass

        def run(self, run_id, executor, params):  # what the page reads while the first group runs
            seen.append(db["runs"].find_one({"_id": run_id})["planned_sources"])
            db["runs"].update_one({"_id": run_id}, {"$set": {"status": "terminating"}})

    monkeypatch.setattr(runner.LLM, "initialize", classmethod(lambda cls: None))
    monkeypatch.setattr(runner, "run_orchestrator", lambda llm: "")
    monkeypatch.setattr(runner, "Supervisor", FirstGroupOnly)
    runner._execute("r1", {"categories": ["H1", "H2", "H3"]})
    assert seen == [3]
