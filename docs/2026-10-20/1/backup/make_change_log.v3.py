"""Needs python-docx (pip install python-docx in any venv). Builds the client change log: Tech Radar - changes after the midpoint review.docx.
Re-run after each item is built: update ITEMS (status, after image) and HISTORY."""
from pathlib import Path
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path("/Users/akki/Documents/Claude/Code/Tech-Radar/review-comments/10-20-2026")
BEFORE = ROOT / "screenshots/before"
AFTER_DESIGN = ROOT / "screenshots/after-design"
AFTER_BUILT = ROOT / "screenshots/after"
OUT = ROOT / "Tech Radar - changes after the midpoint review.docx"
NAVY = RGBColor(0x04, 0x1A, 0x4A)
MUTED = RGBColor(0x49, 0x4A, 0x52)

VERSION = "Version 3 · 21 October 2026"
HISTORY = [("1", "20 Oct 2026", "First version: every change agreed after the midpoint review, with today's screens and design mock-ups."),
           ("2", "20 Oct 2026", "Change 0 built: technologies say how solid their assessment is, a technology's result in each fabric stays "
                                "with the technology, plain names on every screen. Real screens replace its mock-up."),
           ("3", "21 Oct 2026", "Changes 1–13 built. Real screens replace their mock-ups. Change 5 tried both ways first; two measures moved to "
                                "per fabric as a result. Tata's list taken up to the review step. Every technology assessed again and every Point "
                                "of View rewritten with numbered sources.")]

# Built screens, in reading order, with their captions: item-N.png or item-N-<screen>.png
AFTER_CAPTIONS = {
    "item-0-technologies.png": "Built: 'Tracked' replaces 'Up to date'. Each row shows its priority and how many of its measures had "
                               "enough evidence to score; amber marks 'No priority' and under half scored. The definition counts "
                               "the 69 of 146 with no priority yet.",
    "item-0-technology.png": "Built: a technology's page says how solid its assessment is (30 of 48 measures scored; no priority yet "
                             "in Security), and each fabric shows its own count.",
    "item-0-assessment.png": "Built: a technology's result in one fabric stays under Technologies, is titled with the fabric, "
                             "switches fabric with tabs, and lists measures by name. The back link returns to the technology.",
    "item-0-skills.png": "Built: skills by plain name, in the order the radar uses them; code names only under Technical details.",
    "item-0-scoring-tab.png": "Built: every Scoring method tab has a title and a one-line purpose.",
    "item-0-sources.png": "Built: Sources opens on the 13 in use; 'Show all 147' lists the rest.",
    "item-1-bulk-bar.png": "Built: tick rows, and a bar acts on all of them: switch off, switch on, move, or assess with the cost shown first.",
    "item-1-switched-off.png": "Built: a switched-off technology says when, in the time zone it was switched off in; its pages are still collected.",
    "item-2-written-time.png": "Built: a Point of View written from India shows India's time; older ones show US Central.",
    "item-3-skill-map.png": "Built: every skill in the step that uses it, calls that carry several skills as dashed boxes, and what each used last time.",
    "item-4-operations.png": "Built: each run in Operations' history says how many tokens it used, and how many were reused.",
    "item-4-collection.png": "Built: a collection's page shows its model use (calls, tokens sent, reused, written back); Technical details adds a table by skill.",
    "item-5-engine.png": "Built: Weights & Grid chooses how an assessment calls the model: stacked (recommended) or one measure per call.",
    "item-5-stacked.png": "Built: a skill's page shows how it's sent inside a stacked call, its own blocks highlighted, the reused parts first.",
    "item-6-fabric-tab.png": "Built: one tab per fabric on the technology's page: the priority (override with a reason), and the measures that need a person first: score by hand, accept the gap, Tata's entries, find evidence.",
    "item-6-briefing.png": "Built: the Briefing opens on the two to-do lists, Before scoring and Before publishing, counted by technology.",
    "item-7-technologies.png": "Built: views as Tata thinks of them, filters, and for each technology where it is with the reason, its classification and its evidence.",
    "item-8-answers.png": "Built: four answers on every technology, each saying where it came from, with Why? (reason and pages) and Change.",
    "item-8-classification.png": "Built: Setup › Classification: Tata's domains and sub-domains, with the model's proposed sub-domains to accept, merge or rename.",
    "item-9-nascent.png": "Built: a possibly nascent technology, with the reason and the quote that flagged it; a person answers yes or no.",
    "item-10-find-evidence.png": "Built: Find evidence and Add a link wherever evidence is thin, with the cost and today's search budget first.",
    "item-11-import.png": "Built: Tata's list at the review step: 88 matched exactly, 138 proposed matches to accept or reject, 774 new. Nothing saved until confirmed.",
    "item-12-value-tab.png": "Built: where the value lands in a fabric: use cases with Nick's lever chain, the path to scale, and the finance card.",
    "item-12-pov.png": "Built: the Point of View leads with the verdict, then priority, maturity, availability and evidence; numbered sources at the end.",
    "item-13-frontier.png": "Built: Frontier at its own address: the 2×2 by fabric and by Tata's stage (emerging by default, Mature on "
                            "request), the table, and what isn't placed yet.",
}

# status: Planned · In progress · Built · Live
ITEMS = [
    dict(n="0", title="Clearer screens, first fixes", status="Built",
         what=["'Up to date' becomes 'Tracked', and no longer suggests 'complete'. Every technology shows its priority and how many "
               "of its measures had enough evidence to score; amber marks those with no priority, or under half scored "
               "(69 of the 146 tracked have no priority in any fabric yet).",
               "A technology's result in one fabric stays with the technology: the menu keeps Technologies selected, the page is "
               "titled with the fabric, tabs switch between its fabrics, and the back link returns to the technology.",
               "Plain names replace internal codes and ids: skills and measures by name, evidence by collection date; codes only "
               "under Technical details.",
               "Every Scoring method page has a title and a one-line purpose; the sources page opens on the 13 sources in use.",
               "The Briefing stays as it is for now: it fills again with the next collection."],
         why="Users said the portal is still confusing. A walk through it as a first-time user found 11 sources of confusion; these are quick to fix.",
         asked="Tata team; Wharton review",
         before=[("02-technologies.png", "Before: 146 technologies said 'Up to date', in green, although most measures were unscored."),
                 ("08-assessment-agentic-ai-cloud.png", "Before: a technology's result opened under Operations, with measure codes "
                  "and 'unscorable'.")],
         after=("A-briefing.png", "Design: the Briefing opens on two to-do lists and the latest findings.")),
    dict(n="1", title="Switch a technology off from the list", status="Built",
         what=["An on/off switch on every row of the technology list, and switching several at once.",
               "A switched-off technology isn't assessed or shown to leaders, but its pages are still collected, so nothing is lost.",
               "If it suddenly gathers new pages (10 by default), the list flags it: 'Switched off, but 12 new pages since: have a look?'"],
         why="Agreed at the midpoint review (committed).",
         asked="Shashank, Abhishek",
         before=("02-technologies.png", "Today: the switch exists only inside each technology's page."),
         after=("B-technologies.png", "Design: a switch on each row, and a bar for acting on several at once.")),
    dict(n="2", title="When a Point of View was written: date, time and time zone", status="Built",
         what=["Each Point of View shows the date and time it was written, in the time zone of the person who wrote it, for example 'Written 6 Oct 2026, 2:35 AM CDT'."],
         why="Asked during the review of the comments.",
         asked="Tata team",
         before=("05-pov-agentic-ai.png", "Today: 'Written Oct 6', with no time."),
         after=("D-point-of-view.png", "Design: the date, time and zone under the title.")),
    dict(n="3", title="One picture of where each AI instruction is used", status="Built",
         what=["A page showing every instruction the AI follows (we call them skills), at the step where it runs, with how often it ran in the last run.",
               "It prints on one page, so it can be shared."],
         why="Action item from the midpoint review.",
         asked="Midpoint review (action for Akshay)",
         before=("09-skills.png", "Today: a list of skills, each explained on its own page."),
         after=("F-where-skills-are-used.png", "Design: the whole pipeline on one page.")),
    dict(n="4", title="AI usage recorded for every step", status="Built",
         what=["Every AI call records how much it used, by step and by run, and the Operations page shows it.",
               "Repeated instructions are reused at a fraction of the price instead of being sent in full every time."],
         why="So the cost of every change can be measured before and after, and kept under control.",
         asked="Tata team",
         before=("11-operations.png", "Today: run history shows the number of AI calls, not their size or cost."),
         after=None),
    dict(n="5", title="A faster, leaner assessment", status="Built",
         what=["Today each technology gets about 30 separate AI calls, one per measure per business fabric, each re-reading all its evidence.",
               "After: one call for the technology-level questions (market size, growth, maturity, plus which fabrics, metrics to watch, and its domain, TRL and availability) and one per relevant fabric for that fabric's questions (including commercial adoption and use-case breadth, which depend on the fabric).",
               "Tried on 12 technologies first, then compared with the old way on 6, same model and same pages: 19 calls instead of 204, about 12 times fewer tokens, more measures answered (93% against 78%), and scores about one point apart.",
               "The first try judged commercial adoption and use-case breadth for the technology as a whole; they came out much higher than in a fabric, so they're now judged per fabric. The comparison is written up for you."],
         why="The same evidence was being sent about 30 times per technology, and the same maturity question asked once per fabric.",
         asked="Raised in our review of the comments",
         before=("08-assessment-agentic-ai-cloud.png", "Today: one assessment page per technology and fabric, built from one call per measure."),
         after=None),
    dict(n="6", title="The innovation team's decisions before publishing (Gate 2)", status="Built",
         what=["Hold a technology at a different priority than the scores give ('override'), with a reason. The computed priority stays visible beside it.",
               "Place a technology the scores couldn't place (for example, hollow-core fibre).",
               "Settle measures the evidence couldn't score: score by hand with a reason, accept the gap, or find evidence.",
               "Disruption threat and Serviceable capture become measures Tata enters, since public pages almost never answer them (98% unscored in the last run)."],
         why="'An unowned score is overruled' (deck, page 3). In the last run, 58% of measure scores couldn't be scored from public pages.",
         asked="Midpoint review (Gate 2); deck pages 9 and 13",
         before=("08-assessment-agentic-ai-cloud.png", "Today: unscored measures say what's missing, but nothing can be done about them."),
         after=("C-technology-page.png", "Design: each fabric's tab, with the override and the actions on each measure.")),
    dict(n="7", title="Technologies organised the way Tata thinks about them", status="Built",
         what=["Every technology says where it is and why: tracked and placed, tracked but held beside the grid, ready to assess, thin evidence, no evidence yet, or switched off.",
               "Ready-made views: Tracked · Not assessed · Emerging · Emerging and new to Tata · Mature but not on Tata's radar · Possible nascent · Imported with little evidence · Switched off.",
               "Filters by commercial availability, domain, TRL, evidence and fabric."],
         why="Shashank: mature technologies shouldn't crowd out emerging ones; nascent ones belong on the first page.",
         asked="Shashank, Abhishek",
         before=("02-technologies.png", "Today: 1,003 'Not assessed' with no reason per row."),
         after=("B-technologies.png", "Design: views, filters, and a status with its reason on every row.")),
    dict(n="8", title="Every technology classified: commercial availability, domain, TRL, evidence", status="Built",
         what=["Tata's own categories: commercial availability (Research, Pilot, Early commercial, Mature), domain and sub-domain, and TRL (1–9), for every technology, not only the assessed ones.",
               "Each answer shows its reason and the pages it rests on, and a person can change it; the change is remembered.",
               "The AI also judges how solid the evidence is: the number of independent sources, the kind of signal, and how credible each source is. That verdict, not a fixed page count, decides when a technology is ready to assess.",
               "The lists are editable: add or rename a domain, sub-domain or availability value at any time."],
         why="So Tata sees the radar in its own categories, and early technologies aren't hidden behind a page count. 81 of the 147 assessed technologies rested on a single source.",
         asked="Shashank (maturity), Tata team",
         before=("03-technology-agentic-ai.png", "Today: a technology's page shows scores, but no maturity, availability or domain."),
         after=("C-technology-page.png", "Design: four answers at the top, each with 'Why?' and 'Change'.")),
    dict(n="9", title="Possible nascent technologies, flagged for a person to confirm", status="Built",
         what=["The AI flags a technology that looks new and shows a strong early sign (a large funding round, a solid research result, a first deployment, a spin-out, a new standard), even from a single page.",
               "A person answers yes or no. 'Yes' lets it be assessed despite thin evidence."],
         why="Ankur's first test: spot disruptive technologies very early, especially ones unknown to Tata. The Named Data Networking story: one deployment was the signal.",
         asked="Ankur, Shashank",
         before=None,
         after=("A-briefing.png", "Design: 'Possible nascent technologies to confirm' at the top of the Before scoring list.")),
    dict(n="10", title="Find evidence", status="Built",
         what=["A button wherever evidence is missing: on a technology with thin evidence, on a measure that couldn't be scored, or on a fabric with no use case.",
               "It searches the web, reads what it finds like any collected page, and re-runs just that part. Beside it, 'Add a link' takes a page someone already knows.",
               "Only a person starts it; the cost is shown first, and there's a daily limit."],
         why="Abhishek asked for searching beyond the set sources.",
         asked="Abhishek",
         before=("08-assessment-agentic-ai-cloud.png", "Today: an unscored measure says what's missing, with no way to look for it."),
         after=("C-technology-page.png", "Design: 'Find evidence' beside each unscored measure.")),
    dict(n="11", title="Import a list of emerging technologies, or add one by hand", status="Built",
         what=["Upload an Excel laid out like Tata's 'New Emerging Technologies' tab (a blank template can be downloaded).",
               "Names are matched to the radar's technologies, including different wordings (for example 'ZTNA' and 'zero trust network access'). Nobody has to merge rows by hand; anything unsure stays separate.",
               "Nothing is saved until you confirm. Your values (commercial availability, domain, TRL) are kept as Tata's choice."],
         why="Abhishek asked for technologies to be added by hand, starting from Tata's list.",
         asked="Abhishek",
         before=None,
         after=("E-import.png", "Design: the review step, before anything is saved.")),
    dict(n="12", title="A Point of View that says where the value lands", status="Built",
         what=["Up to two use cases per fabric, from the collected evidence, each with its value levers written as Nick's chain: operating change → metric → financial effect → evidence needed → next step.",
               "The path to scale, using Tri's seven steps (Evaluation → Customer zero → Proof of concept → One customer → Beta → Roadmap → Investment), recorded by people.",
               "Maturity (TRL) and commercial availability with their reasons and numbered sources. Market size and other numbers link to their sources too.",
               "A finance screen (contribution margin, payback, break-even), worked out only from figures Tata enters. The AI never writes a financial figure."],
         why="Agreed at the review: each Point of View carries the path to scale. Nick's finance note sets the levers. Abhishek asked for sources behind market size.",
         asked="Midpoint review; Nick; Abhishek; Hasan (TRL)",
         before=("05-pov-agentic-ai.png", "Today: a long text, scores by fabric, no use cases, levers or sources list."),
         after=("D-point-of-view.png", "Design: verdict, the four answers, where the value lands, path to scale, finance screen, and sources.")),
    dict(n="13", title="Frontier: the leaders' view, at its own address", status="Built",
         what=["A separate web address for executives, showing only Frontier: the 2×2 with a fabric filter and zoom, a table beside it, the technologies not yet placed, and each Point of View, read-only.",
               "Nothing else is reachable from it: no setup, no runs, no buttons that cost money.",
               "Publishing, lenses, the frontier line and recording commitments are settled when it's built."],
         why="Agreed at the review: Frontier is the 2×2 a business leader sees. Abhishek asked for separate views for admins and users.",
         asked="Midpoint review; Abhishek",
         before=None,
         after=("G-frontier.png", "Design: Frontier at its own address.")),
]

DECISIONS = [
    "Detection stays the core; each Point of View carries the path to scale; no macro model.",
    "Tata's own categories are used: commercial availability, domain and sub-domain, TRL.",
    "An imported list means 'these are emerging technologies we care about'; each row's own commercial availability is kept.",
    "People's choices are kept and never overwritten by a new run: moves, overrides, hand scores, imports, yes/no on nascent.",
    "The AI never writes a financial figure; contribution, payback and break-even come only from figures Tata enters.",
    "Disruption threat and Serviceable capture are entered by Tata.",
    "Cloud and Security stay separate fabrics for now.",
    "Leaders get their own web address (Frontier).",
    "The Briefing stays as it is; the next collection fills it again.",
]

ASKS = [
    "Past cases to test against: the FY27 Q1 radar entries and technologies with a known outcome (Named Data Networking, post-quantum cryptography, Skywave).",
    "Confirmation or correction of each fabric's two value levers and its main blockers (from Nick's note).",
    "Indicative margins, loss rates and delivery costs per fabric, as ranges, and the ROIC proxy when available.",
    "Comments on the design mock-ups in this document.",
]

LATER = [
    "Logins, together with a shared environment on Tata's AWS.",
    "Calibration against Tata's past cases, and the operating guide for hand-over.",
    "Licensed sources through data providers or MCPs.",
    "Combining Cloud and Security (on hold). Collection on a timer will not be built.",
]


def shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    tc.append(shd)


def table(doc, header, rows, widths):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shade(c, "041A4A")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
    t.autofit = False
    layout = OxmlElement("w:tblLayout"); layout.set(qn("w:type"), "fixed")
    t._tbl.tblPr.append(layout)
    for i, w in enumerate(widths):
        t.columns[i].width = Inches(w)
        for cell in t.columns[i].cells:
            cell.width = Inches(w)
    return t


def image(doc, path: Path, caption: str):
    if not path.exists():
        p = doc.add_paragraph(f"[{path.name} not found]"); return
    doc.add_picture(str(path), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(caption); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p.runs: r.italic = True; r.font.size = Pt(9); r.font.color.rgb = MUTED


def main():
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
    for s in ("Heading 1", "Heading 2", "Heading 3", "Title"):
        doc.styles[s].font.color.rgb = NAVY
    sec = doc.sections[0]
    for side in ("left_margin", "right_margin"): setattr(sec, side, Inches(1))

    doc.add_paragraph("Tech Radar: changes after the midpoint review", style="Title")
    p = doc.add_paragraph("Tata Communications × Wharton Mack Institute · Emerging Technology Radar"); p.runs[0].font.color.rgb = MUTED
    p = doc.add_paragraph(VERSION); p.runs[0].bold = True

    doc.add_heading("About this document", level=1)
    doc.add_paragraph("This is the running list of every change we are making after the midpoint review of 13 October, "
                      "built from the review itself, the notes that followed from Abhishek, Ankur and Nick, and our own review of them. "
                      "We will review it with you as the work progresses.")
    for b in ["For each change: what changes, why, and who asked for it.",
              "'Before' shows today's portal. 'After' shows a design mock-up until the change is built; it is then replaced by a screenshot of the real screen.",
              "Numbers in the mock-ups are illustrative. Numbers in the text come from the radar's last full run (6 October).",
              "Status: Planned → In progress → Built → Live."]:
        doc.add_paragraph(b, style="List Bullet")

    doc.add_heading("Summary", level=1)
    table(doc, ["#", "Change", "Asked by", "Status"], [(i["n"], i["title"], i["asked"], i["status"]) for i in ITEMS], [0.4, 3.4, 1.8, 0.9])

    doc.add_heading("Decisions taken since the review", level=1)
    for d in DECISIONS: doc.add_paragraph(d, style="List Bullet")

    doc.add_heading("The changes, one by one", level=1)
    for it in ITEMS:
        doc.add_heading(f"{it['n']}. {it['title']}", level=2)
        p = doc.add_paragraph(); r = p.add_run(f"Status: {it['status']}   ·   Asked by: {it['asked']}"); r.font.color.rgb = MUTED; r.font.size = Pt(9.5)
        doc.add_paragraph().add_run("What changes").bold = True
        for w in it["what"]: doc.add_paragraph(w, style="List Bullet")
        p = doc.add_paragraph(); p.add_run("Why: ").bold = True; p.add_run(it["why"])
        if it["before"]:
            doc.add_paragraph().add_run("Before").bold = True
            for name, caption in (it["before"] if isinstance(it["before"], list) else [it["before"]]):
                image(doc, BEFORE / name, caption)
        else:
            p = doc.add_paragraph(); p.add_run("Before: ").bold = True; p.add_run("this doesn't exist today.")
        built = [AFTER_BUILT / n for n in AFTER_CAPTIONS if n.startswith(f"item-{it['n']}-") or n == f"item-{it['n']}.png"]
        built = [b for b in built if b.exists()]
        if built:
            doc.add_paragraph().add_run("After (built)").bold = True
            for b in built:
                image(doc, b, AFTER_CAPTIONS[b.name])
        elif it["after"]:
            doc.add_paragraph().add_run("After (design mock-up)").bold = True
            image(doc, AFTER_DESIGN / it["after"][0], it["after"][1])
        else:
            p = doc.add_paragraph(); p.add_run("After: ").bold = True; p.add_run("no new screen; the change is behind the scenes and shows as numbers on existing pages.")

    doc.add_heading("What we need from Tata", level=1)
    for a in ASKS: doc.add_paragraph(a, style="List Number")

    doc.add_heading("Later, not in this round", level=1)
    for l in LATER: doc.add_paragraph(l, style="List Bullet")

    doc.add_heading("Change history", level=1)
    table(doc, ["Version", "Date", "What changed"], HISTORY, [0.8, 1.2, 4.5])

    doc.save(OUT)
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
