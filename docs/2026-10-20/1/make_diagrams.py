"""Workflow diagrams for the client document (make_change_log.py): each one
is a few lanes of steps, drawn as HTML and saved as a PNG. New steps are
filled; a lane where a person decides is marked.

Inside the API container (it has the browser):
    docker cp make_diagrams.py tech-radar-atlas-1:/tmp/ && docker exec tech-radar-atlas-1 python /tmp/make_diagrams.py
    docker cp tech-radar-atlas-1:/tmp/diagrams/. <review folder>/screenshots/diagrams/
"""

import html
import os

from playwright.sync_api import sync_playwright

OUT = "/tmp/diagrams"

# name: (title, [(lane, by_a_person, [(step, detail, new)])]); a lane whose
# name starts with "Gate" holds tasks in any order, so it has no arrows
DIAGRAMS = {
    "process": ("How the radar works now", [
        ("Tech Atlas collects", False, [
            ("Collect", "pages from the sources that are switched on", False),
            ("Read each page", "the signals it shows, and the technologies it names", False),
            ("Organise the names", "one technology, many wordings", False),
            ("Classify", "availability, domain, TRL, how solid the evidence is, possibly nascent", True)]),
        ("Gate 1: before scoring", True, [
            ("Possibly nascent?", "a person says yes or no", True),
            ("Imported list", "a person accepts or rejects each proposed match", True),
            ("Switch off, move, add", "from the technology list, several at once", True),
            ("Find evidence", "for thin technologies", True)]),
        ("Assess", False, [
            ("One technology call", "fabrics, technology-wide measures, metrics to watch", True),
            ("One call per fabric", "that fabric's measures, use cases and value levers", True),
            ("Placement", "priority and horizon: arithmetic, no model call", False)]),
        ("Gate 2: before publishing", True, [
            ("Override a priority", "with a reason; the computed one stays visible", True),
            ("Unscored measures", "score by hand, accept the gap, or find evidence", True),
            ("Path to scale and finance", "recorded by people", True),
            ("Point of View", "with numbered sources, every one checked", True)]),
        ("Frontier, for leaders", False, [
            ("The 2×2", "by fabric and stage, with a table beside it", True),
            ("Point of View", "read-only, at its own address", True)]),
    ]),
    "engine": ("An assessment: before and after", [
        ("Before: one call per measure", False, [
            ("Choose fabrics", "1 call", False),
            ("Each measure, in each fabric", "1 call each, all the evidence sent again every time", False),
            ("About 30 calls", "per technology", False)]),
        ("After: stacked calls", False, [
            ("One technology call", "fabrics, technology-wide measures, metrics to watch, domain, TRL, availability", True),
            ("One call per relevant fabric", "its measures, use cases and value levers; the evidence is reused at a tenth of the price", True),
            ("About 3 calls", "per technology", True)]),
    ]),
    "find-evidence": ("Find evidence and Add a link", [
        ("Find evidence", True, [
            ("A person clicks", "the cost and today's budget are shown first", True),
            ("Search the web", "one search", True),
            ("Skip known pages", "", True),
            ("Read the new pages", "like any collected page", True),
            ("Re-run only the gap", "one measure, the classification, or the use cases", True)]),
        ("Add a link", True, [
            ("A person pastes a link", "a page they already know", True),
            ("Read the page", "", True),
            ("Re-run only the gap", "", True)]),
    ]),
    "import": ("Importing the catalog, Tata's list of emerging technologies", [
        ("Import", True, [
            ("Upload the Excel", "laid out like 'New Emerging Technologies'", True),
            ("Check", "names trimmed, repeats merged", True),
            ("Match", "exact names cost nothing; the AI proposes the rest", True),
            ("A person reviews", "accept or reject each match, map unknown values", True),
            ("Confirm", "matches become other wordings, new ones are added, Tata's values kept as Tata's", True)]),
    ]),
    "value": ("Where the value lands", [
        ("Each use case, as Nick's chain", False, [
            ("Operating change", "", True), ("Metric", "", True), ("Financial effect", "", True),
            ("Evidence needed", "", True), ("Next step", "", True)]),
        ("Path to scale, recorded by people", True, [
            ("Evaluation", "", True), ("Customer zero", "", True), ("Proof of concept", "finance figures asked from here", True),
            ("One customer", "", True), ("Beta", "", True), ("Roadmap", "", True), ("Investment", "", True)]),
    ]),
    "addresses": ("One portal, two addresses", [
        ("Admin address: Tech Lens", False, [
            ("Everything", "setup, runs, decisions, Points of View", False)]),
        ("Executive address: Frontier", False, [
            ("The 2×2 and the table", "", True),
            ("Points of View", "read-only", True),
            ("Everything else refused", "no setup, no runs, nothing that costs money", True)]),
    ]),
}

CSS = """
body { margin: 0; font-family: Helvetica, Arial, sans-serif; color: #0b1b3a; background: #fff; }
.wrap { padding: 22px 24px; width: 820px; }
h1 { font-size: 24px; margin: 0 0 16px; color: #041A4A; }
.lane { margin: 0 0 14px; padding: 2px 0 2px 14px; border-left: 4px solid #d5dbe6; }
.person { border-left-color: #e5a100; }
.who { font-size: 17px; font-weight: 700; color: #041A4A; margin-bottom: 7px; }
.who small { font-weight: 400; color: #8a5a00; margin-left: 8px; font-size: 15px; }
.steps { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.item { display: flex; align-items: center; gap: 7px; }
.step { border: 1.5px solid #9fb0cc; border-radius: 8px; padding: 8px 11px; max-width: 230px; background: #fff; font-size: 17px; }
.step b { display: block; }
.step span { display: block; font-size: 14.5px; color: #4a5a78; margin-top: 3px; line-height: 1.3; }
.new { background: #e6f0ff; border-color: #2457c5; }
.arrow { color: #7b8aa6; font-size: 22px; }
.key { margin-top: 8px; font-size: 14px; color: #4a5a78; }
.key i { display: inline-block; width: 13px; height: 13px; border-radius: 3px; vertical-align: -2px; margin: 0 5px 0 14px; }
"""


def page(title: str, lanes: list) -> str:
    rows = []
    for lane, person, steps in lanes:
        arrow = "" if lane.startswith("Gate") else '<span class="arrow">→</span>'
        boxes = "".join(  # each arrow travels with the step it points to, so a line never ends on one
            f'<div class="item">{arrow if i else ""}<div class="step{" new" if new else ""}"><b>{html.escape(st)}</b>'
            f'{f"<span>{html.escape(d)}</span>" if d else ""}</div></div>' for i, (st, d, new) in enumerate(steps))
        who = html.escape(lane) + ("<small>a person decides</small>" if person else "")
        rows.append(f'<div class="lane{" person" if person else ""}"><div class="who">{who}</div>'
                    f'<div class="steps">{boxes}</div></div>')
    key = ('<div class="key"><i style="background:#e6f0ff;border:1.5px solid #2457c5"></i>new or changed'
           '<i style="background:#fff;border:1.5px solid #9fb0cc"></i>as before'
           '<i style="background:#e5a100"></i>a person decides</div>')
    return f"<html><head><style>{CSS}</style></head><body><div class='wrap'><h1>{html.escape(title)}</h1>" \
           f"{''.join(rows)}{key}</div></body></html>"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 900, "height": 400}, device_scale_factor=2)
        for name, (title, lanes) in DIAGRAMS.items():
            pg.set_content(page(title, lanes))
            pg.locator(".wrap").screenshot(path=f"{OUT}/{name}.png")
            print("wrote", name)
        browser.close()


if __name__ == "__main__":
    main()
