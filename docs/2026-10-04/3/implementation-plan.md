# Implementation plan 4: backend and skills (tech-atlas)

**Date:** 2026-10-04 · **Folder:** 2026-10-04/3 · **Status:** approved on 4 Oct ("make the plan and then execute it"), including "revisit and revise the skills". Build notes in §7.

**Portal plan (the master, with the screens):** [tech-lens plan 4](../../../../tech-lens/docs/2026-10-04/3/implementation-plan.md).

---

## 1. Backend: four small changes

| | Change | Why |
|---|---|---|
| B1 | `POST /scoring/runs` rejects an empty `technologies` list (`min_length=1`, a 422 with the reason). | `[]` is falsy, so `_select_technologies` falls through to every enabled technology: 1,853 of them, about 90,000 model calls. Nothing sends one today. |
| B2 | `_for_analyst` returns every waiting item. The `[:3]` cut goes. | A stopped run pushes "ready for a Point of View" off the Briefing, and with it the Technologies list's "Write these N" button. At most four kinds exist. |
| B3 | The technology summary gives each fabric its stored `placement` (the how-soon and how-big inputs). | The page can then say why there is no priority. |
| B4 | The Points of View list gives each Point of View its `assessed_at`. | It is already computed (`read["assessed_at"]`). Cards can say "from the Sep 11 assessment". |

**Tests:**
- `test_pipeline` expects all four items;
- a 422 for an empty list;
- the summary carries placement;
- the list carries `assessed_at`;
- the new digest (§2).

## 2. Point of View input in plain words

**File:** `src/agent/analyzer/pov.py`, `_assessment_digest`.

**Why:** the writer is handed codes ("S1 fabric-fit: 8"), so it can't say what a partial score rests on. It isn't told how many sites the evidence comes from, and for AgenticOps every cited page is Cisco's own blog. It gets the stored lowercase name.

**What changes:**
- **Measures grouped by axis**, named from the run's own frozen method (`snapshot.measures`), for example:
  > Strategic Fit: 8 (1 of 3 measures scored)
  > Fabric fit: 8 — justification…
  > Portfolio adjacency: not enough evidence — would need: …
- **Priority in words**, for example "Priority and horizon: not set. How soon couldn't be worked out (0 of 2 inputs scored); how big 4 (1 of 4 inputs scored)".
- **Evidence base**, for example "6 pages read. The scores cite 6 pages from 1 site: blogs.cisco.com (6)", worked out from the measures' cited URLs.
- **Watch metrics:** passed once, with their source when there is one.
- **Name:** the display name ("AgenticOps"), from the technology's label.
- **Codes:** none in the digest at all.

## 3. Skills

### 3.1 `pov`

**What's wrong in the AgenticOps Point of View (version 1):**
- **Jargon in the headline:** "cannot yet be placed".
- **An overstatement:** "strong strategic relevance", from 1 of 3 strategic measures.
- **A missing caveat:** it never says up front that all the evidence is Cisco's own announcements.
- **Internal words in client prose:** "The dossier does not provide…".
- **Repetition:** the same caveat appears about ten times across sections.
- **Watch metrics framed as targets:** "Validate the three watch metrics…" uses an internal term, and makes the model's suggested thresholds sound like targets TCL has set.

**Changes:**
- **Headline:** the plain verdict, with no method words ("placed", "cell", "TORA", "measures").
- **Partial scores** say what they rest on and what couldn't be assessed, in plain words.
- **Narrow evidence:** if most of it comes from one company or site, the summary says so.
- **Each gap once:** said in `evidence_gaps`, plus at most one clause in the summary. Other sections are written only when they add something new; otherwise they are null. This replaces the FULL / INSUFFICIENT EVIDENCE modes.
- **Recommendation:** opens with a plain stance ("Monitor, don't invest yet."). It gives the reason, then what would change the stance. Watch items are signs to look for, with thresholds as examples.
- **Banned words:** dossier, roll-up, cell, placeable.

### 3.2 `measure_scoring`

**Change:** "EVIDENCE DOSSIER" becomes "EVIDENCE", and the justification starts with what the evidence shows, never "The dossier…".

**Why:** every AgenticOps justification starts "The dossier…". It shows verbatim on the assessment page and leaks into the Point of View.

### 3.3 `watch_metrics`

**Changes:**
- no priority or horizon codes in implications;
- the source URL in its own `source` field, not inside the text;
- `current_value` says when it was true.

**Why:** the example "H3 becomes H2" taught the model to write "moves from H3 toward H2" for AgenticOps, which has no horizon. Raw URLs sit inside the "Now" text.

### 3.4 Reviewed, no change

- **`article_summary`:** it already asks for 1–3 technologies per finding. No stored finding has them yet: they were extracted before that code existed (§6).
- **`technology_resolve`, `technology_label`, `fabric_relevance`:** their output reads correctly in the register.
- **`orchestrator`, `supervisor`, `scout`, `link_selection`, `analyzer`:** these steer agents, and nobody reads their output.

## 4. How skills ship

The skills live in `seeds/prompts.json`, which is mounted into the atlas container. On 4 Oct, live had Changes = 0 and nothing running. So the next atlas start loads the new skill text and changes nothing else.

The dev API loads the same files into `tech_atlas_dev` when it restarts.

## 5. Verify

- **Unit tests.**
- **Dev:**
  - write AgenticOps' Point of View (1 call), plus one for a technology with a priority (1 call);
  - script runs of `watch_metrics` (1 call) and `measure_scoring` (1 call) on AgenticOps' evidence, read against §3.
- **Live, after deploying:** rewrite AgenticOps' Point of View (1 call), so the improvement shows. Version 1 is replaced.

## 6. Left as is

- **Old wording stays:** existing assessments keep "The dossier…" and "H3 toward H2" until the technology is assessed again.
- **Finding tags:** existing findings use their page's technologies (median 6, up to 30). Giving each its own would mean re-extracting the Oct 3 pages, at about 1 call per page. That is your call.
- **The 200-technology cap:** explicit assessment lists stop at 200. "Assess the N" fails above that, showing the API's reason.

## 7. Build notes

**Built and deployed on 4 Oct, by 11:00 UTC.** B1–B4, the digest and the three skills are as planned. Tests: 82 pass, including the new `test_pov_digest.py`, the empty-list test, and the 4-item, placement and `assessed_at` assertions.

**Additions found while testing on the dev copy** (3 Point of View calls and 2 skill calls):
- **Priority inputs named:** the digest names the measures behind how soon and how big, from the run's own priority grid. Without them, the writer blamed the missing priority on portfolio fit, which doesn't feed it.
- **Evidence sites from every page read:** the first live rewrite said "five of the six pages come from Cisco" when all six do, because it saw only the cited pages' sites. The digest now names the sites of every page the assessment read. These come from its recorded page versions, or for older assessments from the technology's linked pages, as the evidence builder picks them. AgenticOps now reads "6 pages read, from 1 site: blogs.cisco.com (6). The scores cite 5 of them".
- **Skill tightening (`pov` v3):**
  - the summary is written in words, with the scores left to the score sections;
  - only the three main scores are cited, so there is no unexplained "capability gap scored 8";
  - no priority or horizon is named that the data doesn't set;
  - the recommendation gives one or two signs to watch;
  - at most 3 gaps per fabric;
  - a score shared by fabrics is said once.

**Skills now live:** `pov` v3, `measure_scoring` v2, `watch_metrics` v2. Each deploy came after a full live-vs-seed comparison of every list: the only differences were these skills, with nothing running and Changes at 0 before and after.

**Live data refreshed for AgenticOps,** the one Point of View, so the improvement shows:
- its Sep 11 watch metrics were regenerated from the same evidence with the new skill (1 call; its scores are untouched);
- its Point of View was rewritten twice (2 calls), and is now version 3.

The replaced data is in [`replaced/`](replaced/): Point of View version 1, the Sep 11 watch metrics, and `seeds/prompts.json` as it was before this plan.

**Model calls in all:** 8, on gpt-5.6-luna: 5 on the dev copy and 3 on live.

**Not changed (§6 still applies):**
- the other 158 assessed technologies keep their old watch-metric and justification wording until they're assessed again;
- existing findings keep their page's technologies.
