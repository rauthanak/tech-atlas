"""Signals at the summarizing step: normalization, never miss beats ignore,
the list hash, and long pages split into parts and merged."""

import json

from agent.scout.tools import summarize
from agent.scout.tools.summarize import normalise, split_text, summarize_page
from app.services.db import seeding
from app.services.signals import snapshot

ROWS = [
    {"_id": "funding-round", "name": "Funding round", "look_for": "money", "mode": "never_miss"},
    {"_id": "ipo", "name": "IPO or listing", "look_for": "listing", "mode": "never_miss"},
    {"_id": "single-job-ad", "name": "Single job ad", "look_for": "one posting", "mode": "can_ignore"},
]


def hit(signal, quote="Acme raised $40M.", label=None):
    return {"signal": signal, "label": label, "what": "w", "who": "x", "when": "2026-09",
            "quote": quote, "implication": "i"}


def test_normalise_maps_rows_other_and_drops():
    data = {"summary": "s", "technologies": ["Edge AI ", ""], "scout_take": "t",
            "signals": [hit("funding round"),                       # case-insensitive match
                        hit("Spectrum auction", quote="q2"),        # unknown name -> Other
                        hit("Other", quote="q3", label="Lab opening"),
                        hit("Other", quote="q4"),                    # Other without a label: dropped
                        hit("IPO or listing", quote=""),             # no quote: dropped
                        hit("Funding round")],                       # duplicate: dropped
            "ignore": None}
    out = normalise(data, ROWS)
    assert out["technologies"] == ["edge ai"]
    assert [(h["signal_id"], h["name"], h["label"]) for h in out["signals"]] == [
        ("funding-round", "Funding round", None), ("other", "Other", "Spectrum auction"),
        ("other", "Other", "Lab opening")]
    assert out["ignored_by"] is None


def test_a_finding_keeps_its_headline_and_own_technologies():
    data = {"summary": "s", "technologies": ["edge ai", "6g networks", "ml-kem", "quic"], "signals": [
        {**hit("Funding round"), "headline": "Acme raises $40M for edge AI chips",
         "technologies": ["Edge AI", "ml-kem", "edge ai", "not on the page", "quic", "6g networks"]},
        {**hit("IPO or listing", quote="q2"), "technologies": ["unknown"]},   # none on the page's list
        {**hit("Other", quote="q3", label="Lab"), "technologies": "edge ai"}]}  # not a list
    first, second, third = normalise(data, ROWS)["signals"]
    assert first["headline"] == "Acme raises $40M for edge AI chips"
    assert first["technologies"] == ["edge ai", "ml-kem", "quic"]          # on the page's list, at most 3
    assert "technologies" not in second and "technologies" not in third     # readers use the page's
    assert second["headline"] is None


def test_never_miss_beats_ignore():
    assert normalise({"signals": [], "ignore": "single job ad"}, ROWS)["ignored_by"] == "single-job-ad"
    assert normalise({"signals": [hit("Funding round")], "ignore": "Single job ad"}, ROWS)["ignored_by"] is None
    assert normalise({"signals": [], "ignore": "Funding round"}, ROWS)["ignored_by"] is None  # not an ignore row


def test_wrong_shapes_are_tolerated():
    out = normalise({"summary": "s", "technologies": "quantum", "signals": {"a": 1}}, ROWS)
    assert out["technologies"] == [] and out["signals"] == []


def test_hash_is_stable_and_changes_with_the_list():
    a = snapshot.signals_hash(ROWS)
    assert a == snapshot.signals_hash(list(reversed(ROWS))) and len(a) == 12
    changed = [dict(ROWS[0], look_for="more money"), *ROWS[1:]]
    assert snapshot.signals_hash(changed) != a


def test_split_text_keeps_everything_on_paragraph_boundaries():
    paras = [f"paragraph {i} " + "x" * 300 for i in range(40)]
    text = "\n\n".join(paras)
    parts = split_text(text, 2000)
    assert len(parts) > 1 and all(len(p) <= 2000 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
    assert split_text("short", 2000) == ["short"]
    long_para = "word " * 1000  # one paragraph longer than a part
    assert all(len(p) <= 2000 for p in split_text(long_para, 2000))


class FakeLLM:
    """Answers the summarizing prompt by part: a part containing FAIL fails."""
    def __init__(self):
        self.calls = 0

    def ask(self, prompt, system=None, **kw):
        self.calls += 1
        if "FAIL" in prompt.split("URL:")[-1]:
            raise RuntimeError("boom")
        body = prompt.split("URL:")[-1]
        if "[Part 1 of" in body:
            return json.dumps({"summary": "merged summary", "technologies": ["merged"],
                               "scout_take": "merged take", "signals": [], "ignore": None})
        n = body.count("alpha")
        return "```json\n" + json.dumps({
            "summary": f"part with {n} alphas", "technologies": ["quantum key distribution"],
            "scout_take": "take", "ignore": "Single job ad",
            "signals": [hit("Funding round", quote="Acme raised $40M.")] if "money" in body else []}) + "\n```"


def _snap(db, part_chars):
    seeding.load_if_new()
    snap = snapshot.build()
    snap["crawl_settings"]["page_part_chars"] = part_chars
    return snap


def test_long_page_is_split_and_merged(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    snap = _snap(db, 20000)
    text = "\n\n".join(["alpha " * 2000, "beta money " * 1500, "alpha gamma " * 1500])
    llm = FakeLLM()
    out = summarize_page(llm, "https://example.com/long.pdf", text, snap)
    assert out["parts"] == 3 and out["partial"] is False
    assert out["summary"] == "merged summary" and out["scout_take"] == "merged take"
    assert out["technologies"] == ["quantum key distribution"]          # union of parts, merge call ignored
    assert [h["signal_id"] for h in out["signals"]] == ["funding-round"]
    assert out["ignored_by"] is None                                     # a part has a hit
    assert out["signals_hash"] == snap["signals_hash"]
    assert llm.calls == 4                                                # three parts + one merge


def test_a_failed_part_keeps_the_rest_and_stays_stale(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    snap = _snap(db, 20000)
    text = "\n\n".join(["alpha " * 2000, "FAIL " * 3000, "alpha " * 2000])
    out = summarize_page(FakeLLM(), "https://example.com/long", text, snap)
    assert out["partial"] is True and out["signals_hash"] is None
    assert out["summary"] == "merged summary"
    assert out["ignored_by"] is None                                     # never set aside while partial
    assert out["analysis_error"]["reason"] == "some parts failed"
    assert out["analysis_error"]["detail"] == "1 of 3 parts: model call failed: boom"


def test_every_part_failing_is_stored_as_unavailable(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    snap = _snap(db, 20000)
    out = summarize_page(FakeLLM(), "https://example.com/x", "FAIL " * 9000, snap)
    assert out["summary"].startswith("(summary unavailable") and out["signals_hash"] is None
    assert out.get("failed") is True
    assert out["analysis_error"]["reason"] == "model call failed"
    assert out["analysis_error"]["detail"] == "boom" and out["analysis_error"]["at"]


def test_an_unusable_reply_says_so(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())

    class ProseLLM:
        def ask(self, prompt, system=None, **kw):
            return "Sorry, here is a plain summary instead."

    out = summarize_page(ProseLLM(), "https://example.com/p", "alpha " * 100, _snap(db, 120000))
    assert out["summary"] == "Sorry, here is a plain summary instead."   # kept, as before
    assert out["analysis_error"]["reason"] == "reply not in the expected format"
    assert out["analysis_error"]["detail"].startswith("Sorry, here is")


def test_a_good_analysis_has_no_error(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    out = summarize_page(FakeLLM(), "https://example.com/ok", "alpha " * 100, _snap(db, 120000))
    assert out["analysis_error"] is None


def test_a_failed_check_keeps_the_earlier_analysis_and_says_why(db, monkeypatch):
    import agent.resolver
    from app.services.signals import recheck
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    monkeypatch.setattr(agent.resolver, "run_resolve_sync", lambda: None)
    llm = FakeLLM()
    monkeypatch.setattr(recheck.LLM, "initialize", staticmethod(lambda *a, **k: llm))
    snap = _snap(db, 120000)
    docs = db["documents"]
    docs.insert_one({"_id": "d1", "end_url": "https://example.com/a", "is_stub": False,
                     "extracted_text": "FAIL " * 100, "summary_text": "earlier summary",
                     "signals_hash": None})
    docs.insert_one({"_id": "s1", "end_url": "https://example.com/a", "is_stub": True,
                     "ref_doc_id": "d1", "summary_text": "earlier summary"})
    db["recheck_jobs"].insert_one({"_id": "j1", "status": "running", "done": 0, "failed": 0})

    recheck._run("j1", ["d1"], snap)
    page, stub = docs.find_one({"_id": "d1"}), docs.find_one({"_id": "s1"})
    assert page["summary_text"] == "earlier summary"                     # the earlier analysis stays
    assert page["analysis_error"]["reason"] == "model call failed"
    assert stub["analysis_error"] == page["analysis_error"]              # its stub says the same
    assert db["recheck_jobs"].find_one({"_id": "j1"})["failed"] == 1

    docs.update_one({"_id": "d1"}, {"$set": {"extracted_text": "alpha " * 100}})
    recheck._run("j1", ["d1"], snap)                                     # a later success clears it
    page = docs.find_one({"_id": "d1"})
    assert page["analysis_error"] is None and page["summary_text"].startswith("part with")


def test_a_check_counts_what_it_found_and_why_pages_failed(db, monkeypatch):
    import agent.resolver
    from app.services.signals import recheck
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    monkeypatch.setattr(agent.resolver, "run_resolve_sync", lambda: None)
    monkeypatch.setattr(recheck.LLM, "initialize", staticmethod(lambda *a, **k: FakeLLM()))
    snap = _snap(db, 120000)
    db["documents"].insert_many([
        {"_id": "news", "end_url": "u1", "is_stub": False, "extracted_text": "alpha money " * 50},
        {"_id": "job-ad", "end_url": "u2", "is_stub": False, "extracted_text": "alpha " * 50},
        {"_id": "broken", "end_url": "u3", "is_stub": False, "extracted_text": "FAIL " * 50}])
    db["recheck_jobs"].insert_one({"_id": "j2", "status": "running", "done": 0, "failed": 0, "found": 0,
                                   "other": 0, "set_aside": 0, "failed_reasons": {}})
    recheck._run("j2", ["news", "job-ad", "broken"], snap)
    job = db["recheck_jobs"].find_one({"_id": "j2"})
    assert (job["found"], job["other"], job["set_aside"], job["failed"]) == (1, 0, 1, 1)
    assert job["failed_reasons"] == {"model call failed": 1}


def test_unsplit_page_set_aside_when_only_ignore(db, monkeypatch):
    monkeypatch.setattr(summarize, "call_with_backoff", lambda fn, cancelled=None: fn())
    snap = _snap(db, 120000)
    out = summarize_page(FakeLLM(), "https://example.com/job", "alpha " * 100, snap)
    assert out["parts"] is None and out["ignored_by"] == "single-job-ad"
    assert out["signals_hash"] == snap["signals_hash"]
