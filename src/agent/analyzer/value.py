"""Where the value lands: the value_levers skill, stacked in each fabric call
(and asked alone when it fails, or when Find evidence looks for use cases).

Per technology and fabric (from Nick's value note): up to two use cases the
pages support, each with exactly two levers in the fabric's order (lever 1,
its contribution lever; lever 2, its delivery-cost lever), each with its
mechanism and written as a chain (operating change → metric → financial
effect → evidence needed → next step when), the metric taken from the
fabric's key metrics where one fits; and the capital required, on every use
case. A lever the pages don't support is still given, marked "evidence
needed" with what would show it. With no use case in the pages: what evidence
would show one, and up to two suggested use cases (no citations) for a person
to accept before publishing. The model never writes a figure: a chain with
money or a percentage is refused and asked again.

It also suggests which of the fabric's listed blockers the pages show, each
with why, the words and the page; a person ticks them or not. A malformed
suggestion is left out, never a reason to ask again."""

import re

from app.services.db.mongo import get_collection
from app.services.prompts.recipe import Task

MONEY = re.compile(r"[$€£₹]\s?\d|\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?\s?(?:million|billion|bn|mn|k|usd|inr|crore|lakh)\b"
                   r"|\b(?:usd|inr|eur)\s?\d", re.I)
CHAIN = ("operating_change", "metric", "financial_effect", "evidence_needed", "next_step_when")
DIRECTIONS = ("light", "moderate", "heavy")


def mechanisms() -> list[dict]:
    return list(get_collection("mechanisms").find())


def two_levers(fabric: dict) -> list[dict]:
    """The fabric's two priority levers, in order: contribution, then delivery cost."""
    return (fabric.get("levers") or [])[:2]


def task_values(fabric: dict, mechs: list[dict]) -> dict:
    levers = "\n".join(f"- Lever {n}, {lv['name'].lower()} — {lv['lever_id']}: {lv['text']} (mechanism: {lv['mechanism_id']})"
                       for n, lv in enumerate(two_levers(fabric), 1)) or "None set for this fabric yet."
    return {"fabric_levers": f"{levers}\nKey metrics: {fabric.get('key_metrics') or 'none set for this fabric yet.'}",
            "mechanisms": "\n".join(f"- {m['_id']}: {m['name']} — {m['definition']}" for m in mechs),
            "fabric_cautions": fabric.get("cautions") or "None noted.",
            "fabric_blockers": "\n".join(f"- {b}" for b in fabric.get("bottlenecks") or []) or "None listed for this fabric yet."}


def task(fabric: dict, mechs: list[dict]) -> Task:
    return Task("value_levers", "value_levers", "Map where the value lands", task_values(fabric, mechs))


def check(fabric: dict, mechs: list[dict], pages: list[str]):
    """The skill's rules for its answer; page numbers become page ids."""
    required = two_levers(fabric)
    mech_ids = {m["_id"] for m in mechs}

    def cite(nums) -> list[str]:
        return [pages[n - 1] for n in nums or [] if isinstance(n, int) and 1 <= n <= len(pages)]

    def lever(given: dict, want: dict, n: int, rank: int) -> dict:
        text = " ".join(str(given.get(k) or "") for k in CHAIN)
        if MONEY.search(text):
            raise ValueError("a lever's chain wrote a figure; it must say what would be measured, not how much")
        chain = {k: str(given.get(k) or "").strip() for k in CHAIN}
        cited = cite(given.get("pages"))
        if not cited and not chain["evidence_needed"]:
            raise ValueError(f"use case {rank}'s lever {n} ({want['name']}) cites no page and doesn't say what evidence is needed")
        return {"lever_id": want["lever_id"], "order": n,
                "mechanism_id": given.get("mechanism_id") if given.get("mechanism_id") in mech_ids else want["mechanism_id"],
                **chain, "pages": cited, "evidence": "cited" if cited else "needed"}

    def run(value, _task):
        if not isinstance(value, dict):
            raise ValueError("the answer must be an object")
        cases = []
        for rank, uc in enumerate([u for u in value.get("use_cases") or []
                                   if isinstance(u, dict) and str(u.get("title") or "").strip()][:2], 1):
            levers = [lv for lv in uc.get("levers") or [] if isinstance(lv, dict)]
            given = {lv.get("lever_id"): lv for lv in levers}
            if len(levers) == len(required) and not any(lv["lever_id"] in given for lv in required):
                given = {want["lever_id"]: lv for want, lv in zip(required, levers)}  # ids miscopied: in the order asked for
            missing = [f"lever {n} ({lv['name']})" for n, lv in enumerate(required, 1) if lv["lever_id"] not in given]
            if missing:
                raise ValueError(f"use case {rank} leaves out {' and '.join(missing)}: give both of the fabric's levers, "
                                 "saying what evidence is needed where the pages don't show one")
            cap = uc.get("capital") if isinstance(uc.get("capital"), dict) else {}
            why = str(cap.get("why") or "").strip()
            if cap.get("direction") not in DIRECTIONS or not why:
                raise ValueError(f"use case {rank} gives no capital required: say light, moderate or heavy, and why")
            if MONEY.search(why):
                raise ValueError("the capital note wrote a figure")
            cases.append({"key": f"{fabric['_id']}:{rank}", "title": str(uc["title"]).strip(), "rank": rank, "cited": True,
                          "suggested": False, "pages": cite(uc.get("pages")),
                          "levers": [lever(given[lv["lever_id"]], lv, n, rank) for n, lv in enumerate(required, 1)],
                          "capital": {"direction": cap["direction"], "why": why}})
        none = value.get("no_use_case") if isinstance(value.get("no_use_case"), dict) else None
        suggested = [{"key": f"{fabric['_id']}:s{n}", "title": str(s.get("title") or "").strip(), "why": str(s.get("why") or "").strip(),
                      "cited": False, "suggested": True}
                     for n, s in enumerate((value.get("suggested") or [])[:2], 1)
                     if isinstance(s, dict) and str(s.get("title") or "").strip()]
        if not cases and none is None:
            none = {"reason": "The pages show no use case in this fabric.", "evidence_needed": ""}
        listed, blockers = set(fabric.get("bottlenecks") or []), {}
        for b in value.get("blockers") or []:  # only the fabric's own, each once, with its page and words
            if not isinstance(b, dict) or b.get("name") not in listed or b["name"] in blockers:
                continue
            page, why, quote = cite([b.get("page")]), str(b.get("why") or "").strip(), str(b.get("quote") or "").strip()
            if page and why and quote:
                blockers[b["name"]] = {"name": b["name"], "why": why, "quote": quote, "page": page[0]}
        return {"use_cases": cases, "no_use_case": none if not cases else None, "suggested": suggested if not cases else [],
                "blockers": list(blockers.values())}
    return run


def failed(why: str) -> dict:
    """What a fabric call keeps when the skill failed twice: the reason."""
    return {"failed": why}


def fields(result: dict) -> dict:
    """What an assessment stores; a failure keeps its reason (value_failed)."""
    if result.get("failed"):
        return {"use_cases": [], "no_use_case": None, "suggested_use_cases": [], "suggested_bottlenecks": [],
                "value_failed": result["failed"]}
    return {"use_cases": result["use_cases"], "no_use_case": result["no_use_case"],
            "suggested_use_cases": result["suggested"], "suggested_bottlenecks": result.get("blockers", []), "value_failed": None}
