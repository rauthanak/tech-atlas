# Implementation plan 5: Point of View skill v4 and the fabrics left out (tech-atlas)

**Date:** 2026-10-04 · **Folder:** 2026-10-04/4 · **Status:** approved on 4 Oct ("do it please"). Built, deployed and checked.

**Portal plan (the master, with the screens and printing):** [tech-lens plan 5](../../../../tech-lens/docs/2026-10-04/4/implementation-plan.md).

---

## 1. Skill `pov` v4

**Sections:** headline, summary, tora_analysis (one per main score), other_measures, placement_rationale, evidence_gaps and recommendation.

**Removed:** maturity, market_view and capability_gap. They retold measures the score sections already cover. A capability gap is now described under Other measures.

**Rules:**
- **Every section is written.** Each measure is discussed once:
  - in its score's section;
  - or, for the measures listed under "Other measures", in other_measures, in words, without numbers.
  Other sections may name a measure but don't explain it again.
- **Each limitation once:** it is said in its measure's section, in one clause. evidence_gaps names the evidence that would settle the biggest gaps.
- **No measure names in the skill:** it refers to "the measures listed under" each score in the assessment data. Editing measures in Setup keeps it right.

**Code:** `src/agent/analyzer/pov.py` changes `SECTIONS` to match. The input digest already grouped the measures this way (plan 4).

## 2. The fabrics a technology wasn't assessed in

**What:** `evidence.not_assessed_in(run, rows)` gives the run's frozen fabric list (`snapshot.fabrics`) minus the fabrics the technology was scored in. Before scoring, its gate judged those not relevant.

**Where it appears:**
- `GET /api/technologies/{id}/summary`, as `assessment.not_assessed_in`;
- `GET /api/scoring/runs/{run}/pov/{tech}`, as `not_assessed_in`.

**Test:** `test_the_fabrics_it_was_not_assessed_in`. All 83 tests pass.

## 3. How it shipped

It shipped like plan 4: the skill was edited in `seeds/prompts.json`.

**Before deploying, on live:**
- the comparison (`live_vs_seeds.py`, in this folder) showed a load would change one item only: `pov` (system and prompt);
- Changes was 0;
- nothing was running.

**After deploying:** live matched the seeding data exactly, with `pov` v4 loaded, and Changes was still 0.

**Why skill changes don't appear in the Changes tab:** the Changes tab lists edits made in the app that the seeding data doesn't have yet. It's the to-do list for "Update seeding data". This skill was changed in the seeding data itself, and the API loaded it at start, so nothing is waiting to be saved. Each skill's version is shown in Setup → Skills. The text from before this plan is in `replaced/prompts-before-plan5.json`.

## 4. Data

- **Dev copy:** AgenticOps and Agentic AI were rewritten with v4 (2 calls), to check a technology without a priority and one with one.
- **Live:** AgenticOps was rewritten, and is now version 4 (1 call). Version 3 is in `replaced/agenticops-pov-version-3.json`.
- **Model calls:** 3 in all, on gpt-5.6-luna.
- **Other technologies:** none has a written Point of View. The 133 that are ready get v4 when they're written.
