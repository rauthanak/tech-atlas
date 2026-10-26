"""A measure's score counts only when it is a real number from 0 to 10, the
answer didn't abstain, and it cites a page from the evidence it was given
(or the fabric's TCL TODAY source). Links it wasn't given are dropped."""

import math

import pytest

from agent.analyzer import engine
from factories import page, tech

DOSSIER = ("[1] [article] Edge AI trial\n  url: https://www.trial.example/news/edge/ · source: s · published: n/a\n\n"
           "[2] [article] Chips ship\n  url: https://chips.example/a?id=7 · source: s · published: n/a")
CITE = engine.cited_keys(DOSSIER)


def _answer(**kw):
    return {"score": 7, "justification": "j", "evidence_urls": ["https://chips.example/a?id=7"], "counter_case": "c",
            "unscorable": False, "missing": None, **kw}


def test_an_answer_that_abstains_has_no_score():
    r = engine.measure_result(_answer(unscorable=True), CITE)
    assert r["score"] is None and r["unscorable"] and r["missing"] == engine.ABSTAINED
    r = engine.measure_result(_answer(unscorable=True, missing="a named customer"), CITE)
    assert r["score"] is None and r["missing"] == "a named customer"   # the model's own reason is kept


@pytest.mark.parametrize("raw", [True, False, math.nan, math.inf, -math.inf, "7"])
def test_only_a_real_number_is_a_score(raw):
    r = engine.measure_result(_answer(score=raw), CITE)
    assert r["score"] is None and r["unscorable"] and r["missing"] == engine.NOT_A_NUMBER


def test_no_score_given_keeps_its_reason():
    r = engine.measure_result(_answer(score=None, unscorable=True, missing="no pages say"), CITE)
    assert r["score"] is None and r["missing"] == "no pages say"


@pytest.mark.parametrize("cited", ["https://www.trial.example/news/edge/", "http://trial.example/news/edge",
                                   "https://trial.example/news/edge#top", "https://trial.example/news/edge?utm_source=x",
                                   " https://chips.example/a?id=7 "])
def test_only_pages_from_the_evidence_count_however_the_link_is_written(cited):
    r = engine.measure_result(_answer(evidence_urls=[cited, "https://invented.example/x"]), CITE)
    assert r["score"] == 7 and r["evidence_urls"] == [cited.strip()]   # kept as written; the invented one dropped


def test_a_score_citing_only_pages_it_was_not_given_is_not_used():
    r = engine.measure_result(_answer(evidence_urls=["https://invented.example/x"]), CITE)
    assert r["score"] is None and r["evidence_urls"] == [] and r["missing"] == engine.NOT_GIVEN
    r = engine.measure_result(_answer(evidence_urls=[]), CITE)
    assert r["missing"] == "model scored without citing dossier URLs"   # as before


def test_the_url_list_is_always_a_list():
    assert engine.measure_result(_answer(evidence_urls="https://chips.example/a?id=7"), CITE)["evidence_urls"] == \
        ["https://chips.example/a?id=7"]
    assert engine.measure_result(_answer(evidence_urls={"a": 1}), CITE)["evidence_urls"] == []
    assert engine.measure_result(_answer(evidence_urls=None), None)["evidence_urls"] == []


def test_tcl_today_sources_can_be_cited():
    fabric = {"tcl_today": "IZO SD-WAN serves 1,800 sites. Source: https://tatacommunications.com/izo)."}
    cite = engine.cited_keys(DOSSIER, fabric)
    r = engine.measure_result(_answer(evidence_urls=["https://www.tatacommunications.com/izo"]), cite)
    assert r["score"] == 7


def test_without_an_allowed_set_any_citation_counts():
    """Callers that pass none (as before this check) keep today's rule: any citation."""
    assert engine.measure_result(_answer(evidence_urls=["https://anything.example"]))["score"] == 7


def test_the_page_a_dossier_shows_can_be_cited(db):
    """The link the model sees is the newest visit's, even for an unchanged revisit."""
    tech(db)
    page(db, "https://news.example/a", 1, summary_text="Edge AI chips ship")
    page(db, "https://news.example/a", 2, stub_of="https://news.example/a@1")
    built = engine.build_dossier("edge ai", 10000, signals_first=True)
    shown = built["text"].split("url: ")[1].split(" ")[0]
    r = engine.measure_result(_answer(evidence_urls=[shown]), engine.cited_keys(built["text"]))
    assert r["score"] == 7
