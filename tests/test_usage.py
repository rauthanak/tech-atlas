"""Every model call is recorded with its tokens and what it was for; fixed
blocks are marked for reuse."""

from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from app.main import app
from app.services.llm.context import carry, with_context
from app.services.llm.llm import LLM

client = TestClient(app)


class FakeStream:
    def __init__(self, reply, stop="end_turn"):
        self.reply, self.stop = reply, stop

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return NS(content=[NS(type="text", text=self.reply)], stop_reason=self.stop,
                  usage=NS(input_tokens=120, output_tokens=30, cache_read_input_tokens=4000,
                           cache_creation_input_tokens=0))


class FakeAnthropic:
    def __init__(self, reply="{}", stop="end_turn", fail=False):
        self.sent, self.reply, self.stop, self.fail = [], reply, stop, fail
        self.messages = self

    def stream(self, **kw):
        self.sent.append(kw)
        if self.fail:
            raise RuntimeError("overloaded")
        return FakeStream(self.reply, self.stop)


def test_an_anthropic_call_is_recorded_with_its_context(db):
    fake = FakeAnthropic('{"ok": true}')
    llm = LLM("anthropic", "claude-haiku-5-5", fake)
    with with_context(run_kind="scoring", run_id="r1", tech_id="edge-ai"):
        with with_context(skills=["fabric_relevance"]):
            assert llm.ask("hello") == '{"ok": true}'
    row = db["llm_calls"].find_one()
    assert (row["run_kind"], row["run_id"], row["tech_id"], row["skills"], row["ok"]) == \
        ("scoring", "r1", "edge-ai", ["fabric_relevance"], True)
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]) == (120, 30, 4000)


def test_a_failure_and_a_cut_off_reply_are_recorded_with_why(db):
    for fake, why in [(FakeAnthropic(fail=True), "overloaded"), (FakeAnthropic(stop="max_tokens"), "cut off")]:
        try:
            LLM("anthropic", "m", fake).ask("x")
            raise AssertionError("expected a failure")
        except (RuntimeError, ValueError):
            pass
        assert why in db["llm_calls"].find_one({"ok": False}, sort=[("at", -1)])["error"]


def test_blocks_are_marked_for_reuse_and_the_system_text_follows():
    fake = FakeAnthropic()
    LLM("anthropic", "m", fake).ask("tech text", system="per call", blocks=["skills", "fabric"])
    system = fake.sent[0]["system"]
    assert [p["text"] for p in system] == ["skills", "fabric", "per call"]
    assert [("cache_control" in p) for p in system] == [True, True, False]
    LLM("anthropic", "m", fake).ask("plain")
    assert fake.sent[1]["system"] == ""


def test_openai_counts_its_reused_tokens_apart(db):
    class FakeOpenAI:
        def __init__(self):
            self.sent = []
            self.responses = self

        def create(self, **kw):
            self.sent.append(kw)
            return NS(output_text="ok", usage=NS(input_tokens=5000, output_tokens=10,
                                                 input_tokens_details=NS(cached_tokens=4000)))
    fake = FakeOpenAI()
    LLM("openai", "gpt", fake).ask("p", system="s", blocks=["fixed"])
    assert fake.sent[0]["instructions"] == "fixed\n\ns"
    row = db["llm_calls"].find_one()
    assert (row["input_tokens"], row["cache_read_tokens"]) == (1000, 4000)


def test_a_worker_thread_carries_the_callers_context(db):
    from concurrent.futures import ThreadPoolExecutor
    llm = LLM("anthropic", "m", FakeAnthropic())
    with with_context(run_kind="collection", run_id="c1"), ThreadPoolExecutor(2) as pool:
        for f in [pool.submit(carry(llm.ask), "x") for _ in range(3)]:
            f.result()
    assert db["llm_calls"].count_documents({"run_id": "c1"}) == 3


def test_usage_by_skill_and_by_run(db):
    llm = LLM("anthropic", "m", FakeAnthropic())
    with with_context(run_kind="scoring", run_id="r1"):
        for skill in ["measure_scoring", "measure_scoring", "watch_metrics"]:
            with with_context(skills=[skill]):
                llm.ask("x")
    body = client.get("/api/usage", params={"run_id": "r1"}).json()
    assert {r["skill"]: r["calls"] for r in body["by_skill"]} == {"measure_scoring": 2, "watch_metrics": 1}
    assert body["total"]["input_tokens"] == 360 and body["total"]["cache_read_tokens"] == 12000
    runs = client.get("/api/usage/recent").json()["runs"]
    assert runs[0]["run_id"] == "r1" and runs[0]["calls"] == 3 and runs[0]["run_kind"] == "scoring"


def test_usage_adds_several_runs_together(db):
    llm = LLM("anthropic", "m", FakeAnthropic())
    for run_id, skill in [("c1", "article_summary"), ("c1", "signal_extraction"), ("o1", "article_summary")]:
        with with_context(run_kind="collection", run_id=run_id), with_context(skills=[skill]):
            llm.ask("x")
    body = client.get("/api/usage", params={"run_id": "c1,o1"}).json()
    assert [(r["skill"], r["calls"]) for r in body["by_skill"]] == [("article_summary", 2), ("signal_extraction", 1)]
    assert body["total"]["calls"] == 3 and body["total"]["output_tokens"] == 90
    assert client.get("/api/usage", params={"run_id": "c1"}).json()["total"]["calls"] == 2


def _calls(db, run_id, kind, n=1, skills=("pov",), recipe=None, at="2026-10-21T01:00:00+00:00"):
    db["llm_calls"].insert_many([{"run_id": run_id, "run_kind": kind, "at": at, "skills": list(skills),
                                  "recipe": recipe, "ok": True, "input_tokens": 10, "output_tokens": 5,
                                  "cache_read_tokens": 100, "cache_write_tokens": 0} for _ in range(n)])


def test_every_kind_of_run_is_its_own_row_with_what_it_was(db):
    _calls(db, "a1", "scoring", 3, skills=["fabric_relevance"])
    _calls(db, "a1", "pov", 2)                                     # Points of View filed under the assessment run
    _calls(db, "c1", "collection", 2, skills=["article_summary"])
    _calls(db, "o1", "resolve", 1, skills=["technology_resolve"])
    _calls(db, "j1", "find_evidence", 1, skills=["web_search"])
    _calls(db, "r9", "find_evidence", 2, skills=["article_summary"])
    _calls(db, "k1", "classify", 4, skills=["trl_level"], recipe="classify")
    db["scoring_runs"].insert_one({"_id": "a1", "status": "completed", "started_at": "2026-10-06T04:00:00+00:00"})
    db["runs"].insert_many([{"_id": "c1", "status": "completed", "resolve_id": "o1", "params": {}},
                            {"_id": "r9", "status": "completed", "params": {"kind": "find_evidence", "job_id": "j1"}}])
    db["classify_runs"].insert_one({"_id": "k1", "status": "completed", "total": 1558, "tz": "America/Chicago",
                                    "trigger": "on demand", "tech_ids": ["x"]})
    db["find_evidence_jobs"].insert_one({"_id": "j1", "status": "completed", "gap": {"tech_id": "edge-ai"},
                                         "summary": "1 new page"})
    db["technologies"].insert_one({"_id": "edge-ai", "name": "edge ai", "label": "Edge AI"})
    body = client.get("/api/usage/recent", params={"limit": 50}).json()
    rows = {(r["run_id"], r["run_kind"]): r for r in body["runs"]}
    assert rows[("a1", "scoring")]["calls"] == 3 and rows[("a1", "pov")]["calls"] == 2
    assert rows[("a1", "pov")]["about"] == {"assessment": {"id": "a1", "started_at": "2026-10-06T04:00:00+00:00"}}
    assert rows[("o1", "resolve")]["part_of"] == {"kind": "collection", "id": "c1"}
    assert rows[("r9", "find_evidence")]["part_of"] == {"kind": "find_evidence", "id": "j1"}
    assert rows[("j1", "find_evidence")]["about"]["technology"] == "Edge AI"
    assert rows[("k1", "classify")]["about"] == {"status": "completed", "total": 1558, "tz": "America/Chicago",
                                                 "trigger": "on demand"}
    assert body["recorded_since"] == "2026-10-21T01:00:00+00:00"


def test_one_kind_of_a_runs_calls_by_name(db):
    db["recipes"].insert_one({"_id": "technology", "name": "Technology call"})
    db["prompts"].insert_one({"_id": "pov", "title": "Write the Point of View"})
    _calls(db, "a1", "scoring", 2, skills=["fabric_relevance", "measure_scoring"], recipe="technology")
    _calls(db, "a1", "pov", 1)
    body = client.get("/api/usage", params={"run_id": "a1", "kind": "scoring"}).json()
    assert [(r["skill"], r["name"], r["calls"]) for r in body["by_skill"]] == [("technology", "Technology call", 2)]
    pov = client.get("/api/usage", params={"run_id": "a1", "kind": "pov"}).json()["by_skill"]
    assert [(r["name"], r["calls"]) for r in pov] == [("Write the Point of View", 1)]


def test_reasoning_follows_the_skills_setting(db):
    db["prompts"].insert_many([{"_id": "measure_scoring", "reasoning": "on"}, {"_id": "article_summary", "reasoning": "off"}])
    fake = FakeAnthropic()
    llm = LLM("anthropic", "m", fake)
    with with_context(skills=["measure_scoring"]):
        llm.ask("x")
    with with_context(skills=["article_summary"]):
        llm.ask("x")
    assert [s["thinking"]["type"] for s in fake.sent] == ["adaptive", "disabled"]
    assert [r["reasoning"] for r in db["llm_calls"].find().sort("at", 1)] == [True, False]
