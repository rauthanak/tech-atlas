"""What the Point of View writer is given: the stored scores in plain words,
so a partial score says what it rests on and no code can leak into the prose."""

import re

from agent.analyzer.pov import _assessment_digest

METHOD = {
    "growth": {"name": "Growth", "axis": "market_potential"},
    "addressable-market": {"name": "Addressable market", "axis": "market_potential"},
    "fabric-fit": {"name": "Fabric fit", "axis": "strategic_fit"},
    "right-to-play": {"name": "Right to play", "axis": "strategic_fit"},
    "maturity-trl": {"name": "Maturity (TRL)", "axis": "adoption_readiness"},
    "capability-gap": {"name": "Capability gap", "axis": "extra"},
}


def _measure(code, score, url=None, missing=None):
    return {"code": code, "score": score, "unscorable": score is None, "missing": missing,
            "justification": "Cisco reports it." if score is not None else "no evidence",
            "evidence_urls": [url] if url else [], "counter_case": None}


def test_scores_say_what_they_rest_on_in_plain_words():
    a = {"fabric": "Cloud", "doc_count": 6,
         "tora": {"market_potential": {"score": 4.5, "scored": 1, "of": 2, "partial": True},
                  "strategic_fit": {"score": 8.0, "scored": 1, "of": 2, "partial": True},
                  "adoption_readiness": {"score": None, "scored": 0, "of": 1, "partial": True}},
         "placement": {"priority": None, "horizon": None,
                       "timeline": {"score": None, "band": None, "scored": 0, "of": 2},
                       "potential": {"score": 4.0, "band": "mid", "scored": 1, "of": 4}},
         "measures": {"growth": _measure("M2", 4.5, "https://blogs.cisco.com/a"),
                      "addressable-market": _measure("M1", None, missing="a dated market sizing"),
                      "fabric-fit": _measure("S1", 8.0, "https://www.blogs.cisco.com/b"),
                      "right-to-play": _measure("S3", None, missing="TCL's own deployments"),
                      "maturity-trl": _measure("A1", None, missing="a production deployment"),
                      "capability-gap": _measure("X3", 7.0)},
         "watch_metrics": [{"metric": "Paying customers", "current_value": "300 onboarded",
                            "inflection_threshold": "1,000", "implication": "adoption proven",
                            "source": "https://blogs.cisco.com/a"}]}
    grid = {"timeline_from": ["maturity-trl"], "potential_from": ["addressable-market", "growth"]}
    text = _assessment_digest([a, {**a, "fabric": "Network"}], METHOD, grid)
    read = _assessment_digest([a], METHOD, grid, read={"https://blogs.cisco.com/a", "https://blogs.cisco.com/b", "https://www.blogs.cisco.com/c"})

    assert "EVIDENCE: 6 pages read. The scores cite 2 of them, from 1 site: blogs.cisco.com (2)" in text
    # with the pages read known, the sites are theirs: a page the scores don't cite still counts
    assert read.startswith("EVIDENCE: 3 pages read, from 1 site: blogs.cisco.com (3). The scores cite 2 of them.")
    assert "Market Potential: 4.5 out of 10, from only 1 of its 2 measures" in text
    assert "Strategic Fit: 8 out of 10, from only 1 of its 2 measures" in text      # 8.0 reads 8
    assert "Adoption Readiness: no score (none of its 1 measures had enough evidence)" in text
    assert "- Right to play: not enough evidence. Would need: TCL's own deployments" in text
    assert "Other measures (not part of the three scores):\n    - Capability gap: 7. Cisco reports it." in text
    assert ("Priority and horizon: not set. How soon (from Maturity (TRL)) couldn't be worked out: "
            "0 of 2 inputs scored. How big (from Addressable market, Growth): 4, mid, from 1 of 4 inputs.") in text
    assert text.count("SIGNS TO WATCH") == 1 and "source: https://blogs.cisco.com/a" in text  # once per technology
    assert not re.search(r"\b[MSAX]\d\b|UNSCORABLE|market_potential", text)  # no codes to leak into prose
