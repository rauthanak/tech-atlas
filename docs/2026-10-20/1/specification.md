# Plan 9 specification: changes after the midpoint review

**Date:** 2026-10-20 · **Folder:** 2026-10-20/1 · **Status:** written 20 Oct; building waits for your go.

**Sources:**
- [review-notes.md](../../../../review-comments/10-20-2026/review-notes.md): every decision and its reason.
- [build-list.md](../../../../review-comments/10-20-2026/build-list.md): what we build, in order.
- [ux-map.md](../../../../review-comments/10-20-2026/ux-map.md): words, places, screens.
- **Implementation:** [tech-atlas plan](implementation-plan.md) (backend) and [tech-lens plan](../../../../tech-lens/docs/2026-10-20/1/implementation-plan.md) (portal).
- **Client document:** `review-comments/10-20-2026/Tech Radar - changes after the midpoint review.docx`. It shows before and after for each item, and it's updated as items are built.

---

## 1. Goals

1. **Answer what Tata asked for at the midpoint review** (13 Oct), and in the notes that followed from Abhishek, Ankur and Nick, without making the portal harder to use.
2. **Catch early technologies on thin evidence** (Ankur's test 1), and say when to act (test 2) and where the value lands (test 3).
3. **Put people's judgment on top of the model's,** visibly: overrides, hand scores, moves, yes/no on nascent, finance inputs.
4. **Spend fewer tokens per answer:** stacked calls, prompts whose opening is reused, bounded evidence, and recorded usage.

**Not in this plan:**
- logins (B26);
- Tata's AWS (B27);
- calibration against past cases (B28);
- the operating guide (B29);
- collection on a timer (B25, won't be built);
- combining Cloud and Security (on hold);
- owned versus partner;
- licensed sources (B13);
- inflection points (B10) and splitting a technology (B5), which aren't placed yet.

## 2. Principles that apply everywhere

| # | Principle | What it means in practice |
|---|---|---|
| P1 | **Skills stay separate; calls stack them** | Each function is its own skill (its own prompt, version and switch). A *recipe* lists the skills a call carries, in order. No combined skills |
| P2 | **The model never guesses or invents figures** | Every model answer carries a reason and its pages, or abstains. Financial figures come only from people's inputs |
| P3 | **People's choices win, and are kept** | Moves, overrides, hand scores, imports and yes/no decisions are stored as *decisions* and never overwritten by a run |
| P4 | **Cost before every model action; failures say why** | Existing rules, extended to Classify, Find evidence and Import |
| P5 | **Live equals seeds** | Every new setting or list is seeded, and Changes returns to 0. Exception: imported technology lists, while the import is tested |
| P6 | **Times in the time zone of the person who acted** | Each write records the browser's zone. Display uses that zone. Never UTC on screen |
| P7 | **Tokens are measured** | Every call records its tokens by skill and run, and every item that adds calls reports tokens before and after |
| P8 | **UX rules** | The 8 rules in the build list, and the [word list](../../../../review-comments/10-20-2026/ux-map.md#4-word-list) |

## 3. Today, in brief

These facts come from the 20 Oct code maps.
- **Assessment:** 147 technologies, 346 technology-fabric pairs, and 4,474 calls in the last run.
  - For each technology: one fabric-relevance call, one call per measure per relevant fabric (about 28), and one watch-metrics call. Each call carries the full dossier, up to 300,000 tokens.
  - 2,408 of 4,152 measure scores (58%) were left unscored.
- **Register:** 1,150 technologies. 1,003 have fewer than 3 pages; 81 of the 147 assessed rest on one source.
- **What isn't recorded:** tokens; the time zone of any write; person decisions other than enabled, rename, merge and alias.
- **Prompt rendering:** `Prompt.render` returns `system + "\n\n" + filled`. Blanks are `{name}`, and the expected blanks per skill sit in `api/prompts.py:EXPECTED_VARIABLES`.
- **Seeding:** a new seed file changes the fingerprint, and the next boot reloads every list. Live must equal seeds before any deploy that adds seed files.

---

## 4. Data model

### 4.1 Changed collections

**technologies.** New fields:

| Field | Shape | Written by |
|---|---|---|
| `switched_off_at`, `switched_off_tz` | ISO UTC, IANA zone | PUT/bulk switch off; cleared on switch on |
| `origin` | `found` (default) · `imported` · `added` | resolver / import / add by hand |
| `imported` | `{import_id, file, at, tz, row:{domain, sub_domain, description, trl, availability}}` | import (for matched and new) |
| `classification` | see below | Classify step; technology call |
| `pages_seen` | list of page versions the last classification read | Classify |

`classification` holds four answers, `evidence`, `domain`, `availability` and `trl`, plus `nascent`. Each answer comes with a source, a reason, and the numbered pages it rests on:

```
{
  evidence:     {verdict: strong|enough|thin|not_credible, reason, pages:[doc_id], read, of, sources},
  domain:       {domain_id, subdomain_id | null, subdomain_new: str | null, reason, pages, source: pages|assessment},
  availability: {value_id, reason, pages, source},
  trl:          {level 1-9, reason, pages, source},
  nascent:      {reason, quote, page} | null,
  at, run_id, list_versions: {availability, domains, subdomains, trl_levels}
}
```

**assessments** (one per technology × fabric, as now). What changes:
- Each `measures[id]` gains `scope`: `technology`, `fabric` or `tata`. Technology-level results are written once by the technology call and copied into each fabric's assessment, the way watch metrics are copied today.
- New `use_cases`, written by Value levers (item 12):
  `[{title, rank, cited: bool, suggested: bool, pages:[n], levers:[{mechanism_id, lever_id, operating_change, metric, financial_effect, evidence_needed, next_step_when, pages}], capital:{direction: light|moderate|heavy, why}}]`.
- New `no_use_case`, written only when Value levers finds none: `{reason, evidence_needed}`.
- New `calls`, recording the run's calls for this pair: `{technology_call, fabric_call, retries}`.
- `placement` is unchanged in shape. A new `effective` holds the priority after decisions are applied (§4.2): `{priority, horizon, override_id?, computed_priority}`.

**povs:**
- New `composed_tz`.
- `sections` gains `value` (where the value lands, per fabric) and `maturity` (TRL and commercial availability, with `[n]` references).
- New `sources`: the numbered source list the text cites, `[{n, doc_id, url, source_name, date, title}]`.

**settings:** new document `_id: "radar"`, seeded:

| Key | Default | Used by |
|---|---|---|
| `wake_after_pages` | 10 | item 1 |
| `default_time_zone` | `America/Chicago` | P6 |
| `evidence_floor` | 3 | item 7, until a technology is classified |
| `classify_pages_cap` | 10 | item 8 |
| `classify_token_budget` | 2,000,000 per run | item 8 |
| `emerging_availability` | `[research, pilot, early_commercial]` | items 7, 8 |
| `find_evidence_results` | 5 | item 10 |
| `find_evidence_daily_budget` | 20 searches | item 10 |

**scoring_config.evidence:** `max_dossier_tokens` comes down from 300,000. It's set from item 4's measurements: proposed 40,000, to be confirmed.
- New `selection`: `signals_first`. The pages that carry kept signals for the technology come first, then the newest.

**measures:** new `scope`: `technology` · `fabric` · `tata`. Seeded values:
- **technology:** M1, M2, M3, A1, A2;
- **fabric:** S1, S2, S3, A3, X3;
- **tata:** X1, X2.

**fabrics:** new keys, seeded from Nick's note and corrected by Tata:
- `levers`: `[{lever_id, name, mechanism_id, text}]`, two per fabric;
- `key_metrics`: text;
- `bottlenecks`: `[text]`, from Nick's "main blockers to test";
- `cautions`: text. Security: "avoided breach loss isn't Tata revenue". Interaction: "watch for billable minutes the automation removes";
- `finance_defaults`: `{margin_low, margin_high, loss_without, loss_with}`, all null until Tata gives them.

**sources:** new seeded entry `web_search` ("Web search", cluster from each result's site), used by Find evidence.

### 4.2 New collections

**decisions:** every person choice. It isn't seeded, and it's append-only: a new decision for the same key deactivates the old one.

```
{_id, kind, tech_id, fabric_id?, measure_id?, field?, key?, value, reason?, computed?, at, tz, by: null, active: true}
```

| kind | Key | value | Reason | Effect |
|---|---|---|---|---|
| `move` | tech + field (availability, domain, subdomain, trl) | the new value id or level | optional | Wins over classification |
| `override` | tech + fabric | `P1`–`P6` | **required** | Effective priority. `computed` stores the computed priority at the time, so a later move can be flagged |
| `hand_score` | tech + fabric + measure | 0–10 | **required** | Used in place of an unscored measure |
| `accept_gap` | tech + fabric + measure | true | — | Removes the measure from the Gate 2 list |
| `tata_entry` | tech + fabric + measure (scope `tata`) | 0–10 | **required** | Scores a measure that Tata enters |
| `nascent` | tech | `yes` · `no` | — | yes: availability moves to Research or Pilot (a person's choice), and it can be assessed despite the floor. no: dismissed until a new page flags it |
| `use_case` | tech + fabric + use-case key | `accept` · `reject` | — | Only accepted suggested use cases reach the Point of View |
| `path_step` | tech + fabric | step_id | optional | The path to scale |
| `finance` | tech + fabric | `{upfront, running, revenue, margin?}` | — | Finance screen inputs |

**llm_calls:** one document per model call.

```
{_id, at, run_kind: collection|resolve|classify|scoring|pov|find_evidence|import, run_id, tech_id?, recipe?, skills:[name],
 model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, ms, ok, error?}
```

Indexes: `(run_id)` and `(at)`. Deep-agent steps are recorded from LangChain's `usage_metadata` where it's present.

**imports:**

```
{_id, file, sheet, at, tz, status: reviewing|matching|ready|confirmed|discarded, rows,
 items:[{row, name, values:{...}, group: matched|proposed|new, target_tech_id?, decision: accept|reject|null}],
 unknown_values:[{field, value, map_to|add}], counts, calls, confirmed_at}
```

**find_evidence_jobs:**

```
{_id, gap:{kind: technology|measure|use_case|link, tech_id, fabric_id?, measure_id?, url?}, query?,
 results:[{url, status: new|already|failed, doc_id?, reason?}], rerun:{kind, outcome}, status, at, tz, calls}
```

### 4.3 New seeded lists

Each is added to `ID_FIELDS` and `COLLECTIONS` and given a Changes label.

| List | Id field | Fields | Starts from |
|---|---|---|---|
| `availability` | `availability_id` | name, definition, order, emerging, catch_all | Research, Pilot, Early commercial, Mature, Unclassified |
| `domains` | `domain_id` | name, definition, order, catch_all | Tata's 9 domains (the 3 blockchain variants merged into Blockchain/Web3), plus Other |
| `subdomains` | `subdomain_id` | name, domain_id, status (seeded · new) | Tata's 545, each under its row's domain |
| `trl_levels` | `level` | name, definition | The usual 1–9 |
| `path_steps` | `step_id` | name, order, evidence_needed, decision | Tri's 7 steps, with Nick's evidence on Customer zero, Proof of concept and One customer |
| `mechanisms` | `mechanism_id` | name, definition | Nick's 4 |
| `recipes` | `recipe_id` | name, skills (ordered), shared_blanks, scope | `classify`, `technology`, `fabric`. Read-only in the portal for now |

**A sub-domain the model proposes** is stored with `status: new`. It shows on Changes like any edit, so an admin can accept it into the seeds or merge it.

---

## 5. Stacked calls (the mechanism behind items 5, 8, 9, 12)

**A recipe** is seeded and lists:
- its skills in order;
- the blanks its skills share (for example `technology`, `fabric_name`, `fabric_definition`, `tcl_today`, `evidence`), which are given once.

**How a recipe call is built:**
1. **Preamble** (fixed). The role, and the reply format: "Reply with ONE JSON object. Under each key below, put exactly what that block asks for."
2. **One block per skill** (fixed), headed `### <key>: <skill name>`.
   - The block is the skill's own text, rendered with its non-shared blanks.
   - Shared blanks are replaced by a pointer, such as "(given once below, under EVIDENCE)".
   - Measure scoring adds one block per measure, keyed `measure:<measure_id>`, each filled from the measures list.
3. **Fabric part** (fabric calls only; the same for every technology in that fabric): the fabric's definition, TCL today, levers, metrics and cautions.
4. **Technology part:** the technology, its evidence, and, in incremental Classify, its current answers.

**Caching:**
- Parts 1–2, and part 3 per fabric, are the reusable opening. The model layer sends them as system blocks with a cache marker for Anthropic, and as an identical opening for OpenAI, which caches automatically.
- Part 4 is the user message.

**Replies:**
- Each key is checked by its own skill's parser and rules, the same rules used today (for example clamping a score to 0–10, and treating a score with no evidence links as unscored).
- A missing or invalid key is retried once on its own, as a single-skill call with the skill's full normal render. That keeps today's "a failed measure retries alone".

**The preview** ("What it turns into", plan 8) gains a recipe view that shows the stacked call, with each block labelled by its skill. A single skill's preview is unchanged.

**Saving a skill** still checks its own blanks (`EXPECTED_VARIABLES`). New entries:

| Skill | Blanks |
|---|---|
| `evidence_strength` | `technology`, `evidence`, `facts` |
| `domain_subdomain` | `technology`, `evidence`, `domains`, `subdomains` |
| `commercial_availability` | `technology`, `evidence`, `availability_values` |
| `trl_level` | `technology`, `evidence`, `trl_levels` |
| `possible_nascent` | `technology`, `evidence` |
| `value_levers` | `technology`, `fabric_name`, `fabric_definition`, `tcl_today`, `fabric_levers`, `mechanisms`, `fabric_cautions`, `evidence` |

The new lists are fixed per run, so they sit in the fixed part. The largest, `subdomains`, is grouped by domain.

---

## 6. Items

Each item gives what the user sees, how it behaves, the API, and its acceptance checks. Sizes: S (a day or less), M (2–3 days), L (a week).

### Item 0. UX map and quick fixes (S)

The map is done: [ux-map.md](../../../../review-comments/10-20-2026/ux-map.md). The quick fixes:

| Fix | What | Done when |
|---|---|---|
| **Q1** | The Briefing defaults to "since the last collection" instead of 7 days. The window select gains "Since the last collection" as its first option | Opening /admin on today's data shows the 1,073 findings from Oct 6, not 0 |
| **Q2** | Plain names in place of codes and ids | No skill name, measure id, collection id or "TORA" visible with Technical details off |
| **Q3** | Every Scoring method tab gets a PageHeader with a title and a one-line purpose | |
| **Q4** | Sources opens filtered to "switched on" (13), with "Show all 147" | |
| **Q5** | README corrected | |

**Q2 in detail:**
- Skill pages show the skill's display name, from a new `title` in `PROMPT_IMPACT`, and keep the code name under Technical details.
- Assessment measure cards show the measure name, not the id.
- The collection id link reads "Oct 6 collection".
- "TORA" becomes "Market potential · Strategic fit · Adoption readiness".
- "v3" becomes "version 3".

### Item 1. Switch a technology off from the list (S)

**What you see:**
- **On the list:** an on/off switch on each row, and a tick box for bulk actions ("Switch off", "Switch on").
- **On the row and on the technology's page:** "Switched off on 21 Oct, 9:40 AM CDT".
- **Wake flag:** "Switched off, but N new pages since: have a look?", once N ≥ `wake_after_pages`. It also appears on the Gate 1 list.

**How it behaves:**
- A switched-off technology is skipped by Classify and assessment, never shown in Frontier, and gets no Point of View.
- It still collects pages, files them, and is never deleted.
- Switching it back on clears `switched_off_*`. The next Classify and assessment pick it up.

**API:**
- `PUT /api/technologies/{id}` (existing) records `switched_off_at` and `_tz` from the request's time zone.
- New `POST /api/technologies/bulk` `{ids, action: switch_off|switch_on}`, at most 500 ids.
- `GET /api/technologies` rows gain `switched_off_at`, `switched_off_tz` and `pages_since_off`.

**Done when:**
- switching off 2 rows from the list leaves them out of the next assessment estimate;
- the flag appears in a test where 10 new pages are added after switching off.

### Item 2. The written time, in the writer's zone (S)

**The time zone, recorded on every write:**
- The portal sends the browser's time zone on every write, as header `X-Time-Zone` from `lib/api.ts sendJson`.
- The API reads it through one dependency, `request_tz()`. An invalid or missing zone falls back to `settings.radar.default_time_zone`.

**The Point of View:**
- Points of View store `composed_tz`.
- The page shows "Written 6 Oct 2026, 2:35 AM CDT", formatted in `composed_tz`.
- The same goes for the PoV list, the technology page, and every other "at" from decisions and switches.
- The 147 existing Points of View have no `composed_tz`, so they use the default.

**Done when:** a Point of View rewritten from a browser set to Asia/Kolkata shows IST, and an old one shows CDT.

### Item 3. Where each skill is used (S)

**What you see:**
- Setup › Skills gains a "Where each skill is used" page, the mock-up F.
- It shows five steps (Collect, Organise, Classify, Assess, Point of View), each skill in its step, and recipes as dashed boxes with their skills inside.
- Each skill shows its last-run calls and tokens (item 4).
- It prints cleanly.

**API:** new `GET /api/skills/map` → `{stages:[{id, name, recipes:[{recipe_id, calls_last_run}], skills:[{name, title, agent, enabled, calls_last_run, tokens_last_run}]}]}`.
- Calls and tokens come from `llm_calls` once item 4 is in.
- Until then, today's derived counts from the preview are used.

**Done when:** every skill in `prompts` appears exactly once, and a switched-off skill is shown as off.

### Item 4. Record tokens, and reuse the fixed opening (M)

**Recording:**
- `LLM.ask` gains keyword arguments `blocks` (fixed system blocks) and `context` (run_kind, run_id, tech_id, recipe, skills).
- It reads usage from the reply and writes `llm_calls`:
  - **Anthropic:** `usage.input_tokens`, `output_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`;
  - **OpenAI:** `usage.input_tokens`, `output_tokens` and `input_tokens_details.cached_tokens`.
- A failed call is recorded with `ok: false`.

**Reuse:**
- **Anthropic:** `system=[{type:text, text, cache_control:{type:ephemeral}} …]`. The marker goes on the last fixed block, and on the fabric part where there is one.
- **OpenAI:** `instructions` holds the fixed part. Nothing else is needed.

**Context everywhere:** the callers set it through a context variable, so call sites change in one line: engine, summarize, resolver, pov, classify, find_evidence and import matching.

**API:**
- `GET /api/usage?run_id=` returns totals by skill.
- `GET /api/usage/recent?limit=10` returns per-run totals.

**Portal:** Operations shows tokens per run, by skill, with in, out and reused. Each skill's page shows its last-run tokens.

**Done when:**
- a collection, an organise and a Point of View all write `llm_calls`;
- the sum of `ok` calls equals the run's call count;
- a second identical stacked call reports reused tokens (Anthropic).

### Item 5. Stacked calls; assessment as technology call + fabric calls (L)

**What changes in the engine** (`assess_technology`):
1. **The dossier:** signals-first selection, under the lowered ceiling.
2. **The technology call:** recipe `technology`. It stacks:
   - `fabric_relevance`;
   - the 5 technology-scope measures;
   - `watch_metrics`;
   - and, once item 8 has seeded their lists, `domain_subdomain`, `trl_level` and `commercial_availability`.
   - **A check in code flags disagreement** between the TRL level and the Maturity (TRL) score, using the measure's own anchors (0–2 ↔ TRL 1–3, 5 ↔ TRL 4–6, 8–10 ↔ TRL 7–9), and lists it at Gate 2.
3. **One fabric call per relevant fabric:** recipe `fabric`. It stacks the 5 fabric-scope measures, plus `value_levers` once item 12 is built.
4. **Tata measures** (`scope: tata`) aren't asked. Their score comes from active `tata_entry` decisions. Without one they're unscored, with `missing: "waiting for Tata"`.
5. **Assessments are assembled** for each fabric. Technology-scope results are copied into each one.
6. **Placement** is computed from the scores after `hand_score` and `tata_entry` are applied (item 6).
7. **The technology's `classification`** is updated from the technology call, with `source: assessment`, for domain, TRL and availability.

**Measure scope:**
- It's edited on Setup › Measures as "Scored per technology / Scored per fabric / Entered by Tata", and seeded.
- Changing it takes effect at the next run.

**Estimate:** `calls = 1 + gated fabrics` per technology, plus retries. The last run's numbers become 147 + 346 = 493 calls, against about 4,450.

**Rollout:**
1. **Run the sample comparison, recorded in this folder.**
   - Re-assess the same 20 technologies with both engines: a mix of P1–P6, held, and many-fabric.
   - Compare per-measure scores, the unscored share, and priorities.
   - Then switch.
2. **Keep the old per-measure path until you've signed off the comparison,** then remove it in the same plan.

**Done when:**
- the comparison is written up and you've seen it;
- a run with the new engine records `llm_calls` ≤ 1 + gated fabrics + retries per technology;
- the preview shows both recipes.

### Item 6. Gate 2: overrides and unscored measures (M)

**The technology page:** a technology's assessment becomes a tab per fabric, as in mock-up C. The old assessment address redirects there.

**Each fabric tab shows:**
- **The priority,** with how soon and how big, each with "x of y scored".
  - "Override priority…" sets P1–P6 and requires a reason.
  - The computed priority stays visible: "P1 · override in force (computed P3): <reason>, 21 Oct, 9:40 AM CDT".
  - A technology held beside the grid can be placed this way (B16).
- **Each measure,** with its score, reason and sources, or one of these:
  - **unscored:** shows what's missing, with **Score by hand** (0–10 and a required reason), **Accept the gap**, and **Find evidence** (item 10);
  - **waiting for Tata:** shows **Enter** (0–10 and a required reason);
  - **scored by a person** or **gap accepted:** both show who, when and the reason, and either can be undone.

**What happens after a decision:**
- **Recompute:** a decision recomputes that pair's placement on the spot, with no model call.
- **Across runs:** an override lasts across runs. A later run that computes a different priority flags it: "computed moved from P3 to P2 since this override".
- **Recomputing for a settings change** never touches overrides.
- **Hand scores** stay until removed. If a later run scores the measure from evidence, both are shown, and the person's score is used.

**The Gate 2 list (Briefing):** counted by technology, not by measure, and ordered so that items blocking a placement come first.
- unscored measures not settled;
- measures waiting for Tata;
- overrides whose computed priority moved;
- suggested use cases (item 12);
- finance inputs missing at Proof of concept or later (item 12).

**API:**
- `POST /api/decisions` with `{kind, tech_id, fabric_id?, measure_id?, field?, key?, value, reason?}`. A missing required reason gives 422 with the reason.
- `DELETE /api/decisions/{id}` deactivates a decision.
- `GET /api/decisions?tech_id=`.
- `GET /api/technologies/{id}/assessment?fabric=` returns a pair with decisions applied: effective priority, measure states.
- `GET /api/pipeline` gains `gate1` and `gate2` lists in place of `for_analyst`. `for_analyst` stays until the portal moves over.

**Done when:**
- an override on Agentic AI · Interaction shows on the technology page, the Points of View list and the grid, with its reason;
- a hand score on an unscored measure that feeds how big turns a held pair into a placed one;
- removing either restores the computed state.

### Item 7. Organise the technologies (M)

**One status per technology** (`services/radar_status.py`, building on `evidence.py`):

| Status | Rule | Reason shown |
|---|---|---|
| Switched off | `enabled` false | "Switched off on {date}" (+ wake flag) |
| Tracked, placed | latest assessment with any fabric placed (computed or overridden) | "P3 in Cloud, Interaction, IoT" |
| Tracked, held | latest assessment, no fabric placed | "How soon couldn't be scored", taken from the placement composites |
| Ready to assess | not assessed, and evidence `strong` or `enough`; if unclassified, pages ≥ `evidence_floor` | "Evidence judged enough" / "3 pages" |
| Thin evidence | not assessed, and evidence `thin` or `not_credible`; if unclassified, 0 < pages < floor | the verdict's reason / "2 of 3 pages" |
| No evidence yet | 0 pages | "Imported Oct 21" / "Added by hand" |

Today's states (assessing, stopped partway, new evidence, no Point of View) become notes on the row.

**Views** (`view=`):
- `tracked`;
- `not_assessed`;
- `emerging`: effective availability in `emerging_availability`;
- `emerging_new` (new to Tata): emerging and not imported;
- `mature_not_on_tata`: Mature and not imported;
- `nascent`: flagged, with no "no" decision;
- `imported_thin`: imported, and thin or no evidence;
- `off`.

**Filters:** availability, domain, trl (a range), evidence, fabric, q. Every view and filter returns counts.

**Columns:** tick box, technology, where it is (status and reason), commercial availability (value and source), TRL, domain › sub-domain, evidence (verdict, pages, sources), on/off.

**Briefing (Gate 1 list):**
- possible nascent;
- import matches to accept;
- ready to assess, with the cost;
- switched off with new pages.

**API:** `GET /api/technologies` gains `view` and the filters, plus `view_counts`. Rows gain `status`, `status_reason`, `notes`, the effective classification with its sources, `origin` and `imported`.

**Done when:**
- every one of the 1,150 technologies has exactly one status with a reason;
- the counts add up;
- a first-time reader can find "imported, but no evidence" in one click.

### Item 8. Classify every technology (L)

**When it runs:**
- **After organise, at the end of every collection.** It covers technologies that are new or have pages not in `pages_seen`, and that are switched on.
- **On demand:** "Classify N technologies" (cost first) on Operations and on the Gate 1 list.
- **"Re-classify"** after a list definition changes. It covers technologies whose `list_versions` are older.

**This item also adds `domain_subdomain`, `trl_level` and `commercial_availability`** to the assessment's `technology` recipe (item 5), now that their lists exist.

**One call per technology**, recipe `classify`:
- **Skills, stacked:** `evidence_strength`, `domain_subdomain`, `commercial_availability`, `trl_level`, `possible_nascent` (item 9).
- **The evidence,** bounded:
  - the newest visit per page; pages with kept signals for this technology first, then the newest; at most `classify_pages_cap`;
  - each page as `[n] source name (kind) · date · title`, then its summary and its signals' word-for-word quotes;
  - **the facts:** total pages, independent sources, and the source kinds.
- **Incremental:** a technology classified before gets its CURRENT ANSWERS with their reasons, plus only the pages not in `pages_seen`.
- **The reply is checked:**
  - ids must exist in the lists; an unknown sub-domain becomes `subdomain_new`;
  - TRL is an integer from 1 to 9;
  - each answer has a reason of at most 20 words, and pages from the numbered list.
- **The budget:** the step stops at `classify_token_budget` and records "Stopped: token budget of N reached; M technologies left". Those wait for the next run.
- **Effective values:**
  - **availability, domain, TRL:** a person's decision first (`move`, import, nascent yes), then the assessment, then Classify, then Unclassified or Other.
  - **evidence:** from Classify only.

**Setup › Classification** has tabs for Commercial availability, Domains and sub-domains, and TRL levels, edited like Fabrics.
- **Sub-domains:** a list grouped by domain, with "new" ones to accept, merge or rename.
- **What an edit does:**
  - **add:** applies from the next classification;
  - **rename:** applies at once, with no model call;
  - **definition change:** marks the technologies classified under the old wording and offers "Re-classify N" with the cost;
  - **remove:** moves its technologies to the catch-all, marked for review.

**The technology page** shows four answers, each with "Why?" (the reason and the numbered pages) and "Change" (a move), except evidence, which can't be changed.

**API:**
- `POST /api/classify` `{tech_ids?|all_pending: true}` (202; the cost first via `GET /api/classify/preview`).
- `GET /api/classify/runs`.
- CRUD on `/api/lists/{availability|domains|subdomains|trl_levels|path_steps|mechanisms}`.
- `POST /api/lists/subdomains/{id}/merge`.

**First pass:** 1,150 technologies, so 1,150 calls. Evidence averages about 600 tokens per call, with at most about 3,500. The fixed part, about 5–6k tokens, is reused.

**Before switching it on:**
- **Sample:** 50 technologies, including the 52 that match Tata's file exactly.
- **Compare** domain, TRL and availability with Tata's labels, and report the agreement and the tokens.

**Done when:**
- every switched-on technology with pages has a classification with reasons;
- a definition edit marks the right technologies;
- the budget stop says why.

### Item 9. Possible nascent (S)

**The skill:**
- `possible_nascent` is stacked in the Classify call.
- It answers only when it flags: "the technology itself looks new, and its pages show a strong early sign (a large funding round, a solid research result, a first named deployment, a spin-out, a new standard effort)".
- A flag carries a reason, a word-for-word quote, and the page.
- It sees the evidence verdict and the signals in the same evidence.

**What you see:**
- **Gate 1 list and the `nascent` view.**
- **"Yes, nascent":** availability moves to Research, or Pilot if the flag cites a deployment or trial, as a person's choice. The technology can then be assessed despite the floor.
- **"No":** a dismissal. It's flagged again only if a page arrives that wasn't seen when the "no" was given.

**Done when:** a single-page technology with a named-deployment signal and a new-technology reason shows on the list, and "No" takes it off.

### Item 10. Find evidence (M)

**Where the buttons appear:**
- a thin or no-evidence technology;
- an unscored measure;
- a fabric with no use case, as "Find use cases";
- plus "Add a link" beside each.

**What happens:**
1. **The query** is built from the gap: the technology's label, the fabric name, and the measure's `missing` or the use case's `evidence_needed`, cut to about 12 words.
2. **The web search** returns `find_evidence_results` addresses.
3. **Known addresses are skipped.**
4. **The rest are read like any collected page.**
   - Our crawler fetches them, and `summarize_page` reads them.
   - They're saved under a small run of kind `find_evidence`, with source `web_search`.
   - Then they're stamped. If a page brings new raw names, a small organise runs.
5. **Only the call behind the gap is re-run:**
   - **technology:** Classify for that technology;
   - **measure:** that one measure's single-skill call, for that technology and fabric;
   - **use case:** that fabric's call.
6. **The result is recorded on the job and shown:** "3 new pages from 5 results (2 already collected). Addressable market is now scored 6: …", or "Nothing new found", with the query that was used.

**Limits:**
- only a person starts it;
- the cost is shown first: one search, about 5 page reads, and one re-run;
- there's a daily budget, counted in the default time zone;
- pages it finds are marked "found by Find evidence on {date, time, zone}".

**The search service:** `WEB_SEARCH_PROVIDER` and `WEB_SEARCH_API_KEY` in `.env`, behind one adapter, `search(query, n) → [{url, title, snippet}]`.
- **Which service is open** (review-notes section 5). The plan compares the model provider's own web search with a search API such as Brave or Tavily.
- **Until a key is set,** the buttons say "Find evidence needs a web search key (Setup › Crawl settings)". "Add a link" still works.

**API:**
- `GET /api/find-evidence/preview?gap…` returns the cost.
- `POST /api/find-evidence` `{gap}` (202).
- `GET /api/find-evidence/{id}`.
- `POST /api/find-evidence` `{gap:{kind: link, url, tech_id, …}}` adds a link.

**Done when:**
- "Add a link" on an unscored measure, with a page that contains the missing figure, scores it;
- with no key, the button explains why;
- the daily budget stops a 21st search with the reason.

### Item 11. Import a list of emerging technologies, and add one by hand (M)

**The file:**
- `.xlsx` only, laid out like Tata's "New Emerging Technologies" tab.
- **Columns:** Technology Name (required), then Domain, Sub-domain, Description, TRL and Commercial Availability.
- **The sheet used** is the one with these headers. Any other sheet, such as Technologies Tracked, is ignored.
- **A file that doesn't fit is refused** with the reason, for example "No 'Technology Name' column in any sheet".
- **The template** is a download.

**The steps** follow mock-up E:
1. **Upload.**
2. **Check and clean.** Trim, drop blanks, and merge repeats.
3. **Match.**
   - Exact name or alias: no cost.
   - The rest go to `technology_resolve` against the whole register, in chunks, with the cost shown first.
4. **Review.** Nothing is saved yet. The groups are:
   - **Matched exactly;**
   - **Proposed matches,** accepted or rejected singly or all at once. A rejected match becomes new;
   - **New;**
   - **Values not in our lists,** each mapped to an entry or added.
5. **Confirm.**
   - **A match:** the file's wording becomes an alias, and the technology gets `imported` and the row's values as person decisions (availability, domain, sub-domain, TRL).
   - **A new one:** a technology with `origin: imported`, 0 pages, and the row's values as decisions.

**What imports mean:** the importer's values are person choices. A row marked Mature comes in as Mature, and a row with no availability counts as emerging until classified.

**Organise:** `known_register` always includes imported names. Today it keeps only the top 1,500 by pages, so imported names with 0 pages would be cut.

**Uploading again** updates the list and never duplicates. Each import is kept on record.

**Add by hand:** "+ Add technology" is a one-row import, matched the same way, with optional values.

**Not seeded while the import is tested** (decided 20 Oct). Later this week, the lists are written to the seeds.

**API:**
- `POST /api/imports` (multipart).
- `GET /api/imports` and `GET /api/imports/{id}`.
- `POST /api/imports/{id}/match` (cost first, `GET …/match/preview`).
- `PUT /api/imports/{id}/items` `{rows, decision}`.
- `PUT /api/imports/{id}/values`.
- `POST /api/imports/{id}/confirm`.
- `DELETE /api/imports/{id}` discards a review.
- `GET /api/imports/template`.
- `POST /api/technologies` `{name, values?}` adds one by hand.

**Done when:** Tata's file imports, with 52 exact matches, a proposed group, values to map, and the rest new, and re-importing changes nothing.

### Item 12. The Point of View: use cases, levers, path to scale, finance, maturity with sources (L)

**Value levers:**
- `value_levers` is stacked in the fabric call.
- **For each technology and fabric, it returns:**
  - **up to 2 use cases** the pages support, each cited;
  - **two levers per use case,** from the fabric's list. Each is written as Nick's chain: operating change → metric → financial effect → evidence needed → next step when. Each link cites pages, or says what's needed;
  - **the capital direction.**
- **With no use case in the pages,** it gives `no_use_case`, and it may give up to 2 `suggested` use cases. These have no citations and no figures, and they go to the Gate 2 list.
- **Its text carries Nick's five rules and the fabric's cautions.** It never writes a figure.

**Path to scale:**
- **The steps:** Tri's 7 (Evaluation → Customer zero → Proof of concept → One customer → Beta → Roadmap → Investment), seeded with Nick's evidence on the matching steps.
- **Recording it:** a `path_step` decision for each technology and fabric, set on the fabric tab.

**Finance:**
- **The inputs:**
  - fabric defaults on Setup › Fabrics (margin range, loss rates);
  - per pair, a `finance` decision (upfront, running, revenue, and an optional margin), on a card that stays folded until the path to scale reaches Proof of concept.
- **The arithmetic** is in `services/finance.py`, and runs only when the inputs exist:
  - contribution = revenue × margin;
  - payback = upfront ÷ (contribution − running);
  - break-even = running ÷ margin.
- **Each figure says where it came from,** for example "35%, fabric default".
- **A missing input is named,** for example "Payback needs: upfront investment".
- **Setup › Finance** is a table of every pair with inputs, or at Proof of concept or later, with a "missing inputs" filter.

**The Point of View:**
- **What the writer gets** (`assessment_data`):
  - the classification, with reasons and `[n]` references;
  - use cases and levers;
  - path step, finance figures, overrides, hand scores and Tata entries;
  - a numbered SOURCES list, built by code from every cited page.
- **New sections:** `value` and `maturity`.
- **What the page renders as structured blocks,** not model text:
  - the levers (chain cards);
  - the path bar;
  - the finance figures;
  - the numbered sources (source · date · headline, linking to the page).
- **The order:** verdict → priority, maturity, availability, evidence → where the value lands → path to scale → finance → the narrative sections → sources.

**B9:** market size and the other numbers carry their reasons and sources the same way.

**Rewrite:** every Point of View is rewritten once, at the end: 147 calls.

**Done when:**
- Agentic AI's Point of View shows TRL with numbered sources, at least one use case with a full chain, the path bar, and the finance screen saying what's missing;
- every `[n]` resolves to a page.

### Item 13. Frontier at its own address (L)

**Two sides from one codebase:**
- A setting, `APP_SIDE` (`admin` | `frontier`), is read by `proxy.ts` in tech-lens, which is Next.js 16's name for middleware.
- **The frontier side:**
  - `/` serves `/frontier`;
  - every `/admin` path redirects to `/frontier`;
  - every `/api` request except an allow-listed GET is refused with 403 "Not available on the executive address".
- **The admin side:** `/frontier` redirects to `/admin`, and an admin preview link opens the executive address.

**Compose:** a `frontier` service from the same image, with `APP_SIDE=frontier`, on port 3200.

**First version:**
- the 2×2, using effective priorities including overrides, with a fabric filter and zoom;
- a table beside it;
- the not-yet-placed list with reasons;
- a read-only Point of View from a dot.
- **API:** `GET /api/frontier?fabric=`, read-only.

**Settled when it's built:**
- publishing;
- the lenses (B20);
- the frontier line (B21);
- assumptions in force (B22);
- evidence this edition (B23);
- what a leader records (B12).

**Logins come later (B26).** The separate address isn't access control.

**Done when:**
- the executive address can't reach any admin page, or any write;
- the 2×2 and the table agree;
- a Point of View opens read-only.

---

## 7. API summary (new and changed)

| Method · path | Item |
|---|---|
| `POST /api/technologies/bulk` | 1 |
| `X-Time-Zone` header on writes (`request_tz`) | 2 |
| `GET /api/skills/map` | 3 |
| `GET /api/usage`, `GET /api/usage/recent` | 4 |
| `GET /api/prompts/{name}/preview` gains `recipe=` | 5 |
| `POST/DELETE/GET /api/decisions`, `GET /api/technologies/{id}/assessment` | 6 |
| `GET /api/pipeline` gains `gate1`, `gate2` | 6, 7 |
| `GET /api/technologies` gains `view`, filters, `view_counts`, `status` | 7 |
| `/api/classify` (preview, start, runs), `/api/lists/*` | 8 |
| `/api/find-evidence` (preview, start, get) | 10 |
| `/api/imports` (upload, get, match, items, values, confirm, discard, template), `POST /api/technologies` | 11 |
| `GET /api/finance`, finance figures in assessment and PoV responses | 12 |
| `GET /api/frontier` | 13 |

## 8. Skills summary

| Skill | New or changed | Recipe | Output key(s) |
|---|---|---|---|
| `evidence_strength` | new | classify | `evidence_strength` |
| `domain_subdomain` | new | classify, technology | `domain_subdomain` |
| `commercial_availability` | new | classify, technology | `commercial_availability` |
| `trl_level` | new | classify, technology | `trl_level` |
| `possible_nascent` | new | classify | `possible_nascent` |
| `value_levers` | new | fabric | `value_levers` |
| `measure_scoring` | the text makes the block form explicit. TRL comes from `trl_level` in the same call, and code flags any disagreement with the Maturity score | technology, fabric | `measure:<id>` |
| `fabric_relevance`, `watch_metrics` | unchanged text | technology | own key |
| `pov` | new sections `value`, `maturity`; cites `[n]` | single | sections |
| `technology_resolve` | unchanged; reused by import | single | groups |

**The new skills' first texts** are written in the implementation plan and tested on the sample before they're switched on.
- They follow the existing house rules: cite or abstain; plain words; names, not codes.
- Each is visible and editable in Setup › Skills, and has a preview.

## 9. Tokens and cost, on the last run's numbers

| Step | Calls today | Calls after | Note |
|---|---|---|---|
| Assessment (147 technologies) | about 4,474 | about 493 + retries | The evidence is sent about 3.4 times per technology instead of about 30, and the fixed part is reused |
| Classify, first pass | — | 1,150 | Then only technologies with new pages |
| Possible nascent | — | 0 extra | In the Classify call |
| Value levers | — | 0 extra | In the fabric call |
| Point of View rewrite | 147 | 147 (once) | |
| Find evidence | — | 1 search + ~5 page reads + 1 re-run per press | Started by a person, with a daily budget |
| Import matching (Tata's file) | — | about 10 chunks | Cost shown first |

The real token numbers are measured by item 4 and reported per item before and after.

## 10. Rollout and risks

**Order:** item 0 (fixes Q1–Q5) → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13. Each item:
1. builds and passes its tests, plus a browser walk as a first-time reader;
2. gets screenshots for the client document;
3. is shown to you before the next item starts.

**It's saved as a version (git commit) only when you say,** and a push needs its own yes.

| Risk | Mitigation |
|---|---|
| **A new seed file reloads every list** and overwrites live edits not yet in seeds | Before deploying an item that adds seed files: confirm Changes = 0, and back up the database (`mongodump`, kept in this folder's `replaced/`) |
| **Stacked measures blur together** | The 20-technology comparison before switching (item 5), and the old path kept until you sign off |
| **Classification disagrees with Tata's labels** | The 50-technology sample against Tata's file before switching on (item 8). Disagreements are listed for review |
| **Gate lists grow too long to use** (2,408 unscored measures) | Counted by technology, and ordered by what blocks a placement (item 6) |
| **Web search cost or terms** | One adapter, a daily budget, and a person-started button. The provider is chosen in review-notes section 5 |
| **Two portal copies drift** | Same image and the same code. One setting picks the side |
| **Old links into assessment pages** | Redirects to the technology's fabric tab |

## 11. Open questions and assumptions

These come from review-notes section 5.
- **Open:**
  - which web search service;
  - where B5 (split) and B10 (inflection points) go;
  - folding Ankur's tests into calibration.
- **Assumed:**
  - the path to scale per fabric;
  - the blockchain domains merged;
  - the catch-all names "Unclassified" and "Other";
  - old Points of View shown in US Central;
  - the wake flag at 10 pages;
  - `max_dossier_tokens` 40,000, until item 4 measures it.
