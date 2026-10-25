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

VERSION = "Version 19 · 22 October 2026"
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
                                "words; the radar suggests which blockers its pages show."),
           ("6", "21 Oct 2026", "Change 15: the Technologies page says how each group is decided, ticked technologies move "
                                "between groups with one menu, and Tata's list is called the catalog, on every screen and in "
                                "this document. Every screen retaken."),
           ("7", "21 Oct 2026", "Change 16: a Point of View's use cases become a table that says, in full, the investment "
                                "each needs, how far Tata has got and whether it pays; every use case asked again for a plain "
                                "title. Change 17: the Point of View's scores say what each one asks and open the "
                                "measures behind them in a panel on the right; the page uses its full width and stacks on a "
                                "phone. 'Frontier' is called the leaders' view on every screen."),
           ("8", "21 Oct 2026", "Change 18, the first screen of a screen-by-screen review against Don Norman's design "
                                "principles: a technology's page opens on its verdict and one 'Waiting on you' list, with "
                                "the fabrics, the evidence and its history on their own tabs; one page count; every choice "
                                "people made, with Undo, in one place."),
           ("9", "21 Oct 2026", "Change 19: a technology's fabric tab, by the same principles: the fabric bar stays in "
                                "view, each part says how it stands, done parts start folded, the priority is a sentence, "
                                "use cases are compact, and Tata's plan (owner, step, blockers) reads in the order the "
                                "owner's record needs."),
           ("10", "21 Oct 2026", "Change 20: Tata's plan reworked after your review: the path to scale is the one process, "
                                 "drawn as a track; the owner states are a status (the commitment) worked out from a "
                                 "checklist of what's recorded."),
           ("11", "21 Oct 2026", "Change 21: finance set aside until Tata has discussed it, on every screen; the next step's "
                                 "proof is entered on the path to scale itself; every dropdown's arrow set in from its edge. "
                                 "This completes the technology page's review."),
           ("12", "21 Oct 2026", "Change 22: the Briefing, the Points of View list and one Point of View, by the same "
                                 "principles: to-do first and readable closed, one findings count with two tabs, what "
                                 "changed since the edition; the list sorted by priority with filters; a Point of View "
                                 "that says when it's out of date. The Point of View skill says Tata, not TCL."),
           ("13", "21 Oct 2026", "Change 23, after your review of change 22: the Briefing's To do is one strip of three "
                                 "columns, and the findings tabs are New and Old."),
           ("14", "21 Oct 2026", "Change 24, after your review of change 23: To do's open list as cards, the examples "
                                 "folded; Publish to leaders says what it sends; each Point of View says which version "
                                 "leaders see."),
           ("15", "21 Oct 2026", "Changes 25–28: Operations and Setup by the same principles, kept simple; and Tata's "
                                 "plan reaches the Point of View in full, shown on a worked example."),
           ("16", "21 Oct 2026", "Change 29, after your review of the Point of View: About this technology, for readers new "
                                 "to it, above the recommendation."),
           ("17", "22 Oct 2026", "Change 30, a fix after your review: Rewrite on a Point of View's page now shows the new "
                                 "version when it's done."),
           ("18", "22 Oct 2026", "Changes 31–36, from the 21 Oct sync (S9): the collection page by the same principles; "
                                 "market size as a band; metrics to watch checked at the next assessment; leaders' opens "
                                 "and prints counted; fabrics people worked on always assessed again; 86 sources, and "
                                 "the radar compared with the catalog."),
           ("19", "22 Oct 2026", "Change 37, from your question on seeing a run whole: one run from collecting to "
                                 "publishing, in six steps, with where it stands now, on the run page, Operations and "
                                 "the Briefing. Change 38: judging evidence has no token limit any more; it judges "
                                 "catalog technologies first, and never skips a collection's technologies. Change 39: "
                                 "a Status filter on Technologies, and Add evidence (links and files) on a "
                                 "technology, through to its Point of View. Change 40: catalog technologies are found "
                                 "on pages by name; Add evidence made clearer and tested on real pages; About this "
                                 "technology fills a wide page.")]

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
    povs_catalog=22,
    uc_before=652, jargon_before=196, uc_after=607, jargon_after=90, jargon_bare=6,
)

# Where the changes came from; each change cites these by their code.
SOURCES = [
    ("S1", "Hasan's email “Midpoint Review Summary (Oct 13)”",
     "The agreed record of the 13 Oct review, with the replies from Abhishek, Nick and Ankur (Ankur's three tests, 17 Oct)."),
    ("S2", "Email “Mid Point Summary – Zoom”", "Zoom's summary of the 13 Oct meeting, and Nick's note of 19 Oct."),
    ("S3", "The review deck (Tata_Tech_Radar_Midpoint_Review_Oct13.pdf)", "19 pages; the page is given each time."),
    ("S4", "Nick's note (Tata_Finance_Value_Levers_v2.docx)", "Value levers, blockers to test, and finance, revised 20 Oct."),
    ("S5", "Tata's list of emerging technologies (Emerging-technologies October 2026.xlsx)",
     "Attached by Abhishek to S1: 1,000 rows in the 'New Emerging Technologies' tab. Called the catalog on the screens."),
    ("S6", "Our working sessions on the comments, 20 Oct", "Where we went through S1–S5 point by point and agreed how to build each."),
    ("S7", "Our walk-through of the portal, 21 Oct",
     "Every screen read again as someone using it for the first time: what each part is, what to do there and where it's used."),
    ("S8", "Our review of every screen against Don Norman's design principles, from 21 Oct",
     "One screen at a time, most used first: can a reader see what it is, what to do and what happened (discoverability, "
     "signifiers, mapping, feedback, the conceptual model). Nothing in how the radar works changes."),
    ("S9", "Hasan's email “Oct 21 - Sync Summary: Ankur's Three Tests, Demo & Deployment” (22 Oct), and the Zoom summary",
     "What was agreed on 21 Oct: market size as bands, an introduction in each Point of View, metrics flagged when they "
     "cross, view counts, wider sources and the comparison with the catalog, and the deployment."),
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
    "item-8-answers.png": "After: four answers on every technology, each saying where it came from (here the catalog), with what the radar's own reading suggests, Why? (reason and pages) and Change.",
    "item-8-classification.png": "After: Setup › Classification: Tata's domains and sub-domains, with the AI's proposed sub-domains to accept, "
                                 "merge or rename.",
    "item-9-nascent.png": "After: a possibly nascent technology, with the reason and the quote that flagged it; a person answers yes or no.",
    "item-10-find-evidence.png": "After: Find evidence and Add a link wherever evidence is thin, with the cost and today's search budget first.",
    "item-11-import.png": "After: reviewing the catalog's file: each proposed match beside the row's own values and the technology it would join, with a warning when several rows would join one. Nothing is saved until it's confirmed.",
    "item-12-value-tab.png": "After: a fabric's use cases with Nick's two levers and the capital needed, what could stop it scaling, how far Tata has got on the path to scale, and the finance card.",
    "item-12-pov.png": "After: the Point of View's short first view: the verdict, the four answers, the recommendation and where the value lands; the rest folds open, with one numbering of sources.",
    "item-13-frontier.png": "After: the leaders' view shows the published edition: the 2×2 with the frontier line, Growth or Defence, Tata's buckets, what moved since the last edition, the assumptions and the evidence.",
    "item-14-use-cases.png": "After: each part of a fabric tab says what it is, what you do there and where it shows. A lever reads as one line; its five steps open under 'How it makes money, step by step'.",
    "item-14-blockers.png": "After: 'What could stop it scaling': the fabric's blockers to tick, with the ones the radar read on a page marked, each with why, the words and the page.",
    "item-14-change-step.png": "After: the step Tata has reached, and who set it; 'Change step' turns the steps into a choice with Save. Steps whose proof isn't written yet share one line.",
    "item-14-owner.png": "After: who owns it at Tata and what's next, with the four states and what each one means, always in view.",
    "item-14-mechanisms.png": "After: editing a setting opens it in place; the others keep their definitions in view.",
    "item-14-operations.png": "After: each step says when it last ran and what it did.",
    "item-15-groups.png": "After: 'How the groups work' gives each group's rule, names the catalog's file and says how to move technologies.",
    "item-15-bar.png": "After: rows show commercial availability and domain as plain text; ticked rows move together with Move to… (commercial availability, the catalog, possibly nascent).",
    "item-15-technology.png": "After: a technology's page says whether it's in the catalog and who changed that, with Undo.",
    "item-17-why-panel.png": "After: Why opens the measures behind a fabric's scores in a panel on the right; the page moves left to make room, and closing the panel puts it back.",
    "item-17-scores.png": "After: the full name of each score, what it asks and the measures it comes from; Why opens, in place, each measure's score, the reasoning and its pages.",
    "item-16-use-cases.png": "After: one row per use case, in plain words: the investment it needs and why, how far Tata has got on its path to scale, and whether it pays; the note under the table says what those mean and where they're entered.",
    "item-14-briefing.png": "After: the Briefing's three cards fold closed and still say what waits.",
    "item-18-overview.png": "After: a technology's page opens on Overview: the Point of View's verdict, its priority in each fabric, what waits on you, then what the radar judged.",
    "item-18-waiting.png": "After: Waiting on you, fabric by fabric: first what needs a person before publishing, then what the owner's record lacks; each item opens the fabric at the part.",
    "item-18-priority.png": "After: each fabric leads with its priority, why (how soon and how big) and the three scores, with P1–P6 and the horizon said in words.",
    "item-18-path.png": "After: the path to scale as a bar of seven steps, with the step reached and the next in full; every step's proof is one click away.",
    "item-19-fabric-tab.png": "After: a fabric tab: the fabric bar stays in view, the priority is a sentence, and each part's title says how it stands (amber to settle, grey not recorded, green done).",
    "item-19-use-cases.png": "After: use cases, compact: sources folded into a count, the capital in a word with its reason one click away, each lever on one line.",
    "item-22-briefing.png": "After: the Briefing leads with To do; each closed card lists what waits, and the publish card says what changed since the edition. Below, what the radar found, with the window menu on the line it changes and two tabs.",
    "item-23-briefing.png": "After: To do as one strip of three columns, each listing what waits first; the New and Old tabs below.",
    "item-24-todo.png": "After: an open column's list as cards, two or three across, each with its one action; the technologies behind it fold under Which ones.",
    "item-24-publish.png": "After: Publish to leaders says leaders see only what's published, which edition they see now, and exactly what a publish now would send.",
    "item-24-pov.png": "After: a Point of View rewritten after the edition says leaders still see the earlier version, and links to Publish.",
    "item-25-operations.png": "After: Operations' tabs, and its six steps numbered in order, each saying who moves it on: you start it, it runs by itself, or it waits for you.",
    "item-26-signal-form.png": "After: Delete sits inside a signal's Edit form, behind a confirm; switching a signal off pauses it instead.",
    "item-27-open-questions.png": "After: Setup's menu in four groups, and Mark settled on each open question, where the question is read.",
    "item-29-about-this-technology.png": "After: About this technology, between the four answers and the recommendation, saying it comes from general knowledge.",
    "item-30-rewritten.png": "After: the page shows the new version once Rewrite is done, and says so under the button.",
    "item-31-collection.png": "After: problems first in words, four steps that each say where they stand, times in Central time, and the done sources folded.",
    "item-37-run-steps.png": "After: one run in six steps, from collecting to publishing. The Now line says it stopped at step 3 and what comes next; the step that waits for you has the main button, with its cost.",
    "item-37-operations.png": "After: Operations opens on the latest run, in the same six steps and words as the run page, with every button the six cards had.",
    "item-37-older-run.png": "After: an older run shows what happened until the next collection, with no buttons; the assessment runs that read its pages fold into one line.",
    "item-37-briefing.png": "After: the Briefing says in one line where the latest run stands, with a link to every step.",
    "item-39-held.png": "After: a Status filter beside the others, and the counts above the list read as links; 'Assessed, placed' and 'Assessed, not placed' add up to the Assessed group.",
    "item-39-add-evidence.png": "After: Add evidence on a technology: links and files, what happens next, and the cost on Start; a bad link is refused, saying why.",
    "item-39-real-flex-ethernet-flexe-form.png": "After: Add evidence on FlexE, run for real: two links and the OIF's FlexE PDF, a real Choose files button, what happens next, and the cost on Start.",
    "item-39-real-k0s-done.png": "After: k0s with 'Only judge its evidence': the steps done, what came of it, and where to look next.",
    "item-40-organize-step.png": "After: a run's Organize step merges names and links catalog technologies named on its pages, saying what it found; Link known names on all pages runs the catch-up.",
    "item-40-technology.png": "After: a catalog technology says the names it's looked for by on pages, with Edit names.",
    "item-27-settings.png": "After: Settings with the crawler internals behind Technical details, the time-zone line following the rule, and unsaved edits flagged.",
    "item-22-povs.png": "After: the Points of View list says what keeps them current, sorts by highest priority, and filters by fabric, priority and newer pages.",
    "item-22-pov.png": "After: a Point of View says when pages arrived after it was written and what to do, offers one way back, and labels the evidence reason as the latest look.",
    "item-21-path.png": "After: the next step's proof is entered on the path itself: Customer zero needs a measured cost per outcome, with Enter… beside it.",
    "item-21-dropdowns.png": "After: every dropdown's arrow is set in from its rounded edge, with room kept for it after the text.",
    "item-20-plan.png": "After: Tata's plan: the commitment as a status in the title; where Tata is on its path to scale as one track; then a checklist of what's recorded, each with its action.",
    "item-19-finance.png": "After: Finance leads with Enter the figures, says when figures are asked for and what the next step needs now, and lists what the figures need once.",
    "item-18-history.png": "After: History says what the latest assessment read, of all its pages, and lists every choice people made, who, when and why, with Undo.",
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
               "To move technologies to another bucket, tick them and choose Move to… (change 15); one technology moves "
               "on its own page too. The move is kept across runs and can be undone.",
               "Emerging (Research, Pilot, Early commercial) and Mature are views over the buckets, least mature first.",
               "Every technology says where it is and why: placed on the grid, held beside it, ready to assess, thin evidence, "
               "no evidence yet, or switched off. 'In the catalog' and 'Not in the catalog' are filters too, and every "
               "filter shows its counts."],
         why="Tata works in these buckets. Mature technologies shouldn't crowd out emerging ones, and a technology that "
             "isn't assessed should say why.",
         metrics=[("Seeing the radar in Tata's buckets", "Not possible: one column and a drop-down",
                   "Research {b_research} → Pilot {b_pilot} → Early commercial {b_early} → Mature {b_mature}, one click each"),
                  ("Moving a technology between buckets", "Hidden: a bar at the bottom, never mentioned",
                   "Tick, then Move to…, said on the page; kept across runs; Undo"),
                  ("Technologies that say why they're where they are", "None: 1,003 just said 'Not assessed'",
                   "All {techs_all}: {placed} placed, {held} held beside the grid, {ready} ready to assess, {thin} with "
                   "thin evidence, {noev} with no pages yet (most from the catalog), {off} switched off"),
                  ("Technologies in the catalog", "Only the {noev} added from it counted", "{on_list}: {on_list_added} added from it and {on_list_joined} the radar already had")],
         before=[("02-technologies.png", "Before: 1,003 'Not assessed', with no reason on any row, and no buckets.")]),
    dict(n="8", title="Every technology classified: commercial availability, domain, TRL, evidence", status="Built",
         source=[("S5", "Tata's own categories: commercial availability, domain and sub-domain, TRL"),
                 ("S1", "Shashank: mature and emerging views"),
                 ("S2", "Akshay's action: represent or filter by TRL"),
                 ("S3", "page 11: the evidence floor counted in independent sources, not pages")],
         what=["Every technology, not only the assessed ones, gets Tata's categories: commercial availability (Research, Pilot, "
               "Early commercial, Mature), domain and sub-domain, and TRL (1–9).",
               "Each answer says where it came from: the catalog (with the file and date), a person, the assessment, or the "
               "pages. Where the catalog or a person set it, the radar's own reading is shown beside it with its reason and "
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
         why="The set sources can't cover everything, especially for technologies that came in from the catalog.",
         metrics=[("Ways to look for missing evidence", "None", "Find evidence (web search) and Add a link, wherever evidence is thin"),
                  ("A test search (Foundation models, from the catalog)", "No pages", "2 pages filed, its evidence judged enough to assess")],
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
         diagram=("import", "Importing the catalog: a person reviews before anything is saved."),
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
    dict(n="13", title="The leaders' view, at its own address", status="Built",
         source=[("S1", "decided at the review: Frontier is the 2×2 a business leader sees; Abhishek: separate views for admins "
                        "and users; Shashank: a table beside the 2×2, fabric filters and zoom"),
                 ("S3", "pages 5, 6, 9, 11, 13 and 14: the frontier, editions, overrides, lenses, assumptions, evidence, and what "
                        "a leader records")],
         what=["A separate web address for leaders, the leaders' view (called Frontier at the review), read-only: the 2×2 by fabric and by Tata's bucket "
               "(emerging first), a table beside it, what isn't placed yet and why, and each Point of View.",
               "Editions: the innovation team publishes; leaders see only the latest edition, never work in progress, with what "
               "moved since the last one and why.",
               "The frontier line (technologies nothing beats on both axes) with the ones near it; a Growth or Defence lens "
               "(Disruption threat, entered by Tata); the assumptions in force; and the evidence behind this edition.",
               "What a leader records: owner and next action with a date, stage, bottleneck and resources committed, recorded in "
               "Tech Lens and shown in the leaders' view as Undefined → Defined → Aligned → Integrated."],
         why="Leaders need one clear screen, without the workbench, and a record of what they commit.",
         metrics=[("Addresses", "One admin portal", "Two: Tech Lens for the team, the leaders' view for leaders"),
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
    dict(n="15", title="Groups that say how they're decided, moves between them, and the catalog", status="Built",
         source=[("S7", "the Technologies page read again: no way to move technologies between the groups, no word on which "
                        "list 'Tata's list' was or how a technology lands in a group, a menu in every row, and the name "
                        "'Tata's list' itself"),
                 ("S5", "the file the catalog comes from")],
         what=["'Tata's list' is now called the catalog: Tata's own list of emerging technologies, from S5. The groups use the "
               "deck's words: Emerging, New to Tata, Mature, Blind spots, Possibly nascent, and In catalog with thin evidence.",
               "'How the groups work', under the groups, gives each one's rule: Emerging or Mature from commercial "
               "availability; New to Tata and Blind spots are those not in the catalog. It names the catalog's file, its date "
               "and how many technologies came from it.",
               "Ticked technologies move together with one menu, Move to…: another commercial availability (Emerging or "
               "Mature), into or out of the catalog, or yes or no on possibly nascent. Each move is a person's choice, kept by "
               "later runs and imports, with who, when and Undo. Thin evidence can't be moved by hand; Find evidence moves it.",
               "A technology's own page says whether it's in the catalog, with Add to the catalog or Take out of the catalog.",
               "Rows show commercial availability and domain as plain text, with where each came from; the menus in every row "
               "are gone.",
               "Points of View say 'from Tata's catalog'; the {povs_catalog} that said 'Tata's list' were rewritten."],
         why="A group helps only if someone new can see what puts a technology in it and how to move it.",
         metrics=[("Ways to move ticked technologies between groups", "Commercial availability or domain",
                   "Also into or out of the catalog, and yes or no on possibly nascent"),
                  ("Menus in each row", "2", "0; one bar for the ticked rows"),
                  ("Which list, and how each group is decided, said on the page", "No", "Yes: the file, its date and each group's rule"),
                  ("Points of View saying 'Tata's list'", "{povs_catalog}", "0")],
         diagram=None,
         before=[("item-15-before-list.png", "Before: groups named after 'Tata's list', with nothing saying which list it is or how "
                                             "a technology lands in a group, and a menu in every row."),
                 ("item-15-before-bar.png", "Before: ticked rows could change commercial availability or domain only.")]),
    dict(n="16", title="A Point of View's use cases, in a table anyone can read", status="Built",
         source=[("S7", "a Point of View read as a leader would: titles in Tata's product names and acronyms, nine source "
                        "numbers in a row, 'light capital' with no reason, and 'Tata's step' and 'Finance: not entered yet' "
                        "with no word on what they are, what's missing, where it's entered or whether it matters yet"),
                 ("S4", "the capital each use case needs, and the path to scale and finance figures from Nick's note")],
         what=["The use cases are a table: one row per use case, with the fabric, the use case, the investment it needs, how "
               "far Tata has got and whether it pays.",
               "Investment needed: light, moderate or heavy, with the reason in one sentence (the full reason on hover).",
               "How far Tata has got: the step on the path to scale and its number ('Evaluation, step 1 of 7'), the next "
               "step, and the blockers a person picked; or 'Not recorded yet'.",
               "Does it pay?: contribution, payback and break-even once Tata's figures are in; until then 'Not known yet', "
               "with what's needed, or the step from which it's asked for (Proof of concept), and for admins 'Enter figures'.",
               "A note under the table says what the last two columns mean, who records them and where.",
               "Each use case shows up to three source numbers, then '+n' for the rest.",
               "Every use case was asked again with a plain title: a Tata product is named only beside what it is "
               "('Tata's Vayu cloud'), and acronyms are spelled out. Scores didn't change."],
         why="A leader reading a Point of View has to see what each use case is, what it costs to start and what's still "
             "needed to know whether it pays, without a guide.",
         metrics=[("Use case titles naming a Tata product or acronym", "{jargon_before} of {uc_before}, none saying what it is",
                   "{jargon_after} of {uc_after}, all but {jargon_bare} saying what it is"),
                  ("Source numbers shown per use case", "Up to 10 in a row", "Up to 3, then '+n'"),
                  ("What 'step' and 'finance' mean, and where they're entered", "Not said", "Said once, under the table"),
                  ("Reason for the investment level", "Stored, never shown", "One sentence in each row")],
         diagram=None,
         before=[("item-16-before-use-cases.png", "Before: fragments per fabric: product names, rows of source numbers, "
                                                  "'light capital', and 'Tata's step' and 'Finance: not entered yet' unexplained.")]),
    dict(n="17", title="A Point of View's scores, explained where they are, on a page that uses its width", status="Built",
         source=[("S7", "a Point of View read again: the scores gave no detail, 'Details' led to the technology's working "
                        "page, much of the page was empty space, and it didn't fit a phone")],
         what=["Scores carry their full names (Market potential, Strategic fit, Adoption readiness), and a note says what each "
               "asks and which measures it comes from: how big the prize could be, how well it fits Tata, how ready it is "
               "to adopt now.",
               "Why, on a fabric's row, opens a panel on the right with each measure behind its three scores: its score, its "
               "weight, the reasoning, its pages and what argues against it. On a wide screen the page moves left to make "
               "room; closing the panel puts the page back as it was. 'Details', which left for the technology's working "
               "page, is gone; admins get 'Change a score or the priority' in the panel instead.",
               "The page uses its width: the recommendation and the scores sit side by side, and the use cases and the folds "
               "below run across the page. The narrow column with empty space beside it is gone.",
               "On a phone, the scores and the use cases become one card per fabric, every value labelled, with nothing to "
               "scroll sideways.",
               "The leaders' screen is called the leaders' view on every screen; the name Frontier, which no screen "
               "explained, is gone."],
         why="A leader asks 'why this score?' on the Point of View itself; the answer belongs there, readable on any screen.",
         metrics=[("Where 'why this score' is answered", "On the technology's working page, 4,500 px long",
                   "In a panel beside the scores; closing it restores the page"),
                  ("What each score asks, said on the page", "No", "Yes, with the measures it comes from"),
                  ("Empty space beside the use cases (1440 px wide)", "About 1,500 px tall", "None"),
                  ("Use case columns hidden off-screen on a phone", "3 of 5", "0: one card per fabric")],
         diagram=None,
         before=[("item-17-before-scores.png", "Before: three short score names, 'Details' leading away, and no word on what a score rests on."),
                 ("item-17-before-page.png", "Before: the scores alone in a narrow right column, with empty space below them.")]),
    dict(n="18", title="A technology's page opens on its verdict and what waits on you", status="Built",
         source=[("S8", "the technology page, read against the design principles: the conclusion was at the bottom, what needs "
                        "a person was spread over every fabric, three different page counts, the same help text in every "
                        "part, and the status said four times")],
         what=["The page has four tabs under its name: Overview, Fabrics, Evidence and History. Above them, as before: the "
               "fabrics, where it is on the radar's journey and the Next step with its cost.",
               "Overview leads with the Point of View's verdict (Open, Rewrite), its priority in each fabric with the horizon "
               "in words, and how many measures had enough evidence.",
               "Waiting on you: one list, fabric by fabric. First what needs a person before the next edition goes to "
               "leaders (figures to enter, measures the pages couldn't score, suggested use cases, a moved override, "
               "finance figures); then what the owner's record lacks (how far Tata has got, the blockers, an owner, what "
               "the next step needs). Each item opens the fabric's tab at that part. A fabric tab's number now counts all "
               "of these, not only unscored measures.",
               "Each fabric leads with its priority, why (how soon and how big) and the three scores, which used to be "
               "folded at the bottom. Each part says in one line what it is; More gives what you do and where it shows.",
               "The path to scale is a bar of seven steps, with the step reached and the next in full; every step's proof "
               "is one click away, and Change step lists them all as before.",
               "One page count. A page collected again because it changed is listed once, with how many times it was "
               "collected; History says what the latest assessment read of them ('112 of its 113 pages, 1 arrived after').",
               "History lists every choice people made about the technology, newest first, in plain words: who (a person, "
               "or the catalog file), when, why, with Undo; replaced and undone choices on request.",
               "Plain words: 'your figure' where it said 'Tata's figure' (the reader is Tata); the first owner state is "
               "'No owner yet', not 'Undefined'; two pages from one source carry their dates; '1 page', not '1 pages'."],
         why="Someone opening a technology asks what we think, what they need to do, and why; the page now answers in that "
             "order, on one screen, and nothing that was there is gone.",
         metrics=[("Page height, an assessed technology at 1440 px", "4,500 px, one page", "Overview 1,406 px; Fabrics 2,833 px"),
                  ("Where the Point of View's verdict sits", "About 3,700 px down", "First, under the tabs"),
                  ("Where what needs a person is listed", "Spread over 6 parts in each fabric",
                   "One list on Overview; each item opens its part"),
                  ("A fabric tab's number, Agentic AI in Cloud", "None (counted unscored only; 2 figures waited)", "2"),
                  ("Page counts on the page", "Three: 112, 113, 122", "One: 113"),
                  ("Help text repeated in each fabric", "About 360 words", "One line per part; More for the rest"),
                  ("Who decided what, and Undo", "Beside each value, where it is", "Also in one list, on History")],
         diagram=None,
         before=[("item-18-before-top.png", "Before: the first screen: status, counts and the model's answers; no verdict, and "
                                            "nothing saying what waits on you."),
                 ("item-18-before-bottom.png", "Before: the Point of View's verdict, about 3,700 px down, after every part of a fabric.")]),
    dict(n="19", title="A fabric tab that says how each part stands, in the order you work through it", status="Built",
         source=[("S8", "the fabric tab, read against the same principles: the fabric scrolled out of view, parts didn't say "
                        "whether they were done, the owner's record came after the two things it depends on, use cases "
                        "were long, pointers weren't links, and Finance's main action was a small link at the bottom")],
         what=["The fabric bar (each fabric with its priority and what's to settle) stays at the top of the screen while the "
               "parts scroll; 'Not assessed in IoT or Media' sits beside it.",
               "Each part's title says how it stands, in the words Waiting on you uses: amber when something needs settling, "
               "grey when it isn't recorded yet, green when it's done. Parts that are done start folded.",
               "The priority is a sentence: 'P2 because it arrives mid-term (how soon: 6 of 10, from 2 of 2 measures) and the "
               "prize is big (how big: 8 of 10, from 2 of 4 measures)'.",
               "Use cases are compact: sources folded into '4 sources', the capital in a word with 'why' one click away, "
               "each lever on one line; 'How it makes money, step by step' still opens under each.",
               "Tata's plan for it, one part, holding the owner, how far Tata has got and what could stop it scaling "
               "(reworked in change 20).",
               "Pointers are links: 'enter it under Finance' opens Finance and scrolls to it; 'Setup › Fabrics' and "
               "'Setup › Path to scale' open those pages.",
               "Finance leads with Enter the figures. It says figures are asked for from Proof of concept (step 3), and what "
               "the next step needs from it now; until a figure is worked out, what they need is listed once."],
         why="A fabric tab is where people do the work; each part now says whether it waits on them, in the order they do it.",
         metrics=[("Fabric tab height, Agentic AI in Cloud, 1440 px", "2,833 px", "2,637 px"),
                  ("Use cases, two of them (1440 / 400 px)", "656 / 1,649 px", "491 / 1,154 px"),
                  ("Which fabric you're in, scrolled to Finance", "Only the headings' 'in Cloud'", "The fabric bar, always in view"),
                  ("Parts that say how they stand", "None",
                   "Measures, Tata's plan and Finance always; Use cases when a suggestion waits"),
                  ("Owner's record order", "Blockers, step, owner (the reverse of what it needs)", "Owner, step, blockers"),
                  ("Pointers that are links", "0 of 5", "5 of 5")],
         diagram=None,
         before=[("item-19-before-top.png", "Before: the fabric buttons at the top only, the priority as a row of numbers, every part open."),
                 ("item-19-before-plan.png", "Before: blockers, then the path, then the owner, as three separate parts, and Finance's action a small link at the bottom.")]),
    dict(n="20", title="Tata's plan: one process, and a status that says what's recorded", status="Built",
         source=[("S8", "your review of change 19: the owner states (No owner yet, Defined, Aligned, Integrated) were drawn as "
                        "steps, like the path to scale beneath them, so the section read as two processes; only the path "
                        "to scale is a process")],
         what=["Where Tata is: the path to scale, Tata's process, is the only progress track: a dot per step, filled to the "
               "step reached, the next one ringed (down the screen on a phone). Under it: the step reached with Change step "
               "and Undo, what the next step needs with a link to where it's entered, and every step's proof one click away.",
               "The owner states are a status, not steps: the commitment, in the part's title, with how much is recorded "
               "('Commitment: No owner yet · 1 of 4 recorded'). The leaders' view keeps the same four names.",
               "What's recorded: a checklist of the four things that raise the commitment, each ticked or not, with its "
               "action in its row: the step reached; owner and next action (Record, Change, Undo); what could stop it "
               "scaling (Pick blockers… opens the checklist, with the pages' suggestions and their quotes, in place); "
               "people, budget or a trial. One line says what each level means: Defined, Aligned, Integrated.",
               "Nothing was dropped: every action and Undo works as before."],
         why="One thing on the page should look like a process: the one Tata walks through. How much of the plan is on record "
             "is a status, and now reads as one.",
         metrics=[("Progress tracks in the part", "Two (the owner states and the path to scale)", "One: the path to scale"),
                  ("The commitment shown as", "A row of four steps", "A status in the title, with '1 of 4 recorded'"),
                  ("What raises the commitment", "Said in the states' captions", "A checklist, each row with its action"),
                  ("Tata's plan in Cloud, 1440 / 400 px", "881 / 1,849 px", "550 / 953 px")],
         diagram=None,
         before=[("item-20-before-plan.png", "Before: the owner states drawn as four steps above the path to scale, so the part "
                                             "read as two processes.")]),
    dict(n="21", title="Finance set aside until Tata has discussed it", status="Built",
         source=[("S8", "your review of the fabric tab: the finance card asked an emerging technology for retail-style inputs "
                        "(volume, unit price, revenue displaced) it can't have yet, without saying what they were for")],
         what=["Finance (contribution, payback, break-even, from Nick's note, S4) is set aside on every screen until Tata has "
               "discussed how it wants to judge an emerging technology's business case: the fabric tab's Finance part, "
               "Setup › Finance (its address now says it's set aside), the fabrics' finance defaults, the Point of View's "
               "'Does it pay?' column and its finance fold, and the leaders' view, which shows the Point of View's parts.",
               "Nothing asks for it meanwhile: the before-publishing list and Waiting on you no longer list finance inputs, "
               "and the Point of View's writer isn't given finance. Figures already entered are kept, and the code is "
               "kept, so it can come back as it was or changed.",
               "The proof each step on the path needs is still recorded, now on the path itself: under 'Where Tata is', the "
               "next step lists what it needs, with Enter… beside each piece a person records (Customer zero: a measured "
               "cost per outcome; Proof of concept: a named buyer, a budget, a price). 'Proof for <step> is in hand' still "
               "flags it, and a note alone no longer calls for figures.",
               "Every dropdown in the portal (25 of them) has its arrow set in from the rounded edge, with room kept for "
               "it after the text; the browser's own arrow sat against the edge."],
         why="Ask for a number only when the technology's stage can have one, and say what it's for. Until Tata has decided "
             "what an emerging technology's business case should hold, the honest screen asks for nothing.",
         metrics=[("Finance inputs asked of an Evaluation-stage technology, per fabric", "11 fields (13 for a protection lever)", "None"),
                  ("Where the next step's proof is entered", "In the finance form, under 'Evidence for the next step'",
                   "Beside the next step, on the path"),
                  ("Screens that show finance", "6", "0 (kept, switched off)")],
         diagram=None,
         before=[("item-21-before-finance.png", "Before: the finance form on an Evaluation-stage technology: revenue, volume, "
                                                "unit price, revenue it displaces, costs and margin, with the next step's proof among them.")]),
    dict(n="22", title="The Briefing and the Points of View, read first-time", status="Built",
         source=[("S8", "the Briefing, the Points of View list and one Point of View, read against the same principles")],
         what=["Briefing: it leads with To do. The three cards (before scoring, before publishing, publish the edition) "
               "list what waits even when closed, row by row, in place of '4 things to settle · 196 items', a sum that "
               "counted one technology several times.",
               "Briefing: the publish card says what has changed since the edition leaders see ('Since then: 22 Points of "
               "View rewritten'), so it's clear when publishing would change anything.",
               "Briefing: what the radar found sits under its own heading. The window menu is on the line it changes "
               "('Last 7 days: 795 findings from 533 pages'), and Recent findings and Older articles found now are two "
               "tabs with their counts, in place of one list where the older ones came after 375 recent ones. A "
               "finding with no publication date says so.",
               "Points of View: sorted by highest priority (a technology's best fabric), or newest written; filtered by "
               "fabric, by priority (including 'no priority', now written on the card) and to those with newer pages.",
               "Points of View: 'Keeping them current' at the top: those written from an older assessment can be written "
               "now, with the cost; those with newer pages need their technology assessed again first, since a Point of "
               "View only explains its assessment. Rewrite all moves up beside them, away from 'Show more'.",
               "One Point of View: a line under the title says when pages arrived after it was written, and what to do. "
               "One way back, and 'Open the technology' only when the back link doesn't go there; the assessment run "
               "is under Technical details.",
               "One Point of View: the evidence card's reason is labelled 'at its latest look': the radar's most recent "
               "judgment can have read only the newest pages, so it isn't presented as the reason for all of them. The "
               "score legend is one line; the rest is in How to read this page.",
               "The Point of View skill (version 9) calls the company Tata, never TCL, even where its inputs say TCL. "
               "Points of View change as they're written again; none was rewritten now."],
         why="The Briefing is where work starts and the Points of View are what leaders act on: each now says first what "
             "waits, what's current and what isn't.",
         metrics=[("Briefing: what a closed to-do card says", "'4 things to settle · 196 items'", "Each thing that waits, by name"),
                  ("Briefing: findings counts on the page", "Three (795, 375, '20 of 795')", "One per tab, with the window on its line"),
                  ("Briefing: whether publishing would change anything", "Not said", "What changed since the edition"),
                  ("Points of View: order", "Newest written", "Highest priority first; filters by fabric, priority, newer pages"),
                  ("One Point of View: out of date", "Not said", "Said under the title, with what to do")],
         diagram=None,
         before=[("item-22-before-briefing.png", "Before: three folded cards saying only how many things to settle, and the "
                                                 "window menu in the corner."),
                 ("item-22-before-povs.png", "Before: the Points of View in the order they were written, with search only."),
                 ("item-22-before-pov.png", "Before: four links at the top, and no word that a page arrived after it was written.")]),
    dict(n="23", title="The Briefing's To do in one strip, and plain tab names", status="Built",
         source=[("S8", "your review of change 22: the three to-do cards took the whole page, and 'Older articles found now' "
                        "didn't say what 'now' meant")],
         what=["To do is one strip of three columns: Before scoring, Before publishing, Publish the edition. Each lists its "
               "first three items (and how many more), each opening where it's done; the publish column says when it was "
               "last published and what changed since.",
               "A column's title, or Open, shows its full list below the strip, with every in-place action as before (a "
               "run with its cost, Yes or No on each possibly nascent technology, Publish). The browser remembers which "
               "one you left open.",
               "The findings tabs are New and Old (a finding can be an article, a paper or a report, so not 'news'). Old "
               "was published more than 30 days before the radar collected it: background, not new; the line beside the "
               "tabs says so."],
         why="The Briefing's work list should be seen at a glance, not scrolled past; and a tab's name should say what "
             "decides it.",
         metrics=[("Height of To do (1440 px)", "About 400 px, three stacked cards", "172 px, one strip"),
                  ("Where the findings start (1440 px)", "About 760 px down", "About 530 px down"),
                  ("The tabs' names", "'Recent findings', 'Older articles found now'", "'New', 'Old', with what Old means beside them")],
         diagram=None,
         before=[("item-23-before-briefing.png", "Before: the three to-do cards stacked across the full width, pushing the "
                                                 "findings below the first screen.")]),
    dict(n="24", title="To do's open list as cards, and what Publish does", status="Built",
         source=[("S8", "your review of change 23: an opened column filled the page with white space and pushed it down; "
                        "and it wasn't clear what Publish sends, or which Point of View leaders see")],
         what=["An opened column's list shows as cards, two or three across (one on a phone): each with its sentence, a "
               "line on what it means and its one action. The technologies behind it fold under 'Which ones', with Yes "
               "or No on each possibly nascent one as before.",
               "The third column is 'Publish to leaders'. It says which edition leaders see and what changed since; "
               "opened, it says that leaders see only what's published, never work in progress, and exactly what a "
               "publish now sends: every Point of View and placement as it stands, and what isn't placed yet with the "
               "reason. Publishing rewrites nothing, costs no model calls and keeps every earlier edition.",
               "'Before publishing' says it's advice, not a gate: what's unsettled goes to leaders as it stands, with its "
               "reason.",
               "Each Point of View says which version leaders see: this one, or an earlier one in the latest edition, "
               "with a link that opens Publish on the Briefing. The Points of View list says how many were written "
               "after the edition."],
         why="A list that opens should keep the page in place; and the person publishing should know what leaders will "
             "see before and after they press it.",
         metrics=[("Height of the opened Before publishing list (1440 px)", "Over 750 px", "364 px"),
                  ("Which Point of View leaders see", "Not said anywhere outside the leaders' view",
                   "Said on every Point of View and on the list"),
                  ("What Publish sends", "'Freezes every placement and Point of View'",
                   "The counts: 249 Points of View, 399 placements, 117 not placed yet")],
         diagram=None,
         before=[("item-24-before-todo.png", "Before: Before publishing opened as full-width rows, each with five "
                                             "technologies, running past the first screen.")]),
    dict(n="25", title="Operations: the steps in order, and only what matters", status="Built",
         source=[("S8", "our review of Operations against the design principles: six steps drawn as tiles with no order, "
                        "a history of one line per Point of View, and the developers' service checks in plain view")],
         what=["The six steps are numbered in the order they run, and each says who moves it on: you start it "
               "(Collect), it runs by itself (Signals, Organize, Classify), or it waits for you (Assess, Points of View). "
               "Only a step that waits for you carries the main button.",
               "Points of View written since the edition leaders see are counted on their step, with a link to Publish.",
               "Overview, Collections and Assessment runs are tabs of one place. History groups Points of View written "
               "one at a time into one row ('4 written · 4 model calls'), and 'By skill' reads 'Cost by skill'.",
               "Service health shows only with Technical details on, or whenever the API or the database is down.",
               "One label for one action: 'Assess them again' everywhere. Redo scores on a run's page asks first and "
               "says what it changes: priorities may move, and leaders see that only after the next publish."],
         why="A process should read in its order, and a page should show the reader's work, not the system's.",
         metrics=[("Steps in order", "Six tiles, unnumbered", "Numbered 1–6, each saying who moves it on"),
                  ("Rows in History", "One per run: 59 on 21 Oct", "35, single Points of View grouped"),
                  ("Service health", "Always shown", "Only when Technical details is on, or something is down")],
         diagram=None,
         before=[("item-25-before-operations.png", "Before: six tiles with no order, and no word on which run by "
                                                   "themselves.")]),
    dict(n="26", title="Setup: grouped, with work moved out and safer controls", status="Built",
         source=[("S8", "our review of Setup: a flat menu of eleven kinds of thing, work living in Setup, hidden edit "
                        "controls, and actions too easy to trigger")],
         what=["The menu has four groups: what the radar reads, how it judges, Tata's frame, and the system.",
               "Work moved out of Setup: Import technologies sits under Technologies ('Import a catalog file'), and the "
               "sub-domains the model proposed wait in the Briefing's To do with the import's matches.",
               "Every list edited in place says Edit on each row, as the Signal list did; a fabric's form scrolls into view when opened.",
               "A signal's Delete sits inside its Edit form, behind a confirm. The cut-points are number fields with "
               "the bands said in words. Changing how an assessment calls the model asks first, with its cost.",
               "Developer details sit behind Technical details: the evidence limit, how an assessment calls the model, "
               "the page-part settings, the judging token limit and the skill map's 'agent' marks. Changes speaks of "
               "'the defaults' rather than 'starting files', and a sub-domain's status reads proposed → accepted."],
         why="Setup should say what each part is for, show what can be changed, and make mistakes hard.",
         metrics=[("Menu", "11 items in one list", "10 items in 4 groups; Import under Technologies"),
                  ("Delete buttons on the Signal list", "37, one per row", "None on the rows; one inside Edit"),
                  ("Lists that say Edit on each row", "Signal list only", "Also Fabrics, Measures, Classification, Path to scale, Mechanisms, Assumptions")],
         diagram=None,
         before=[("item-26-before-signal-list.png", "Before: a Delete as prominent as Edit on every one of the 37 rows.")]),
    dict(n="27", title="Setup's pages: answer where you read, and Tata's words", status="Built",
         source=[("S8", "our review of Setup's pages: open questions answered on another tab, numbers that said "
                        "nothing, a list shown twice, and 'TCL' in the setup text")],
         what=["Each open question has Mark settled beside it; the item keeps its values. (Raising or settling a "
               "question on a fabric no longer clears its 'what Tata has today' text, which it could before.)",
               "Scoring method opens with one plain line ('12 setup decisions wait on Tata's answer') instead of "
               "number tiles. Path to scale shows its steps once.",
               "Sources say On or Off in words; a source's page has its switch at the top.",
               "Settings flags edits not saved yet, and its time-zone line follows the rule: each time shows in the "
               "zone of the person who did the thing.",
               "'TCL' is now 'Tata' in the fabrics, measures, open questions and the Sources H1 line (16 setup items), "
               "kept as the defaults."],
         why="An answer belongs where the question is read, and the screens should use the client's own name.",
         metrics=[("Where an open question is settled", "On its item's tab", "Beside it, on Open questions"),
                  ("'TCL' in setup text", "40 places", "None"),
                  ("Path to scale's proof", "Listed twice", "Once")],
         diagram=None,
         before=[("item-27-before-open-questions.png", "Before: open questions to read here and settle elsewhere.")]),
    dict(n="28", title="Tata's plan reaches the Point of View in full", status="Built",
         source=[("S8", "your request for a worked example: an invented plan for one catalog technology, to see what it "
                        "changes in the Point of View")],
         what=["The Point of View is now written from everything recorded in Tata's plan, labelled as Tata's own "
               "record: the step reached and why, the proof recorded for each step, whether the next step's proof is "
               "in hand, the blockers, and the owner's next action and date, people, budget and trial.",
               "Its skill (version 10) says how to use it: attribute it to Tata and quote it exactly; never list as "
               "missing what Tata has recorded; name the blockers as risks; end the recommendation on the owner's next "
               "action and date.",
               "Worked example, invented for the demo: Agentic AI in Interaction, at Customer zero (Tata's own service "
               "desk at US$2.80 a resolved request against US$6.90), a bank's letter of intent, three blockers, and an "
               "owner with a pilot to sign by 15 Dec 2026. Published in the edition 'Demo: Agentic AI plan'.",
               "Small fixes: the indicative price shows as '$0.45 a unit', a next action no longer reads 'each., by', "
               "and a section the model puts in the wrong place is moved back before the page shows it."],
         why="What Tata records about its own plan is the strongest evidence a Point of View can have; it should "
             "change the conclusion, not sit beside it.",
         metrics=[("What the Point of View received from the plan", "One line: step, blockers, 'proof in hand'",
                   "All of it, as Tata's own record"),
                  ("Recommendation in the example", "Ended on signs to watch",
                   "Ends on the owner's next action, by 15 Dec 2026"),
                  ("Gaps in the example", "Asked for the cost Tata had already measured",
                   "Asks for outside confirmation of Tata's figures")],
         diagram=None,
         before=[]),
    dict(n="29", title="About this technology, for readers new to it", status="Built",
         source=[("S8", "your review of the Point of View: a section above the recommendation on what the technology is, "
                        "its history and how it has evolved, for executives who have never heard of it")],
         what=["Each Point of View now opens, after its four answers, with About this technology: what it is in plain "
               "words, where it came from, the turns that shaped it and where it stands today, in four to six sentences.",
               "It is the one section written from general knowledge, not the pages, and says so under its heading. Its "
               "skill (version 11) keeps it to well-established facts: no market sizes, prices or forecasts, a year only "
               "where it is widely known, and nothing about Tata or the scores, which the other sections cover. The "
               "summary no longer repeats what the technology is.",
               "Both addresses show it: the analysts' page now, and the leaders' view from the next publish. A Point of "
               "View gets it when it is next written."],
         why="A recommendation means little to a reader who doesn't know what the technology is; the page should "
             "explain it before asking for a decision.",
         metrics=[("What a new reader learns before the recommendation", "The verdict and four answers",
                   "Also what it is, where it came from, how it has evolved"),
                  ("Where the explanation comes from", "Not shown", "Said under the heading: general knowledge")],
         diagram=None,
         before=[("item-29-before-pov.png", "Before: the verdict, four answers and the recommendation, with nothing on "
                                            "what the technology is.")]),
    dict(n="30", title="Rewrite shows the new version when it's done", status="Built",
         source=[("S8", "your review of change 29: after Rewrite, the page kept the old text and status until you left it "
                        "and came back")],
         what=["Writing a Point of View takes about a minute (47 seconds in the middle case, up to 2 minutes). The "
               "portal used to give up waiting after 30 seconds; the radar still wrote and saved the new version, but "
               "the page never heard back, so it kept showing the old one. It now waits up to 10 minutes.",
               "While it writes, the button says 'Writing… about a minute'; when it's done, the page shows the new "
               "text, its written time and which version leaders see, and says so under the button."],
         why="A person who presses a button should see what it did, on the spot; a page that looks unchanged reads as "
             "a failure, and invites pressing again (four rewrites of one technology on 22 Oct).",
         metrics=[("Rewrites the page showed when done", "None that took over 30 seconds (most do)", "All"),
                  ("What the button says while writing", "Starting…", "Writing… about a minute")],
         diagram=None,
         before=[]),
    dict(n="31", title="The collection page says where it stands and what went wrong", status="Built",
         source=[("S8", "your review of a running collection's page: it didn't follow the design principles")],
         what=["Problems come first, in words, each with what to do: a source that couldn't finish (for example "
               "'OpenAlex refused its searches: it now needs its free key'), pages that couldn't be analysed, "
               "technologies that couldn't be judged. A failed model call says why.",
               "Four steps in the order they run, each saying in progress, waiting, done or stopped: collect (with "
               "'N of 86 sources done' while it reads), findings, merging names, and judging evidence, which was "
               "hidden before though it can be the costliest step. A step's link appears once it's done.",
               "'Running for…' while it runs, in the zone of whoever started it, and the page updates by itself. "
               "Sources are grouped as couldn't finish, reading now and done (folded); the page budget is said once.",
               "Stop the collection asks first and says what is kept. Operations words a failed source the same way."],
         why="A person watching a run needs to see what is happening, what went wrong and what to do, without "
             "reading 86 rows or a raw error.",
         metrics=[("Page length, 86 sources", "7,701 px", "1,180 px"),
                  ("Where a failure shows", "In its row, as a raw error", "First, in words, with what to do"),
                  ("Times", "UTC", "The starter's zone (Central)"),
                  ("Stopping", "One click", "Asks first")],
         diagram=None,
         before=[("item-31-before-collection.png", "Before: RUNNING, but no step says where it is; times in UTC; "
                                                   "a failure in row 4 of 86.")]),
    dict(n="32", title="Market size as a band, from a named page", status="Built",
         source=[("S9", "decision 3: market size appears as bands, from named sources, never as a figure the model makes up")],
         what=["The Addressable market measure now names the one figure its score rests on, with its year, what it "
               "covers and the page that states it. A figure is kept only when that page is one the measure cites.",
               "Each Point of View shows it as a fifth answer: under $1B, $1–5B, $5–20B, $20–100B or over $100B, with "
               "the figure and its page, or 'No figure found'. The Point of View's text uses the band too.",
               "It appears as each technology is assessed again; Statista or another source Tata trusts can be added "
               "later."],
         why="A band from a named page is honest about how precise a market figure is, and never invents one.",
         metrics=[("Market size on a Point of View", "In the text only, when a page gave one", "A band with its page, or 'No figure found'")],
         diagram=None, before=[]),
    dict(n="33", title="Metrics to watch are checked at the next assessment", status="Built",
         source=[("S9", "Ankur's second test: metrics to watch, flagged when they cross an inflection point")],
         what=["Each assessment now gets the metrics the one before it set, and says for each: crossed, not yet, or "
               "no newer value, with today's value and the page that shows it. A crossing counts only from a page "
               "the assessment read.",
               "A crossing shows on the Briefing (Signs that crossed their threshold), on the technology's metrics "
               "and in the Point of View, whose writer is told."],
         why="The meeting notes said metrics are re-checked and flagged; until now each assessment suggested new "
             "ones and nothing compared them.",
         metrics=[("Previous metrics at the next assessment", "Not compared", "Each checked, with its page")],
         diagram=None, before=[]),
    dict(n="34", title="Leaders' opens and prints are counted", status="Built",
         source=[("S9", "backlog item 4: view and download counts per Point of View, to see where leaders' attention goes")],
         what=["The leaders' address counts each time a Point of View is opened and each Print / Save as PDF; it "
               "is the one thing that address can write.",
               "The Points of View list and each Point of View say how often leaders opened it and when last. Who "
               "isn't known until there is sign-in."],
         why="It shows which conclusions leaders read, without asking them.",
         metrics=[("Leaders' reading", "Not known", "Opens and prints per Point of View")],
         diagram=None, before=[]),
    dict(n="35", title="A fabric people worked on is always assessed again", status="Built",
         source=[("S8", "your question: is anything people entered lost at the next run?")],
         what=["Nothing people enter is lost: it is kept against the technology and fabric, not the run. But each "
               "assessment chooses its fabrics again, and a fabric it judged not relevant dropped off the page with "
               "Tata's plan, a priority set by hand or a hand score in it.",
               "Now every fabric where people recorded something is assessed again, whatever the model judges."],
         why="Agentic AI's fabrics varied between runs (IoT came and went); the demo plan in Interaction would have "
             "dropped the same way.",
         metrics=[("A fabric with people's entries", "Could drop off the page", "Always assessed again")],
         diagram=None, before=[]),
    dict(n="36", title="86 sources, and the radar compared with the catalog", status="Built",
         source=[("S9", "Ankur's first test: expand the sources and compare the radar's results with Tata's list")],
         what=["Sources switched on went from 13 to 86, each test-read first: research labs, standards bodies, "
               "conferences, funders, journals, investors and trade press. arXiv also reads its quantum, robotics "
               "and AI lists; the paper and grant searches cover 20 topics. Patents (EPO) and USAJOBS follow once "
               "their free keys are in.",
               "A spreadsheet for Tata compares the radar with the catalog before and after: what the radar finds "
               "that the catalog doesn't track, and every catalog technology with its pages and why it has little "
               "or nothing.",
               "The collection used 7,750 model calls (660 with 13 sources); judging evidence stopped at its token "
               "limit, and the rest are judged at the next collection."],
         why="Most of the catalog had no evidence at all: the 13 sources simply never named it.",
         metrics=[("Catalog technologies with 3+ pages", "40", "143"),
                  ("Catalog technologies with no pages", "883", "715"),
                  ("Found by the radar, not in the catalog, 3+ pages", "300", "1,181")],
         diagram=None, before=[]),
]

ITEMS.append(
    dict(n="37", title="One run, from collecting to publishing, in six steps", status="Built",
         source=[("S8", "your question: an easier way to see which step the last run is on, and everything that happened in it")],
         what=["A run is now shown whole, in six steps: Collect (reading each page), Organize (merging names), "
               "Classify (judging evidence), Assess, Write Points of View and Publish to leaders. Each step says where "
               "it stands (in progress, waits for you, stopped and why, done), who moves it on, what it did, and "
               "links to its results.",
               "A Now line on top says which step the run is on and what comes next; that step is marked. Assess, "
               "Write and Publish count what was done from the collection's start until the next collection's, so "
               "an older run shows what happened until then, with no buttons.",
               "The same steps, in the same words, appear on the run page and on Operations, where they replace the "
               "six cards and keep every button: Check again, Organize now, Classify, Assess, Resume, Write and "
               "Publish, each showing its model-call cost first. The Briefing has one line on where the latest run "
               "stands, and the status panel in the top bar links to it.",
               "The Classify button is never the main one: the next collection carries on for free."],
         why="Until now a run was split across three places that didn't agree: the run page stopped at judging "
             "evidence, Operations showed the latest of each job (possibly from different runs) under other names, "
             "and the Briefing's To do. Nothing answered which step the last run was on.",
         metrics=[("Where a run's progress shows", "Three places, different step names", "One six-step view, used everywhere"),
                  ("Steps after the collection (assess, write, publish)", "Not linked to the run", "Counted until the next collection"),
                  ("Which step the run is on", "Worked out by the reader", "Said in the Now line")],
         diagram=None,
         before=[("item-37-before-operations.png", "Before: six cards for the latest of each job, which can come from different runs, under names the run page doesn't use."),
                 ("item-37-before-briefing.png", "Before: the Briefing says when the last collection ran, not where it stands.")]))
ITEMS.append(
    dict(n="38", title="Judging evidence has no limit, and the catalog goes first", status="Built",
         source=[("S8", "your question on why 5,807 technologies were left unjudged: remove the limit for good")],
         what=["Classify (judging each technology's evidence) used to stop at 8 million tokens a run, a setting in "
               "Setup › Settings. The 22 Oct collection's run stopped after 2,908 of 8,715 technologies, leaving "
               "5,807 without a domain, availability, maturity or evidence verdict. The limit is gone from the "
               "radar, its settings and the seeding data: a run judges every technology it is given.",
               "Catalog technologies are judged first, then those with the most pages, so what matters most is "
               "ready first.",
               "A collection no longer skips judging when a Classify someone started is still going: it waits for "
               "that run, then judges what it left, and its step says so.",
               "The 5,807 left by the 22 Oct collection were judged on 22 Oct in one run of 35 minutes, none "
               "failing: 563 technologies are now ready to assess for the first time, 76 of them in the catalog."],
         why="The limit, not the method, left most new technologies unjudged; and the button offering to judge them "
             "all would have stopped halfway at the same limit.",
         metrics=[("Technologies one Classify run judges", "Up to about 2,900 (8M tokens)", "All it is given"),
                  ("Order", "As stored", "Catalog first, then most pages"),
                  ("A collection's Classify while another runs", "Skipped, without saying why", "Waits, then judges what's left")],
         diagram=None, before=[]))
ITEMS.append(
    dict(n="39", title="A Status filter, and Add evidence through to the Point of View", status="Built",
         source=[("S8", "your questions: is there a view of held technologies, and can a person give links or "
                        "documents for one technology and have it assessed end to end?")],
         what=["Technologies has a Status filter beside the others (Assessed, placed; Assessed, not placed; Ready to "
               "assess; Thin evidence; No evidence yet), and the counts above the list now look like the links they "
               "are. 'Assessed' became 'Assessed, placed', so the two assessed statuses add up to the Assessed group.",
               "Each technology's page has Add evidence: paste links (one per line) and add PDF, text, Markdown or "
               "HTML files. They are read like collected pages and filed under it, then its evidence is judged "
               "again. By default it carries on by itself: assessed, then its Point of View written, which waits for "
               "you to publish. 'Only judge its evidence' stops there.",
               "If its evidence is still judged thin it stops and says so, unless you ticked 'Assess even if…'. The "
               "cost shows on Start (one call per page, one to judge, the assessment's calls, one for the Point of "
               "View); each step shows while it runs; pages already collected aren't read again.",
               "It replaces the technology's single Add a link; Add a link stays on measures and use cases."],
         why="Held technologies were reachable only through grey text that didn't look clickable; and a person who "
             "knows the right pages for a technology had to drive four separate steps to get it to a Point of View.",
         metrics=[("Finding the held technologies", "Grey text above the list", "A Status filter, and links"),
                  ("Evidence a person gives", "One link at a time", "Links and files together"),
                  ("From a person's pages to a Point of View", "Four steps by hand", "One start, with its cost")],
         diagram=None,
         before=[("item-39-before-technologies.png", "Before: the statuses are grey text after the group's meaning; nothing says they can be clicked.")]))
ITEMS.append(
    dict(n="40", title="Catalog technologies found on pages by name", status="Built",
         source=[("S8", "your question on why so many catalog technologies had no evidence, and our sample of 14: "
                        "most were named on pages we held, but not in the catalog's wording")],
         what=["Each catalog technology now has the names it's written as on pages: its usual name, other spellings "
               "and short forms (FlexE, Flex Ethernet; C-V2X, Cellular Vehicle-to-Everything; DALI, IEC 62386). A "
               "model gives them once, 40 at a time; a person can edit them on the technology's page.",
               "Every stored page is searched for those names at no model cost (a one-word name only as written, so "
               "\"did\" or \"matter\" in a sentence isn't a match). For each technology named on pages it isn't filed "
               "under, a model reads the passages and says whether each page is about it, names it in passing, or "
               "uses the word for something else. Pages about it are filed as its evidence; pages naming it in "
               "passing are counted apart and never count as evidence. Each page is checked once.",
               "It runs in every collection, on its new pages, inside the Organize step (now 'Organize: merge and "
               "link names'), and once over every stored page as a catch-up (Operations, Link known names on all "
               "pages). Catalog only, as you chose: broad assessed technologies already have plenty of pages. The "
               "catch-up on 22 Oct checked 600 catalog technologies named on 7,650 pages in about 1,200 model calls: "
               "856 pages were about one and are now its evidence, 5,588 named one in passing, 1,206 used the words "
               "for something else. Their evidence was then judged again: 37 more catalog technologies are ready to "
               "assess.",
               "108 catalog entries read as an industry application rather than a technology (\"Edge Computing for "
               "Cold Chain\", \"AI in education\"); each says so on its page, worth asking Tata which technology it "
               "stands for.",
               "Also: Add evidence's file picker is a real button with the chosen files listed; it says a link is "
               "read as one page (links on it aren't followed), refuses a link carrying a login and says why; "
               "\"Only judge\" says where to see the result; tested on real pages (FlexE, from no pages to a Point "
               "of View in 2 minutes 20 seconds; k0s judged thin). About this technology runs in two columns on a "
               "wide page."],
         why="Most catalog technologies had no evidence because pages name them in other words, not because the "
             "pages weren't there; the page reader only noted what each page was mainly about.",
         metrics=[("Catalog technologies with no pages", "726", "610"),
                  ("Catalog technologies with 3+ pages", "150", "205"),
                  ("Pages filed under catalog technologies by name (catch-up, 22 Oct)", "—", "856, for 226 technologies"),
                  ("How a page is linked to a catalog technology", "Only if the reader named it as the page's subject",
                   "Also by its names, checked by a model"),
                  ("A page naming it in passing", "Not counted", "Counted apart, never evidence")],
         diagram=None, before=[]))

DECISIONS = [
    "Finance (contribution, payback, break-even) is set aside on every screen until Tata has discussed it; figures and "
    "code are kept (21 Oct).",
    "Detection stays the core; each Point of View carries the path to scale; no macro model.",
    "Tata's own categories are used: commercial availability, domain and sub-domain, TRL.",
    "An imported list means 'these are emerging technologies we care about'; each row's own commercial availability is kept.",
    "People's choices are kept and never overwritten by a new run: moves, overrides, hand scores, imports, yes or no on nascent.",
    "The AI never writes a financial figure; contribution, payback and break-even come only from figures Tata enters.",
    "Disruption threat and Serviceable capture are entered by Tata.",
    "Cloud and Security stay separate fabrics for now.",
    "Leaders get their own web address: the leaders' view (called Frontier at the review).",
    "Assessments use stacked calls (change 5), after trying both ways; commercial adoption and use-case breadth are judged per "
    "fabric (signed off 21 Oct).",
    "The leaders' view shows a published edition, never live data; the innovation team publishes.",
    "When several rows of an imported list join one technology, none of their values is applied; a narrower technology is "
    "never folded into a broader one.",
    "The radar may suggest blockers from the pages; only a person picks them (signed off 21 Oct).",
    "Tata's list is called the catalog. A person can add a technology to it or take one out, kept like any other choice, "
    "with Undo (signed off 21 Oct).",
]

WAITING = [
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
