"""Needs python-docx (pip install python-docx in any venv). Builds the client change log: Tech Radar - changes after the midpoint review.docx.

For each change: where it came from (the email, document or page), what changed, why, before → after in numbers,
a workflow diagram where it helps (make_diagrams.py), and the screens before and after.
Re-run after each change: update ITEMS, N (the numbers, from the live radar) and HISTORY."""
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
DIAGRAMS = ROOT / "screenshots/diagrams"
OUT = ROOT / "Tech Radar - changes after the midpoint review.docx"
NAVY = RGBColor(0x04, 0x1A, 0x4A)
MUTED = RGBColor(0x49, 0x4A, 0x52)

VERSION = "Version 5 · 21 October 2026"
HISTORY = [("1", "20 Oct 2026", "First version: every change agreed after the midpoint review, with today's screens and design mock-ups."),
           ("2", "20 Oct 2026", "Change 0 built: technologies say how solid their assessment is, a technology's result in each fabric stays "
                                "with the technology, plain names on every screen. Real screens replace its mock-up."),
           ("3", "21 Oct 2026", "Changes 1–13 built. Real screens replace their mock-ups. Change 5 tried both ways first; two measures moved to "
                                "per fabric as a result. Tata's list taken up to the review step."),
           ("4", "21 Oct 2026", "Rearranged so each change says where it came from, with before → after numbers and workflow diagrams. "
                                "Numbers now come from the full run of 21 Oct: every technology assessed again and every Point of View "
                                "rewritten with numbered sources. Tata's list imported (885 added, 115 joined). Frontier gains Tata's "
                                "stage buckets."),
           ("5", "21 Oct 2026", "A line-by-line check against the review, the emails and Nick's note found gaps in changes 7–13; all are "
                                "built now: Tata's buckets on the Technologies page with moves in one choice; Nick's two levers, "
                                "bottlenecks, ladder and finance arithmetic; Frontier's editions, frontier line, lens, assumptions, "
                                "evidence and leaders' commitments. Tata's list: 27 proposed matches back at review. Lever chains and "
                                "Points of View refreshed. Change 14: every screen read again as a first-time user and put in plain "
                                "words; the radar suggests which blockers its pages show.")]

# The numbers in the text, from the live radar on 21 Oct (6 Oct is the run before these changes).
N = dict(
    old_techs=147, old_calls="4,474", old_scored=50, old_unscored=50,  # the two measures Tata enters left out
    techs_all="2,490", calls_full=772, techs_full=248, per_tech=3, scored_full=84, unscored_full=16, reused_pct=25,
    calls_recorded="3,623", classified="2,490", nascent=158, proposed_subdomains=246, skills=18,
    placed=188, held=61, ready=1, thin="1,357", noev=883, off=0,
    povs=249, pov_sources=249, avg_sources=9,
    fr_placed=399, fr_techs=188, fr_mature=87,
    b_research=346, b_pilot=195, b_early="1,108", b_mature=524, on_list=967, on_list_added=885, on_list_joined=82,
    two_levers_before=50, two_levers_after=100, capital_after=100, blocker_pairs=301, pairs=516,
)

# Where the changes came from; each change cites these by their code.
SOURCES = [
    ("S1", "Hasan's email “Midpoint Review Summary (Oct 13)”",
     "The agreed record of the 13 Oct review, with the replies from Abhishek, Nick and Ankur (Ankur's three tests, 17 Oct)."),
    ("S2", "Email “Mid Point Summary – Zoom”", "Zoom's summary of the 13 Oct meeting, and Nick's note of 19 Oct."),
    ("S3", "The review deck (Tata_Tech_Radar_Midpoint_Review_Oct13.pdf)", "19 pages; the page is given each time."),
    ("S4", "Nick's note (Tata_Finance_Value_Levers_v2.docx)", "Value levers, blockers to test, and finance, revised 20 Oct."),
    ("S5", "Tata's list (Emerging-technologies October 2026.xlsx)",
     "Attached by Abhishek to S1: 1,000 rows in the 'New Emerging Technologies' tab."),
    ("S6", "Our working sessions on the comments, 20 Oct", "Where we went through S1–S5 point by point and agreed how to build each."),
    ("S7", "Our walk-through of the portal, 21 Oct",
     "Every screen read again as someone using it for the first time: what each part is, what to do there and where it's used."),
]

# Built screens, in reading order, with their captions: item-N.png or item-N-<screen>.png
AFTER_CAPTIONS = {
    "item-0-technologies.png": "After: 'Tracked' replaces 'Up to date'. Each row shows its priority and how many of its measures had "
                               "enough evidence to score.",
    "item-0-technology.png": "After: a technology's page says how solid its assessment is, and each fabric shows its own count.",
    "item-0-skills.png": "After: skills by plain name, in the order the radar uses them; code names only under Technical details.",
    "item-0-scoring-tab.png": "After: every Scoring method tab has a title and a one-line purpose.",
    "item-0-sources.png": "After: Sources opens on the ones in use; 'Show all' lists the rest.",
    "item-1-bulk-bar.png": "After: tick rows, and a bar acts on all of them: switch off, switch on, move, or assess with the cost shown first.",
    "item-1-switched-off.png": "After: a switched-off technology says when, in the time zone it was switched off in; its pages are still collected.",
    "item-2-written-time.png": "After: a Point of View written from India shows India's time; older ones show US Central.",
    "item-3-skill-map.png": "After: every skill in the step that uses it, calls that carry several skills as dashed boxes, and what each used last time.",
    "item-4-operations.png": "After: each run in Operations' history says how many tokens it used, and how many were reused.",
    "item-4-collection.png": "After: a collection's page shows its AI use: calls, tokens sent, reused and written back.",
    "item-5-engine.png": "After: Weights & Grid chooses how an assessment calls the AI: stacked (recommended) or one measure per call.",
    "item-5-stacked.png": "After: a skill's page shows how it's sent inside a stacked call, its own parts highlighted, the reused parts first.",
    "item-6-fabric-tab.png": "After: one tab per fabric on the technology's page: the priority (override with a reason), and the measures that "
                             "need a person first: score by hand, accept the gap, Tata's entries, find evidence.",
    "item-6-briefing.png": "After: the Briefing opens on the two to-do lists, Before scoring and Before publishing, counted by technology.",
    "item-7-technologies.png": "After: Tata's buckets across the top with their counts, Emerging least mature first, and on each row a choice that moves it to another bucket or domain.",
    "item-8-answers.png": "After: four answers on every technology, each saying where it came from (here Tata's list), with what the radar's own reading suggests, Why? (reason and pages) and Change.",
    "item-8-classification.png": "After: Setup › Classification: Tata's domains and sub-domains, with the AI's proposed sub-domains to accept, "
                                 "merge or rename.",
    "item-9-nascent.png": "After: a possibly nascent technology, with the reason and the quote that flagged it; a person answers yes or no.",
    "item-10-find-evidence.png": "After: Find evidence and Add a link wherever evidence is thin, with the cost and today's search budget first.",
    "item-11-import.png": "After: reviewing Tata's list: each proposed match beside the row's own values and the technology it would join, with a warning when several rows would join one. Nothing is saved until it's confirmed.",
    "item-12-value-tab.png": "After: a fabric's use cases with Nick's two levers and the capital needed, what could stop it scaling, how far Tata has got on the path to scale, and the finance card.",
    "item-12-pov.png": "After: the Point of View's short first view: the verdict, the four answers, the recommendation and where the value lands; the rest folds open, with one numbering of sources.",
    "item-13-frontier.png": "After: Frontier shows the published edition: the 2×2 with the frontier line, Growth or Defence, Tata's buckets, what moved since the last edition, the assumptions and the evidence.",
    "item-14-use-cases.png": "After: each part of a fabric tab says what it is, what you do there and where it shows. A lever reads as one line; its five steps open under 'How it makes money, step by step'.",
    "item-14-blockers.png": "After: 'What could stop it scaling': the fabric's blockers to tick, with the ones the radar read on a page marked, each with why, the words and the page.",
    "item-14-change-step.png": "After: the step Tata has reached, and who set it; 'Change step' turns the steps into a choice with Save. Steps whose proof isn't written yet share one line.",
    "item-14-owner.png": "After: who owns it at Tata and what's next, with the four states and what each one means, always in view.",
    "item-14-mechanisms.png": "After: editing a setting opens it in place; the others keep their definitions in view.",
    "item-14-operations.png": "After: each step says when it last ran, in the reader's time zone, and what it did.",
    "item-14-briefing.png": "After: the Briefing's three cards fold closed and still say what waits.",
}

# status: Planned · In progress · Built · Live
ITEMS = [
    dict(n="0", title="Clearer screens, first fixes", status="Built",
         source=[("S6", "a walk through the portal as a first-time user found 11 places where it confuses; the quick ones were "
                        "fixed first, the rest folded into the changes below")],
         what=["'Up to date' is now 'Tracked', and no longer suggests 'complete'. Every technology shows its priority and how many "
               "of its measures had enough evidence to score; amber marks those with no priority, or under half scored.",
               "A technology's result in one fabric opens on the technology's own page, as a tab, instead of under Operations, so "
               "you don't lose your place.",
               "Plain names replace internal codes: skills and measures by name, evidence by collection date; codes only under "
               "Technical details.",
               "Every Scoring method page has a title and a one-line purpose; the sources page opens on the sources in use."],
         why="Users said the portal is still confusing, and the changes below add more to it, so it had to be clear first.",
         metrics=[("Technologies shown as 'Up to date', in green", "146, although 58% of their measures were unscored",
                   "None: each says 'Tracked', with its priority and 'x of y measures scored'"),
                  ("Where a technology's result in a fabric opens", "Under Operations (you lose your place)",
                   "A tab on the technology's own page")],
         before=[("02-technologies.png", "Before: 146 technologies said 'Up to date', in green, although most measures were unscored."),
                 ("08-assessment-agentic-ai-cloud.png", "Before: a technology's result opened under Operations, with measure codes "
                  "and 'unscorable'.")]),
    dict(n="1", title="Switch a technology off from the list", status="Built",
         source=[("S1", "'Things to build': switch a technology off from the technology list, committed at the review"),
                 ("S6", "how it behaves: its pages are still collected, and it asks for a look when new pages arrive")],
         what=["An on/off switch on every row of the technology list; tick several rows to switch them off or on at once.",
               "A switched-off technology isn't assessed or shown to leaders, but its pages are still collected, so nothing is lost. "
               "It says when it was switched off.",
               "If it gathers new pages after being switched off (10 by default, a setting), the list asks for a look."],
         why="Agreed at the midpoint review.",
         metrics=[("Switching off 10 technologies", "Open each one, then Manage, then the switch: 10 pages",
                   "Tick 10 rows, one click")],
         before=[("02-technologies.png", "Before: the switch existed only inside each technology's page.")]),
    dict(n="2", title="When a Point of View was written: date, time and time zone", status="Built",
         source=[("S6", "asked when we went through the comments"),
                 ("S3", "page 6: what leaders see is dated ('published 6 Oct')")],
         what=["Each Point of View shows the date and time it was written, in the time zone of the person who wrote it."],
         why="A reader needs to know how fresh a Point of View is, and readers sit in India and the US.",
         metrics=[("A Point of View's written time", "'Oct 6'", "'Oct 21, 2026, 7:45 AM GMT+5:30'")],
         before=[("05-pov-agentic-ai.png", "Before: 'Written Oct 6', with no time.")]),
    dict(n="3", title="One picture of where each AI instruction is used", status="Built",
         source=[("S1", "action item for Akshay: a diagram of where each prompt is used")],
         what=["A page shows every instruction the AI follows (we call them skills) in the step that uses it, the calls that carry "
               "several skills together, and what each used in its last run.",
               "It prints on one page, so it can be shared."],
         why="So anyone can see what the AI is asked to do, where, and at what cost.",
         metrics=[("Skills shown together, in the order they run", "None: one page per skill", "{skills}, on one page")],
         before=[("09-skills.png", "Before: a list of skills, each explained on its own page.")]),
    dict(n="4", title="AI usage recorded for every call", status="Built",
         source=[("S6", "our plan to measure the cost of every change before and after, and keep it under control")],
         what=["Every AI call records the tokens it sent, reused and wrote back, with its step, run and technology. Operations, each "
               "run's page and each skill's page show them.",
               "The fixed opening of a call (its instructions and evidence) is marked for reuse, so the next call that starts the "
               "same way pays a tenth of the price for that part.",
               "Each skill has a switch for whether the AI may reason before it answers. Reasoning is paid for but never shown, so "
               "it's on only where it helps: scoring, value levers and the Point of View."],
         why="Without it, nobody could say what a run or a change costs.",
         metrics=[("AI calls with their tokens recorded", "None", "Every call: {calls_recorded} since 20 Oct"),
                  ("Tokens sent that were reused at a tenth of the price (21 Oct run)", "Nothing reused", "{reused_pct}%")],
         before=[("11-operations.png", "Before: run history showed the number of AI calls, not their size or cost.")]),
    dict(n="5", title="A leaner assessment", status="Built",
         source=[("S6", "why the assessment called the AI about 30 times per technology, and the plan to change it")],
         what=["Before, each technology got one AI call per measure per fabric, about 30 in all, each sending all of its evidence again.",
               "Now one call answers the questions about the technology as a whole (maturity, market size, growth, which fabrics it "
               "matters to, metrics to watch, and its domain, TRL and availability), and one call per relevant fabric answers that "
               "fabric's questions. The evidence is sent once and reused.",
               "Both ways were tried on the same 6 technologies, with the same AI and the same pages, before switching. Commercial "
               "adoption and use-case breadth came out too high when judged for the technology as a whole, so they're judged per fabric.",
               "Each assessment may now read up to 500,000 tokens of evidence (roughly a 750-page book), up from 300,000; "
               "the AI's limit is 1,000,000."],
         why="The same evidence was being sent about 30 times per technology, and the same maturity question asked once per fabric.",
         metrics=[("AI calls per technology", "About 30 ({old_calls} for {old_techs} on 6 Oct)",
                   "About {per_tech} ({calls_full} for {techs_full} on 21 Oct)"),
                  ("The same 6 technologies, both ways: AI calls", "204", "19"),
                  ("The same 6: tokens at the full price", "4,287,124", "367,485 (about 12 times fewer)"),
                  ("The same 6: measures the evidence could answer", "78%", "93%"),
                  ("Every assessed technology: measures the evidence could answer (the two Tata enters left out)",
                   "{old_scored}% (6 Oct, with the earlier AI model)", "{scored_full}% (21 Oct)")],
         diagram=("engine", "Before, every measure was its own call; now one call per technology and one per fabric."),
         before=[("08-assessment-agentic-ai-cloud.png", "Before: one assessment page per technology and fabric, built from one call per measure.")]),
    dict(n="6", title="The innovation team's decisions before publishing (Gate 2)", status="Built",
         source=[("S3", "pages 9, 11 and 14: Gate 2 overrides are audited and carry a reason; 'handle unscored measures'"),
                 ("S2", "Hasan: place a technology by hand when the scores can't place it"),
                 ("S1", "the not-yet-placed list stays visible beside the grid")],
         what=["Each fabric has a tab on the technology's page with its priority. A person can override it, with a reason; the "
               "computed priority stays beside it, and Undo restores it.",
               "Measures the evidence couldn't score come first, each with three ways to settle it: score it by hand (with a reason), "
               "accept the gap, or find evidence.",
               "Disruption threat and Serviceable capture are entered by Tata: public pages almost never answer them.",
               "The Briefing opens on two to-do lists: Before scoring (Gate 1) and Before publishing (Gate 2).",
               "A person's choices are kept, and a new run never overwrites them."],
         why="'An unowned score is overruled' (S3, page 3). On 6 Oct, 58% of measures couldn't be scored from public pages, "
             "and nothing could be done about them.",
         metrics=[("Measures the evidence couldn't score (the two Tata enters left out)",
                   "{old_unscored}% (6 Oct), with nothing to do about them",
                   "{unscored_full}% (21 Oct), each with score by hand, accept the gap, or find evidence"),
                  ("Disruption threat and Serviceable capture", "Asked of the AI: 98% unscored", "Entered by Tata"),
                  ("Priority set by a person", "Not possible", "Override with a reason; the computed one stays visible")],
         diagram=("process", "The whole process now: the two gates are where people decide."),
         before=[("08-assessment-agentic-ai-cloud.png", "Before: unscored measures said what was missing, but nothing could be done about them.")]),
    dict(n="7", title="Technologies organised the way Tata thinks about them: in Tata's buckets", status="Built",
         source=[("S1", "Shashank: mature and emerging views, nascent technologies first; a move between them remembered "
                        "across runs"),
                 ("S5", "Tata's buckets, the 'Commercial Availability' column: Research, Pilot, Early commercial, Mature"),
                 ("S6", "'Tracked' means assessed; Emerging and Mature as views over the buckets, least mature first")],
         what=["The Technologies page shows Tata's buckets across the top, in order, with how many technologies are in each: "
               "Research → Pilot → Early commercial → Mature. One click shows a bucket. A bucket Tata adds appears by itself.",
               "Moving a technology to another bucket is one choice on its row (and on its own page); the move is kept "
               "across runs and can be undone. Several can be moved at once.",
               "Emerging (Research, Pilot, Early commercial) and Mature are views over the buckets, least mature first.",
               "Every technology says where it is and why: placed on the grid, held beside it, ready to assess, thin evidence, "
               "no evidence yet, or switched off. 'On Tata's list' and 'Found by the radar only' are filters too, and every "
               "filter shows its counts."],
         why="Tata works in these buckets. Mature technologies shouldn't crowd out emerging ones, and a technology that "
             "isn't assessed should say why.",
         metrics=[("Seeing the radar in Tata's buckets", "Not possible: one column and a drop-down",
                   "Research {b_research} → Pilot {b_pilot} → Early commercial {b_early} → Mature {b_mature}, one click each"),
                  ("Moving a technology between buckets", "Hidden: tick it, then a bar at the bottom",
                   "One choice on its row; kept across runs; Undo"),
                  ("Technologies that say why they're where they are", "None: 1,003 just said 'Not assessed'",
                   "All {techs_all}: {placed} placed, {held} held beside the grid, {ready} ready to assess, {thin} with "
                   "thin evidence, {noev} with no pages yet (most from Tata's list), {off} switched off"),
                  ("Technologies on Tata's list", "Only the {noev} added from it counted", "{on_list}: {on_list_added} added from it and {on_list_joined} the radar already had")],
         before=[("02-technologies.png", "Before: 1,003 'Not assessed', with no reason on any row, and no buckets.")]),
    dict(n="8", title="Every technology classified: commercial availability, domain, TRL, evidence", status="Built",
         source=[("S5", "Tata's own categories: commercial availability, domain and sub-domain, TRL"),
                 ("S1", "Shashank: mature and emerging views"),
                 ("S2", "Akshay's action: represent or filter by TRL"),
                 ("S3", "page 11: the evidence floor counted in independent sources, not pages")],
         what=["Every technology, not only the assessed ones, gets Tata's categories: commercial availability (Research, Pilot, "
               "Early commercial, Mature), domain and sub-domain, and TRL (1–9).",
               "Each answer says where it came from: Tata's list (with the file and date), a person, the assessment, or the "
               "pages. Where Tata's list or a person set it, the radar's own reading is shown beside it with its reason and "
               "pages ('its pages suggest Pilot').",
               "The AI also judges how solid the evidence is: how many independent sources, of what kind, and how credible. That, "
               "not a page count, decides when a technology is ready to assess.",
               "The lists are editable in Setup. Sub-domains the AI proposes wait for a person to accept, merge or rename them."],
         why="So Tata sees the radar in its own categories, and early technologies aren't hidden behind a page count.",
         metrics=[("Technologies with availability, domain and TRL", "None", "{classified} of {techs_all}"),
                  ("Agreement with Tata's own list (a sample)", "No classification to compare",
                   "Domain 88%; availability within one step 79%; TRL within one level 9 of 11")],
         before=[("03-technology-agentic-ai.png", "Before: a technology's page showed scores, but no maturity, availability or domain.")]),
    dict(n="9", title="Possible nascent technologies, flagged for a person to confirm", status="Built",
         source=[("S2", "Shashank: nascent technologies shouldn't be hidden below the evidence floor"),
                 ("S1", "Ankur's first test: spot disruptive technologies very early, especially ones Tata doesn't know")],
         what=["The AI flags a technology that looks new and shows a strong early sign (a large funding round, a solid research "
               "result, a first deployment, a spin-out, a new standard), even from a single page, and quotes it.",
               "A person answers yes or no, from the list or the Briefing, with the reason and the page in view. Yes moves it to "
               "Research or Pilot (saying first if that replaces Tata's value); no is kept until a new page flags it again."],
         why="One deployment can be the signal (the Named Data Networking story), and a page count would hide it.",
         metrics=[("Possibly nascent technologies flagged for a person", "None", "{nascent}, settled one click each from the list")],
         before=[]),
    dict(n="10", title="Find evidence", status="Built",
         source=[("S1", "Abhishek: open web search beyond the set sources"),
                 ("S3", "page 9: handle unscored measures at Gate 2")],
         what=["A button wherever evidence is missing: on a technology with thin evidence or none, a measure that couldn't be "
               "scored, or a fabric with no use case. It leads on a technology with no pages yet.",
               "It searches the web for what's missing, skips pages already known, reads the new ones like any collected page, "
               "and re-runs only the part that was missing. 'Add a link' beside it takes a page someone already knows.",
               "Each page found counts as its own site when the evidence is judged. Every search stays on the page: what was "
               "searched, what was filed, what was set aside and why.",
               "Only a person starts it; the cost is shown first, and there's a daily limit."],
         why="The set sources can't cover everything, especially for technologies that came in from Tata's list.",
         metrics=[("Ways to look for missing evidence", "None", "Find evidence (web search) and Add a link, wherever evidence is thin"),
                  ("A test search (Foundation models, from Tata's list)", "No pages", "2 pages filed, its evidence judged enough to assess")],
         diagram=("find-evidence", "Find evidence searches; Add a link starts from a page a person knows. Both re-run only the gap."),
         before=[("08-assessment-agentic-ai-cloud.png", "Before: an unscored measure said what was missing, with no way to look for it.")]),
    dict(n="11", title="Import a list of emerging technologies, or add one by hand", status="Built",
         source=[("S1", "Abhishek: add technologies by hand, starting from Tata's list"),
                 ("S5", "the 'New Emerging Technologies' tab"),
                 ("S6", "how the upload works: nothing saved until confirmed; Tata's values kept as Tata's")],
         what=["Upload an Excel laid out like Tata's 'New Emerging Technologies' tab (a blank template can be downloaded).",
               "Names are matched to the radar's technologies. Exact names cost nothing; the AI proposes the rest, and never folds "
               "a narrower technology into a broader one ('AI in Education' stays apart from 'Artificial intelligence').",
               "The review shows each row's own values and description beside the technology it would join (its pages and "
               "classification), and warns when several rows would join one technology. Nothing is saved until a person confirms.",
               "One technology can also be added by hand, with its availability, domain and TRL, the cost shown first."],
         why="Tata already tracks technologies the collection may not have found.",
         metrics=[("Tata's 1,000 rows", "Matched by hand",
                   "88 matched exactly, 885 added; 27 proposed matches back at review after the first review let narrower "
                   "technologies fold into broad ones")],
         diagram=("import", "Importing Tata's list: a person reviews before anything is saved."),
         before=[]),
    dict(n="12", title="A Point of View that says where the value lands", status="Built",
         source=[("S1", "decided at the review: each Point of View carries the path to scale"),
                 ("S4", "Nick's value levers, five rules, blockers to test, commitment ladder and finance screens"),
                 ("S2", "Hasan: maturity (TRL) stated in the Point of View"),
                 ("S1", "Abhishek: link the sources for market size and other numbers")],
         what=["Up to two use cases per fabric, from the evidence, each with Nick's two levers (lever 1 on contribution, lever 2 "
               "on the cost of delivery), written as his chain: operating change → metric (from the fabric's key metrics) → "
               "financial effect → evidence needed → next step, and the capital it needs.",
               "The bottlenecks standing in the way, picked by people from the fabric's 'main blockers to test'.",
               "The path to scale in Tri's seven steps, with Nick's evidence for each rung in view; when the evidence for the next "
               "step is in hand, the radar flags it.",
               "Finance worked out only from figures Tata enters: contribution (for protection levers, revenue at stake × margin × "
               "the drop in loss rate, as in Nick's PQC example), payback with a cash line, and break-even. The AI never writes a "
               "figure; until there are figures it says 'for Tata to fill in'.",
               "Maturity (TRL) and commercial availability with their reasons, and every number cited to its page, numbered once "
               "for the whole Point of View. A short first view: verdict, the four answers, the recommendation and the value; "
               "the rest folds open."],
         why="A Point of View has to say where the value lands for Tata, and every claim has to point to its page.",
         metrics=[("Use cases with two levers", "{two_levers_before}%", "{two_levers_after}%"),
                  ("Use cases that say the capital needed", "89%", "{capital_after}%"),
                  ("Nick's PQC example, worked by the radar", "Not possible", "$2.8m a year protected, payback about 21 months (his figures)"),
                  ("Points of View with numbered sources", "0 of {old_techs}", "{pov_sources} of {povs}"),
                  ("Length of a Point of View's first view (Agentic AI)", "10,189 px, everything open", "1,541 px; the rest folds open")],
         diagram=("value", "A use case's value as Nick's chain, and the path to scale."),
         before=[("05-pov-agentic-ai.png", "Before: a long text, scores by fabric, no use cases, levers or sources.")]),
    dict(n="13", title="Frontier: the leaders' view, at its own address", status="Built",
         source=[("S1", "decided at the review: Frontier is the 2×2 a business leader sees; Abhishek: separate views for admins "
                        "and users; Shashank: a table beside the 2×2, fabric filters and zoom"),
                 ("S3", "pages 5, 6, 9, 11, 13 and 14: the frontier, editions, overrides, lenses, assumptions, evidence, and what "
                        "a leader records")],
         what=["A separate web address for leaders that shows only Frontier, read-only: the 2×2 by fabric and by Tata's bucket "
               "(emerging first), a table beside it, what isn't placed yet and why, and each Point of View.",
               "Editions: the innovation team publishes; leaders see only the latest edition, never work in progress, with what "
               "moved since the last one and why.",
               "The frontier line (technologies nothing beats on both axes) with the ones near it; a Growth or Defence lens "
               "(Disruption threat, entered by Tata); the assumptions in force; and the evidence behind this edition.",
               "What a leader records: owner and next action with a date, stage, bottleneck and resources committed, recorded in "
               "Tech Lens and shown on Frontier as Undefined → Defined → Aligned → Integrated."],
         why="Leaders need one clear screen, without the workbench, and a record of what they commit.",
         metrics=[("Addresses", "One admin portal", "Two: Tech Lens for the team, Frontier for leaders"),
                  ("What leaders see", "Live data, mid-run", "A dated edition: {fr_placed} placements for {fr_techs} technologies")],
         diagram=("addresses", "The same portal at two addresses; the leaders' address can only read."),
         before=[]),
    dict(n="14", title="Plain words on every screen, and blockers read from the pages", status="Built",
         source=[("S7", "every screen read as a first-time user: parts that didn't say what they are or what to do, people's "
                        "names used as labels, buttons with no word on what they do, and a step that ran without saying so"),
                 ("S4", "the blockers to test in each fabric, which the radar now looks for in the pages")],
         what=["Each part of a technology's fabric tab now says what it is, what you do there and where it shows up, and folds "
               "closed: 'Use cases: where the value lands', 'What could stop it scaling', 'How far Tata has got with it', "
               "'Who owns it at Tata, and what's next' and 'Finance'.",
               "A use case's two levers read as one line each; the full chain opens under 'How it makes money, step by step'.",
               "How far Tata has got: one line gives the step reached and who set it; 'Change step' turns the steps into a "
               "choice with Save. Steps whose proof Tata hasn't written yet share one line.",
               "The radar now suggests which of a fabric's blockers its pages show, each with why, the page's own words and the "
               "page. A person ticks the ones that apply; a suggestion is never picked by itself.",
               "The Briefing's to-do lists and 'Publish the edition' fold closed and still say what waits. Operations says when "
               "each step last ran and what it did; every button says Started or Done, or why not.",
               "Names of people are used only as credits; codes (P1–P6, H1–H3) carry their meaning; every time shows in the time "
               "zone it was done in, never UTC; a technology's evidence splits into findings (events picked out of pages) and pages.",
               "Fixed: after Classify ran, technologies with a page visited twice still counted as waiting."],
         why="Someone opening the portal for the first time has to see what each part is and what to do there, without a guide.",
         metrics=[("Length of a technology's page (Agentic AI)", "5,872 px, everything open", "4,261 px; each part folds"),
                  ("Length of the Briefing", "3,951 px, both lists open", "2,515 px; the three cards fold"),
                  ("Length of the signal list", "8,728 px", "2,626 px"),
                  ("People's names used as labels", "15", "0; credits only, in 'How to read this page'"),
                  ("Fabric results with blockers suggested from the pages", "0 of {pairs}", "{blocker_pairs} of {pairs}"),
                  ("Waiting to be classified after Classify ran", "40, every time", "0")],
         diagram=None,
         before=[("item-14-before-use-cases.png", "Before: every lever's five boxes open, and the bottlenecks with no word on what they are for."),
                 ("item-14-before-path.png", "Before: seven 'Set at' buttons with no instructions, and 'What a leader records' with four bare states."),
                 ("item-14-before-briefing.png", "Before: both to-do lists open at the top of the Briefing."),
                 ("item-14-before-operations.png", "Before: Organize and Classify looked the same before and after they ran."),
                 ("item-14-before-mechanisms.png", "Before: editing one setting hid every other definition.")]),
]

DECISIONS = [
    "Detection stays the core; each Point of View carries the path to scale; no macro model.",
    "Tata's own categories are used: commercial availability, domain and sub-domain, TRL.",
    "An imported list means 'these are emerging technologies we care about'; each row's own commercial availability is kept.",
    "People's choices are kept and never overwritten by a new run: moves, overrides, hand scores, imports, yes or no on nascent.",
    "The AI never writes a financial figure; contribution, payback and break-even come only from figures Tata enters.",
    "Disruption threat and Serviceable capture are entered by Tata.",
    "Cloud and Security stay separate fabrics for now.",
    "Leaders get their own web address (Frontier).",
    "Assessments use stacked calls (change 5), after trying both ways; commercial adoption and use-case breadth are judged per "
    "fabric (signed off 21 Oct).",
    "Frontier shows a published edition, never live data; the innovation team publishes.",
    "When several rows of an imported list join one technology, none of their values is applied; a narrower technology is "
    "never folded into a broader one.",
    "The radar may suggest blockers from the pages; only a person picks them (signed off 21 Oct).",
]

WAITING = [
    "Review the 27 proposed matches of Tata's list again, on the new review screen, and confirm.",
    "Confirm or replace the assumptions in force: the first edition (21 Oct) shows the deck's two examples, from Setup › "
    "Assumptions. Publish the next edition when they're right.",
    "Answer yes or no on the {nascent} possibly nascent technologies.",
    "Tick the blockers that apply on each technology's fabric tab; those the radar read on a page are marked.",
    "Accept, merge or rename the {proposed_subdomains} sub-domains the AI proposed.",
    "Settle the measures that need a person, technology by technology, from the Briefing's Before publishing list.",
]

ASKS = [
    "Past cases to test against: the FY27 Q1 radar entries and technologies with a known outcome (Named Data Networking, "
    "post-quantum cryptography, Skywave).",
    "Confirmation or correction of each fabric's two value levers and its main blockers (from Nick's note, S4).",
    "Indicative margins, loss rates and delivery costs per fabric, as ranges, and the ROIC proxy when available.",
]

LATER = [
    "Splitting an umbrella term into its emerging part, such as SGP.32 within eSIM (S1).",
    "Tracking inflection points across runs (S1).",
    "Logins, together with a shared environment on Tata's AWS (S3, pages 11, 14, 17).",
    "Calibration against Tata's past cases, and the operating guide for hand-over (S3, pages 14, 17).",
    "Licensed sources through data providers or MCPs (S1).",
    "Combining Cloud and Security (on hold). Collection on a timer will not be built.",
]


def t(text: str) -> str:
    """Text with the numbers filled in."""
    return text.format(**N)


def shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    tc.append(shd)


def table(doc, header, rows, widths):
    tb = doc.add_table(rows=1, cols=len(header))
    tb.style = "Table Grid"; tb.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = tb.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shade(c, "041A4A")
    for row in rows:
        cells = tb.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = t(str(v))
    tb.autofit = False
    layout = OxmlElement("w:tblLayout"); layout.set(qn("w:type"), "fixed")
    tb._tbl.tblPr.append(layout)
    for i, w in enumerate(widths):
        tb.columns[i].width = Inches(w)
        for cell in tb.columns[i].cells:
            cell.width = Inches(w)
    return tb


def image(doc, path: Path, caption: str):
    if not path.exists():
        doc.add_paragraph(f"[{path.name} not found]"); return
    doc.add_picture(str(path), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(caption); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p.runs: r.italic = True; r.font.size = Pt(9); r.font.color.rgb = MUTED


def label(doc, text: str):
    doc.add_paragraph().add_run(text).bold = True


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
    doc.add_paragraph("Every change we made after the midpoint review of 13 October, built from the review itself, the emails "
                      "and notes that followed, and our own working sessions on them. Each change has:")
    for b in ["Where it came from: the email or document (S1–S7, listed below) and the point, page or person in it.",
              "What changed, in plain words, and why.",
              "Before → after, in numbers, and the screens before and after. A workflow diagram where it helps.",
              "Numbers come from the radar itself: 'before' from the run of 6 October, 'after' from the full run of 21 October."]:
        doc.add_paragraph(b, style="List Bullet")

    doc.add_heading("Where the changes came from", level=1)
    table(doc, ["", "Email or document", "What it is"], SOURCES, [0.4, 2.6, 3.5])

    doc.add_heading("Summary", level=1)
    table(doc, ["#", "Change", "Came from", "Status"],
          [(i["n"], i["title"], ", ".join(dict.fromkeys(s for s, _ in i["source"])), i["status"]) for i in ITEMS],
          [0.4, 3.6, 1.6, 0.9])

    doc.add_heading("How the radar works now", level=1)
    doc.add_paragraph("The radar's steps after these changes. Filled boxes are new or changed; the amber lanes are where a person decides.")
    image(doc, DIAGRAMS / "process.png", "The process, from collecting pages to the leaders' view.")

    doc.add_heading("The changes, one by one", level=1)
    for it in ITEMS:
        doc.add_heading(f"{it['n']}. {it['title']}", level=2)
        p = doc.add_paragraph(); r = p.add_run(f"Status: {it['status']}"); r.font.color.rgb = MUTED; r.font.size = Pt(9.5)
        label(doc, "Where it came from")
        for code, where in it["source"]:
            p = doc.add_paragraph(style="List Bullet"); p.add_run(f"{code}: ").bold = True; p.add_run(where)
        label(doc, "What changed")
        for w in it["what"]: doc.add_paragraph(t(w), style="List Bullet")
        p = doc.add_paragraph(); p.add_run("Why: ").bold = True; p.add_run(t(it["why"]))
        label(doc, "Before → after")
        table(doc, ["", "Before", "After"], it["metrics"], [2.0, 2.2, 2.3])
        if it.get("diagram"):
            label(doc, "How it works")
            image(doc, DIAGRAMS / f"{it['diagram'][0]}.png", it["diagram"][1])
        label(doc, "Screens")
        for name, caption in it["before"]:
            image(doc, BEFORE / name, caption)
        if not it["before"]:
            doc.add_paragraph("Before: this didn't exist.")
        built = [AFTER_BUILT / n for n in AFTER_CAPTIONS if n.startswith(f"item-{it['n']}-")]
        for b in [b for b in built if b.exists()]:
            image(doc, b, AFTER_CAPTIONS[b.name])

    doc.add_heading("Decisions taken since the review", level=1)
    for d in DECISIONS: doc.add_paragraph(d, style="List Bullet")

    doc.add_heading("Waiting for Tata's team, in the portal", level=1)
    for w in WAITING: doc.add_paragraph(t(w), style="List Number")

    doc.add_heading("What we need from Tata", level=1)
    for a in ASKS: doc.add_paragraph(a, style="List Number")

    doc.add_heading("Not in this round", level=1)
    for l in LATER: doc.add_paragraph(l, style="List Bullet")

    doc.add_heading("Change history", level=1)
    table(doc, ["Version", "Date", "What changed"], HISTORY, [0.8, 1.2, 4.5])

    doc.save(OUT)
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
