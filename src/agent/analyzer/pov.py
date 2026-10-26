"""PoV composer (Phase E). One LLM call per technology that NARRATES the
stored assessment data into the client's house-format sections — it never
scores. Every number in a PoV is copied from assessments (TORA roll-ups,
placement, watch metrics); the composer writes the prose around them, and an
unscorable measure becomes an explicit evidence-gap sentence, never a guess."""

import logging
import re
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.services import auth, decisions, evidence, watch
from app.services.llm.context import with_context
from app.services.db.mongo import get_collection
from app.services.llm.llm import LLM, parse_json
from app.services.prompts.store import PromptStore
from app.services.timezone import now_utc, valid_tz
from app.settings import get_settings
from app.services import jobs as background

log = logging.getLogger(__name__)

# one section per score, one for the other measures, then the priority: each
# measure is discussed once (before v4 of the skill: maturity, market_view and
# capability_gap, which retold the scores' measures); background (v11 on) is
# the one written from general knowledge, for a reader new to the technology
SECTIONS = ("headline", "background", "summary", "maturity", "value", "tora_analysis", "other_measures",
            "placement_rationale", "evidence_gaps", "recommendation")
CITE = re.compile(r"\[(\d+)\]")

AXES = {"market_potential": "Market Potential", "strategic_fit": "Strategic Fit",
        "adoption_readiness": "Adoption Readiness"}


def _num(x: float) -> str:
    """A score as the portal shows it: at most one decimal (8.0 → 8, 7.29 → 7.3)."""
    return f"{round(x, 1):g}"


def _site(url: str) -> str:
    return (urlparse(url).hostname or url).removeprefix("www.")


def _axis_line(name: str, v: dict | None) -> str:
    if not v:
        return f"  {name}: not assessed"
    if v.get("score") is None:
        return f"  {name}: no score (none of its {v.get('of')} measures had enough evidence)"
    rest = (f"from all {v['of']} measures" if v.get("scored") == v.get("of")
            else f"from only {v.get('scored')} of its {v.get('of')} measures")
    return f"  {name}: {_num(v['score'])} out of 10, {rest}"


def _priority_line(p: dict, inputs: dict[str, str]) -> str:
    """The priority and horizon, and the two things they're worked out from:
    how soon (`inputs["timeline"]`: the measures behind it) and how big."""
    def part(label: str, c: dict | None, names: str) -> str:
        c, src = c or {}, f" (from {names})" if names else ""
        if c.get("score") is None:
            return f"{label}{src} couldn't be worked out: {c.get('scored', 0)} of {c.get('of', '?')} inputs scored"
        band = f", {c['band']}" if c.get("band") else ""
        return f"{label}{src}: {_num(c['score'])}{band}, from {c.get('scored')} of {c.get('of')} inputs"
    rest = (f"{part('How soon', p.get('timeline'), inputs.get('timeline', ''))}. "
            f"{part('How big', p.get('potential'), inputs.get('potential', ''))}.")
    o = p.get("override")
    who = (f" (set by a person; the scores give {o.get('computed') or 'no priority'}; "
           f"their reason: {o.get('reason') or 'none recorded'})") if o else ""
    if p.get("priority"):
        return f"  Priority {p['priority']}{who}, horizon {p.get('horizon') or 'not set'}. {rest}"
    return f"  Priority and horizon: not set. {rest}"


def _assessment_digest(assessments: list[dict], method: dict[str, dict], grid: dict | None = None,
                       read: set[str] | None = None, cite=None) -> str:
    """The composer's only source of truth: the stored scores, in plain words.
    Each measure is named under its axis (`method`: the run's own frozen
    measures, by id), with what couldn't be scored and what would resolve it;
    then the priority and the measures behind it (`grid`: the run's own
    priority grid), and the sites the evidence comes from (`read`: the URLs of
    the pages the assessment read). No codes, so none can leak into the prose."""
    def names(ids: list[str] | None) -> str:
        return ", ".join((method.get(i) or {}).get("name") or i for i in ids or [])
    inputs = {"timeline": names((grid or {}).get("timeline_from")),
              "potential": names((grid or {}).get("potential_from"))}
    def from_sites(pages: set[str]) -> str:
        sites = Counter(_site(u) for u in pages)
        return (f"from {len(sites)} {'site' if len(sites) == 1 else 'sites'}: "
                + ", ".join(f"{s} ({n})" for s, n in sites.most_common()))
    docs = len(read) if read else max((a.get("doc_count") or 0) for a in assessments)
    urls = {u for a in assessments for m in (a.get("measures") or {}).values()
            for u in m.get("evidence_urls") or []}
    pages = f"{docs} pages read, {from_sites(read)}" if read else f"{docs} pages read"
    cited = (f"The scores cite {len(urls)} of them" + ("" if read else f", {from_sites(urls)}") if urls
             else "The scores cite none of them")
    blocks = [f"EVIDENCE: {pages}. {cited}."]
    for a in assessments:
        lines = [f"FABRIC: {a['fabric']}"]
        by_axis: dict[str, list[str]] = {}
        for mid, m in a.get("measures", {}).items():
            meta = method.get(mid) or {}
            name = meta.get("name") or mid.replace("-", " ").capitalize()
            if m.get("unscorable") or m.get("score") is None:
                text = f"    - {name}: not enough evidence. Would need: {m.get('missing') or 'not recorded'}"
            else:
                text = f"    - {name}: {_num(m['score'])}. {m.get('justification') or ''}".rstrip()
                if m.get("state") == "scored_by_person" and m.get("decision"):
                    text = (f"    - {name}: {_num(m['score'])}, scored by a person"
                            f" (reason: {m['decision'].get('reason')})")
                elif cite:
                    text += cite(m.get("evidence_urls") or [])
                if m.get("counter_case"):
                    text += f"\n      Counter-case: {m['counter_case']}"
            by_axis.setdefault(meta.get("axis") or "extra", []).append(text)
        for axis, name in AXES.items():
            lines.append(_axis_line(name, (a.get("tora") or {}).get(axis)))
            lines += by_axis.get(axis, [])
        if by_axis.get("extra"):
            lines.append("  Other measures (not part of the three scores):")
            lines += by_axis["extra"]
        lines.append(_priority_line(a.get("placement") or {}, inputs))
        blocks.append("\n".join(lines))
    wm = next((a["watch_metrics"] for a in assessments if a.get("watch_metrics")), [])  # one per technology
    tech_id = next((a["tech_id"] for a in assessments if a.get("tech_id")), None)
    if wm and tech_id:  # a person's threshold, or their "not crossed", is what the Point of View says
        wm = watch.apply(wm, decisions.active([tech_id], ["watch_threshold", "watch_crossed"]))
    if wm:
        crossed = {True: " | CROSSED its threshold since the last assessment", False: " | not crossed yet"}
        blocks.append("SIGNS TO WATCH (suggested by the assessment and checked at the next one):\n" + "\n".join(
            f"  - {m.get('metric')} | now: {m.get('current_value')}"
            + (f" | was: {m['previous_value']}" if m.get("previous_value") else "")
            + f" | threshold: {m.get('inflection_threshold')}{crossed.get(m.get('crossed'), '')}"
            f" | if crossed: {m.get('implication')}" + (
                (f" | source:{cite([m['source']])}" if cite and str(m["source"]).startswith("http")
                 else f" | source: {m['source']}") if m.get("source") else "")
            for m in wm))
    return "\n\n".join(blocks)


def _cite(nums: list[int]) -> str:
    return "".join(f" [{n}]" for n in nums)


class Sources:
    """The numbered sources a Point of View cites: every page its answers
    rest on, in first-cited order, one number per address. `items`: a
    written Point of View's own list, which later pages continue."""

    def __init__(self, items: list[dict] | None = None):
        self._names = evidence.source_names()
        # written before 21 Oct, a source was stored as its id: it reads as its name
        self.items = [{**s, "source": self._names.get(s.get("source"), s.get("source"))} for s in items or []]
        self._by_url: dict[str, int] = {s["url"]: s["n"] for s in self.items if s.get("url")}

    def _add(self, doc: dict) -> int:
        url = doc.get("end_url") or ""
        if url not in self._by_url:
            self.items.append({"n": len(self.items) + 1, "doc_id": doc.get("_id"), "url": url,
                               "source": doc.get("source_name") or self._names.get(doc.get("source_id"))
                               or doc.get("source_id") or _site(url),
                               "date": doc.get("published_date") or str(doc.get("scraped_at") or "")[:10],
                               "title": doc.get("title") or url})
            self._by_url[url] = len(self.items)
        return self._by_url[url]

    def docs(self, ids: list[str] | None) -> list[int]:
        """The numbers of these pages (by id), each new one numbered next."""
        ids = list(ids or [])
        docs = {d["_id"]: d for d in get_collection("documents").find(
            {"_id": {"$in": ids}}, {"end_url": 1, "title": 1, "source_name": 1, "source_id": 1,
                                    "published_date": 1, "scraped_at": 1})} if ids else {}
        return list(dict.fromkeys(self._add(docs[i]) for i in ids if i in docs))

    def urls(self, urls: list[str] | None) -> list[int]:
        """The numbers of these addresses, each new one numbered next."""
        nums = []
        for u in urls or []:
            if u in self._by_url:
                nums.append(self._by_url[u])
                continue
            d = get_collection("documents").find_one({"end_url": u}, {"end_url": 1, "title": 1, "source_name": 1,
                                                                     "source_id": 1, "published_date": 1, "scraped_at": 1},
                                                     sort=[("scraped_at", -1)]) or {"end_url": u}
            nums.append(self._add(d))
        return list(dict.fromkeys(nums))

    def cite_docs(self, ids: list[str]) -> str:
        return _cite(self.docs(ids))

    def cite_urls(self, urls: list[str]) -> str:
        return _cite(self.urls(urls))

    def text(self) -> str:
        return "\n".join(f"[{s['n']}] {s['source']} · {s['date']} · {s['title']}" for s in self.items)


def _plan(tech_id: str, fabric_id: str, f: dict, decs: list[dict], decisions, finance) -> str:
    """Tata's plan for one fabric, in full, as its fabric tab records it: the
    step reached (with the reason given), the proof recorded for each step,
    whether the next step's proof is in hand, the blockers, and the owner's
    record (next action and date, people, budget, trial) with the commitment
    it adds up to."""
    clean = lambda t: str(t or "").strip().rstrip(".").strip()
    parts = []
    step_d = decisions.pick(decs, "path_step", tech_id=tech_id, fabric_id=fabric_id)
    if f["step"]:
        why = clean(step_d.get("reason")) if step_d else ""
        parts.append(f"step reached on the path to scale: {f['step']['name']} (step {f['step']['order']} of "
                     f"{len(finance.steps())})" + (f"; the reason recorded: {why}" if why else ""))
    v = (decisions.pick(decs, "finance", tech_id=tech_id, fabric_id=fabric_id) or {}).get("value") or {}
    proof = [f"{finance.NEEDS[k][0]}: {clean(v[k])}" for k in ("cost_per_outcome", "buyer", "budget", "exposed_contracts") if v.get(k)]
    if v.get("price") is not None:
        proof.append(f"an indicative price: ${v['price']:g} a unit")
    if proof:
        parts.append("proof Tata has recorded: " + "; ".join(proof))
    nxt = f.get("next_step") or {}
    if f["step"] and nxt.get("name") and nxt.get("needs"):
        parts.append(f"the proof for the next step, {nxt['name']}, is in hand" if nxt.get("in_hand") else
                     f"next step {nxt['name']}, which still needs: " + ", ".join(n["label"] for n in nxt["needs"] if not n["have"]))
    b = f.get("bottlenecks") or {}
    blockers = [clean(x) for x in [*(b.get("picked") or []), b.get("other")] if clean(x)]
    if blockers:
        parts.append("blockers that could stop it scaling: " + "; ".join(blockers))
    lead = decisions.leader_state(decs, tech_id, fabric_id)
    if lead.get("owner"):
        due = datetime.fromisoformat(lead["due"]).strftime("%-d %b %Y")  # "15 Dec 2026"
        parts.append(f"owner: {clean(lead['owner'])}; next action: {clean(lead['next_action'])}, due {due}"
                     + "".join(f"; {w}: {clean(lead[k])}" for k, w in (("people", "people committed"),
                               ("budget", "budget committed"), ("poc", "trial committed")) if lead.get(k)))
    state = {"undefined": "No owner yet", "defined": "Defined", "aligned": "Aligned", "integrated": "Integrated"}[lead["state"]]
    return (". ".join(parts) + f". Commitment: {state}.") if parts else "nothing recorded yet."


def _extras(tech: dict, applied: list[dict], decs: list[dict], src: Sources) -> str:
    """What a Point of View adds to the scores: the classification, where the
    value lands, the path to scale, the finance figures and people's choices
    (`decs`: the technology's choices in force)."""
    from app.services import classify_effective, finance
    c = classify_effective.effective(tech, decs, classify_effective.names())
    said = classify_effective.SOURCE_WORDS.get

    def why(a: dict) -> str:
        """Where an answer came from, with its reason and pages. A value from
        Tata's catalog says so, with what the radar judged when that differs."""
        if a.get("imported"):
            r = a.get("radar") or {}
            return (f", from Tata's catalog ({a['imported']})"
                    + (f"; the radar judged {r['name']}, {said(r['source'])}" + (f": {r['reason']}" if r.get("reason") else "")
                       + src.cite_docs(r.get("pages") or []) if r.get("name") and not r.get("same") else ""))
        return f", {said(a['source'])}" + (f": {a['reason']}" if a.get("reason") else "") + src.cite_docs(a.get("pages") or [])

    lines = ["CLASSIFICATION (cite as [n]):",
             f"- Commercial availability: {c['availability']['name']}{why(c['availability'])}",
             "- Readiness: " + (f"TRL {c['trl']['level']} ({c['trl']['name']}){why(c['trl'])}" if c["trl"]["level"]
                                else f"not known ({c['trl'].get('missing') or 'the pages do not show it'})"),
             f"- Domain: {c['domain']['name']}" + (f" › {c['domain']['subdomain']}" if c["domain"].get("subdomain") else ""),
             (f"- Evidence: judged {c['evidence']['verdict'].replace('_', ' ')}: {c['evidence'].get('reason')}"
              + src.cite_docs(c["evidence"].get("pages") or []) if c.get("evidence") else "- Evidence: not judged yet")]
    from app.services import market
    size = next((s for s in (market.market_size(a.get("measures")) for a in applied) if s), None)
    if size:  # the band the page shows; quote it as a band, with the figure it comes from
        lines.append(f"- Market size: the {size['band']} band, from a figure of ${size['amount_usd_bn']:g}B"
                     f" ({', '.join(str(x) for x in (size.get('scope'), size.get('year')) if x)}){src.cite_urls([size['url']])}"
                     if size["band"] else "- Market size: no page gives a market figure")
    accepted = {d["key"] for d in decs if d["kind"] == "use_case" and d["value"] == "accept"}
    value = ["VALUE, per fabric (cite as [n]; never write a figure):"]
    for a in applied:
        cases = a.get("use_cases") or []
        if cases:
            for uc in cases:
                value.append(f"- {a['fabric']}: use case {uc['rank']}: {uc['title']}{src.cite_docs(uc.get('pages') or [])}")
                for lv in uc.get("levers") or []:
                    value.append(f"    lever ({lv['lever_id']}): {lv['operating_change']} → {lv['metric']} → "
                                 f"{lv['financial_effect']} → evidence needed: {lv['evidence_needed']} → next step when: "
                                 f"{lv['next_step_when']}{src.cite_docs(lv.get('pages') or [])}")
                cap = uc.get("capital") or {}
                if cap.get("direction"):
                    value.append(f"    capital: {cap['direction']}: {cap.get('why')}")
        else:
            ok = [s for s in a.get("suggested_use_cases") or [] if s["key"] in accepted]
            for sgg in ok:
                value.append(f"- {a['fabric']}: suggested use case, accepted by a person (not from the pages): {sgg['title']}: {sgg['why']}")
            if a.get("no_use_case"):
                value.append(f"- {a['fabric']}: no use case in the pages. {a['no_use_case'].get('reason') or ''} "
                             f"Evidence that would show one: {a['no_use_case'].get('evidence_needed') or 'not said'}")
            elif not ok:
                value.append(f"- {a['fabric']}: not mapped yet")

    path = finance.steps()
    steps = ["TATA'S PLAN (typed in by Tata's people on each fabric's tab, not from the pages: Tata's own record; "
             "quote it exactly and never cite a page number for it), per fabric:"]
    money, people = ["FINANCE (figures entered by people; quote exactly):"], ["PEOPLE'S CHOICES:"]
    for a in applied:
        f = finance.figures(tech["_id"], a["fabric_id"], decs, None, path)
        steps.append(f"- {a['fabric']}: " + _plan(tech["_id"], a["fabric_id"], f, decs, decisions, finance))
        if not f["needed"]:
            money.append(f"- {a['fabric']}: not needed yet (asked for from Proof of concept on)")
        else:
            got = [f"{k.replace('_', '-')}: {f[k]['value']:,}" + (f" {f[k].get('unit')}" if f[k].get("unit") else "")
                   + f" ({f[k]['formula']})" for k in ("contribution", "payback", "break_even") if f.get(k) and f[k].get("value") is not None]
            miss = [f"{k.replace('_', '-')} needs {', '.join(v)}" for k, v in f["missing"].items()]
            margin = f"margin {f['margin']['value']:.0%} ({f['margin']['source']})" if f.get("margin") else "no margin yet"
            money.append(f"- {a['fabric']}: {'; '.join(got) or 'no figures yet'}; {margin}" + (f"; {'; '.join(miss)}" if miss else ""))
        # a priority a person set is on its fabric's priority line, a hand score on its measure's
        for mid, m in a["measures"].items():
            if m.get("state") == "gap_accepted":
                people.append(f"- {a['fabric']}: a person accepted that {mid.replace('-', ' ')} can't be assessed")
    money = money if finance.SHOWN else []  # set aside until Tata has discussed it
    return "\n".join(lines + [""] + value + [""] + steps + ([""] + money if money else []) + ([""] + people if len(people) > 1 else []))


def pov_inputs(run_id: str, tech_id: str, with_sources: bool = False):
    """The assessments a Point of View is written from, and the pov skill's
    blanks filled from them: compose_pov sends exactly these, and the Skills
    page's preview shows them. Raises KeyError when the run has no
    assessments for the technology."""
    assessments, applied, tech, decs, method, grid = _written_from(run_id, tech_id)
    technology = assessments[0]["technology"]
    # the pages it read: the versions it recorded, or (older assessments) the
    # technology's linked pages, as the evidence builder picks them
    versions = [p for a in assessments for p in a.get("dossier_pages") or []]
    query = {"_id": {"$in": versions}} if versions else {"technologies_resolved": technology}
    read = {d.get("end_url") or str(d["_id"]) for d in get_collection("documents").find(query, {"end_url": 1})}

    for a in applied:  # the priority in force, and a person's override with its reason
        e = a["effective"]
        a["placement"] = {**a["placement"], "priority": e["priority"],
                          **({"override": {"reason": e["override"].get("reason"), "computed": e["computed_priority"]}}
                             if e["override"] else {})}
    src = Sources()
    extras = _extras(tech, applied, decs, src)
    digest = _assessment_digest(applied, {m["_id"]: m for m in method}, grid, read, cite=src.cite_urls)
    data = f"{extras}\n\n{digest}\n\nSOURCES (cite only these numbers):\n{src.text() or '(none)'}"
    values = {"technology": tech.get("label") or technology, "assessment_data": data}
    return (assessments, values, src.items) if with_sources else (assessments, values)


def _written_from(run_id: str, tech_id: str):
    """(assessments, the same with people's choices applied, the technology,
    its choices in force, the run's measures, its priority grid): what a Point
    of View is written from and shown beside. The run's own frozen method, so
    later Setup edits can't change what an old run meant. Raises KeyError
    when the run has no assessments for the technology."""
    assessments = list(get_collection("assessments")
                       .find({"scoring_run_id": run_id, "tech_id": tech_id})
                       .sort("fabric_id", 1))
    if not assessments:
        raise KeyError(f"no assessments for {tech_id!r} in scoring run {run_id!r}")
    tech = get_collection("technologies").find_one({"_id": tech_id}) or {"_id": tech_id, "name": assessments[0]["technology"]}
    snapshot = (get_collection("scoring_runs").find_one(
        {"_id": run_id}, {"snapshot.measures": 1, "snapshot.scoring_config": 1}) or {}).get("snapshot") or {}
    method = snapshot.get("measures") or list(get_collection("measures").find())
    config = snapshot.get("scoring_config") or list(get_collection("scoring_config").find())
    grid = next((c for c in config if c["_id"] == "priority_grid"), None)
    # people's choices applied: a hand score replaces an unscored measure, an override is the priority
    from app.services import decisions, effective
    decs = decisions.active([tech_id])
    return assessments, [effective.apply(a, decs, method, config) for a in assessments], tech, decs, method, grid


def pov_view(pov: dict) -> dict:
    """What a Point of View's page shows beside its text, the same for the
    admins and the leaders, every page numbered in its sources: the four
    answers, and per fabric the scores, the priority (with a person's
    override and reason), each measure and where the value lands, from the
    assessment it was written from. A page these cite that the text doesn't
    gets the next number, so the page has one numbering throughout; so do the
    pages of the latest assessment's use cases, which the page shows in full."""
    from app.services import classify_effective, finance, gates
    src = Sources(pov.get("sources"))
    tech_id = pov["tech_id"]
    try:
        _, applied, tech, decs, method, _ = _written_from(pov["scoring_run_id"], tech_id)
    except KeyError:  # its assessments are gone: the text stands alone
        applied, decs, method = [], [], []
        tech = get_collection("technologies").find_one({"_id": tech_id}) or {"_id": tech_id, "name": pov.get("technology")}
    cls = classify_effective.effective(tech, decs, classify_effective.names())
    for k in ("availability", "domain", "trl", "evidence"):
        if cls.get(k):
            cls[k]["refs"] = src.docs(cls[k].get("pages"))
            if (cls[k].get("radar") or {}).get("pages"):  # what the radar judged, beside a value from Tata's catalog
                cls[k]["radar"]["refs"] = src.docs(cls[k]["radar"]["pages"])
    accepted = {d["key"] for d in decs if d["kind"] == "use_case" and d["value"] == "accept"}
    path, fabrics = finance.steps(), []
    for a in applied:
        e = a["effective"]
        f = finance.figures(tech_id, a["fabric_id"], decs, None, path)
        fabrics.append({
            "assessment_id": a["_id"], "fabric_id": a["fabric_id"], "fabric": a.get("fabric"),
            "doc_count": a.get("doc_count"), "created_at": a.get("created_at"), "tora": a.get("tora") or {},
            "priority": e["priority"], "computed_priority": e["computed_priority"], "horizon": e["horizon"],
            "override": {k: e["override"].get(k) for k in ("reason", "at", "tz")} if e["override"] else None,
            "override_moved": e["override_moved"],
            "measures": {mid: {**{k: m.get(k) for k in ("score", "state", "justification", "counter_case", "missing",
                                                       "model_score")},
                               "reason": (m.get("decision") or {}).get("reason"), "refs": src.urls(m.get("evidence_urls"))}
                         for mid, m in a["measures"].items()},
            "use_cases": [{"title": uc["title"], "refs": src.docs(uc.get("pages")),
                           "levers": [lv["lever_id"] for lv in uc.get("levers") or []],
                           "capital": (uc.get("capital") or {}).get("direction"),
                           "capital_why": (uc.get("capital") or {}).get("why")} for uc in a.get("use_cases") or []],
            "suggested": [s["title"] for s in a.get("suggested_use_cases") or [] if s["key"] in accepted],
            "no_use_case": a.get("no_use_case"),
            "path_step": (f["step"] or {}).get("name"), "path_step_order": (f["step"] or {}).get("order"),
            "path_steps": len(path), "figures_from": {k: path.get(finance.POC, {}).get(k) for k in ("name", "order")},
            "finance": {k: f.get(k) for k in ("needed", "contribution", "payback", "break_even", "missing", "bottlenecks",
                                                "next_step")}})
    latest = gates.latest_applied([tech_id]).get(tech_id, [])
    for a in latest:
        for uc in a.get("use_cases") or []:
            src.docs([*(uc.get("pages") or []), *(p for lv in uc.get("levers") or [] for p in lv.get("pages") or [])])
    from app.services import market
    size = next((s for s in (market.market_size(a.get("measures")) for a in applied) if s), None)
    if size and size.get("url"):
        size["refs"] = src.urls([size["url"]])
    return {"classification": cls, "fabrics": fabrics, "market_size": size, "sources": src.items,
            "measures": [{k: m.get(k) for k in ("_id", "code", "name", "axis", "weight")} for m in method],
            "watch_metrics": watch.apply(next((a["watch_metrics"] for a in applied if a.get("watch_metrics")), []),
                                         decisions.active([tech_id], ["watch_threshold", "watch_crossed"])),
            "latest_assessment": {"scoring_run_id": latest[0]["scoring_run_id"], "fabric_ids": [a["fabric_id"] for a in latest],
                                  "assessed_at": min(a.get("created_at") or "" for a in latest)} if latest else None}


def compose_pov(run_id: str, tech_id: str, tz: str | None = None, job_id: str | None = None) -> dict:
    """Compose (or recompose) the PoV for one technology in one scoring run,
    recording the writer's time zone (`tz`, else the radar's default) so it
    shows when it was written in that zone. Its model calls are recorded
    under its compose job (`job_id`; a single rewrite is a job of its own),
    not the assessment run, so each run's totals are its own; the Point of
    View keeps both ids. Raises KeyError when the run has no assessments for
    the technology."""
    assessments, values, sources = pov_inputs(run_id, tech_id, with_sources=True)
    technology = assessments[0]["technology"]
    job_id = job_id or uuid.uuid4().hex[:12]
    prompt = PromptStore.get("pov")
    llm = LLM.initialize()
    rendered = prompt.render(**values)
    sections, problems, why = None, None, None
    for attempt in (1, 2):
        try:
            with with_context(run_kind="pov", run_id=job_id, tech_id=tech_id, skills=["pov"]):
                data = parse_json(llm.ask(rendered))
            if isinstance(data, dict):
                # a section the model nested inside another (seen: four under tora_analysis) goes back to its place
                for parent in [v for v in data.values() if isinstance(v, dict)]:
                    for k in SECTIONS:
                        if k in parent and data.get(k) is None:
                            data[k] = parent.pop(k)
                sections = {k: data.get(k) for k in SECTIONS}
                bad = sorted({int(n) for n in CITE.findall(str(sections)) if not 1 <= int(n) <= len(sources)})
                problems = f"cites {', '.join(f'[{n}]' for n in bad)}, which aren't in its sources" if bad else None
                if not bad:
                    break
                log.warning("pov for %s cites missing sources %s (attempt %d)", tech_id, bad, attempt)
            else:
                why = "the model's reply wasn't a JSON object"
        except ValueError as exc:
            why = f"the model's reply wasn't valid JSON ({exc})"
            log.warning("pov compose returned bad JSON (attempt %d): %s", attempt, exc)
    if sections is None:
        raise RuntimeError(f"Writing the Point of View failed twice: {why}. Try again.")

    doc_id = f"{run_id}:{tech_id}"
    existing = get_collection("povs").find_one({"_id": doc_id}, {"version": 1})
    get_collection("povs").replace_one(
        {"_id": doc_id},
        {"_id": doc_id,
         "scoring_run_id": run_id,
         "tech_id": tech_id,
         "technology": technology,
         "sections": sections,
         "assessment_ids": [a["_id"] for a in assessments],
         "compose_job_id": job_id,  # its model calls are recorded under this id
         "version": (existing or {}).get("version", 0) + 1,
         "composed_at": now_utc(),
         "composed_tz": valid_tz(tz),
         "sources": sources,
         **({"citation_problems": problems} if problems else {})},
        upsert=True)
    return get_collection("povs").find_one({"_id": doc_id})


# --- compose-all: one background job over every uncomposed technology -------

_batch_lock = threading.Lock()

_STALE_AFTER_S = 180  # a running job whose heartbeat is older than this died
                      # with the process — surface it as interrupted


def batch_status() -> dict | None:
    """The latest compose-all job, for the Points of View tab's polling."""
    job = get_collection("pov_compose_jobs").find_one(sort=[("started_at", -1)])
    if job and job["status"] == "running":  # its heartbeat says whether it's still going (it may run in the worker)
        last = job.get("heartbeat_at") or job["started_at"]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
        if age > _STALE_AFTER_S:
            get_collection("pov_compose_jobs").update_one(
                {"_id": job["_id"], "status": "running"},
                {"$set": {"status": "interrupted", "current": [],
                          "finished_at": now_utc()}})
            job["status"], job["current"] = "interrupted", []
    return job


def start_compose_all(targets: list[dict], recompose: bool = False, tz: str | None = None) -> str | None:
    """Compose PoVs for every (scoring_run_id, tech_id) in targets, in a
    background thread pool. None when a job is already running. `recompose`
    is recorded on the job so the portal can badge composed rows as queued."""
    with _batch_lock:
        job = batch_status()
        if job and job["status"] == "running":
            return None
    job_id = uuid.uuid4().hex[:12]
    get_collection("pov_compose_jobs").insert_one(
        {"_id": job_id, "status": "running", "recompose": recompose, "by": auth.by(),
         "total": len(targets), "done": 0,
         "current": [], "failed": [], "started_at": now_utc(),
         "heartbeat_at": now_utc()})
    background.start(_run_batch, job_id, targets, tz)
    return job_id


def _run_batch(job_id: str, targets: list[dict], tz: str | None = None) -> None:
    jobs = get_collection("pov_compose_jobs")

    def one(t: dict) -> None:
        jobs.update_one({"_id": job_id},
                        {"$push": {"current": t["tech_id"]},
                         "$set": {"heartbeat_at": now_utc()}})
        update: dict = {"$inc": {"done": 1},
                        "$pull": {"current": t["tech_id"]},
                        "$set": {"heartbeat_at": now_utc()}}
        try:
            compose_pov(t["scoring_run_id"], t["tech_id"], tz, job_id)
        except Exception as exc:
            log.exception("compose-all: %s failed", t["tech_id"])
            update["$push"] = {"failed": {"tech_id": t["tech_id"],
                                          "scoring_run_id": t["scoring_run_id"],
                                          "error": str(exc)}}
        jobs.update_one({"_id": job_id}, update)

    try:
        with ThreadPoolExecutor(max_workers=get_settings().scoring_concurrency,
                                thread_name_prefix="pov") as executor:
            list(executor.map(one, targets))
        jobs.update_one({"_id": job_id},
                        {"$set": {"status": "completed", "current": [],
                                  "finished_at": now_utc()}})
    except Exception as exc:
        jobs.update_one({"_id": job_id},
                        {"$set": {"status": "failed", "error": str(exc),
                                  "current": [], "finished_at": now_utc()}})

