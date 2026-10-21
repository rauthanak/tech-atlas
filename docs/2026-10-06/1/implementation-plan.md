# Plan 8: What a skill turns into (tech-atlas)

**Date:** 2026-10-06 · **Folder:** 2026-10-06/1 · **Status:** approved on 6 Oct ("once the assessment is done… go ahead and implement it"), with D1–D3 as recommended. All three phases built, tested and live on Docker the same day; build notes in §10.

**Portal half:** [tech-lens plan 8](../../../../tech-lens/docs/2026-10-06/1/implementation-plan.md), covering the screen, its words and its checks.

**Where this came from:** your idea of 6 Oct. When an admin clicks a skill in Setup › Skills, they should see how many versions of it the radar sends, with which data and in which situations. That way a future admin can see what a skill turns into once the rest of the configuration fills it in.

---

## 1. Summary

**What the skill page lacks today.** It shows the skill's text, where the skill acts, and its blanks as bare chips (`{fabric_name}`). It doesn't show what fills the blanks, how many versions one skill becomes, or what the model actually receives. That last part matters more than it looks. Measure scoring's own text is about 1,500 characters. When it scores Agentic AI, the filled-in prompt is about 103,000 characters: 98% of what the model reads comes from other configuration and the collected pages.

**What this plan adds.** Each skill's page gets one new section, **What it turns into**, in three parts:

| Part | What the admin sees | Example: Measure scoring |
|---|---|---|
| **How many versions** | What multiplies the skill, with today's numbers, and how many prompts the last run sent | 12 measures × up to 6 fabrics = up to 72 versions per technology · last assessment run: about 4,200 prompts |
| **Where the blanks are filled from** | Each blank and the Setup page or data that fills it, linked to where it's edited | `{definition}` ← Scoring method › Measures |
| **A real one** | The whole prompt exactly as the model would receive it, built from real data and today's settings. Switches change the case, and each filled-in part is marked with where it came from | Technology: API security · Fabric: Security · Measure: M1 Addressable market · about 2,700 tokens |

**Optional, your call (phase 3):** the same view for an edit you haven't saved yet, so you can see what an edit will turn into before it goes live.

**What doesn't change:**
- **No model calls.** Building a preview costs nothing.
- **No settings and no seeding data.** Changes stays at 0.
- **Runs behave exactly as today.** The only change to run code is moving the lines that fill each skill into a small named function (§3.1), and the text sent stays the same, character for character.

**The rule that keeps it honest:** the example is built by the same code that builds the real prompt.
- Each skill gets one small fill function, and both the run and the preview call it.
- A test runs each real step with a stand-in model that only records what it's sent. That text must be identical to the preview's (§6).

Without this rule, the preview would slowly drift away from what really runs.

---

## 2. What each skill turns into

This is what the new section will show, with today's numbers. The last runs are collection `a4795679954e` (6 Oct) and assessment run `6d0c41a2d13d`, which is still going as this is written.

| Skill | When it's used | Versions today | Blanks ← where they're filled from | Switches in "A real one" | Last run |
|---|---|---|---|---|---|
| **Orchestrator** | Once per collection run. Agent instructions (see note 1), at most 20 steps | 1 | none | none | 1 |
| **Supervisor** | Once per horizon. Agent instructions, at most 20 steps | 3: H1, H2, H3 | `{category}` ← the horizon | Horizon | 3 |
| **Scout** | Once per batch of up to 5 sources in a horizon (`SOURCES_PER_SCOUT`, a server setting). Agent instructions, at most 10 steps plus 4 per source | 3: H1 has 5 sources, H2 has 4 and H3 has 4, so one batch each | `{category}` ← the horizon<br>`{sources}` ← Sources: each source's id, name and address<br>`{max_depth}` ← server setting `SCRAPE_MAX_DEPTH` (8)<br>`{max_pages}` ← Crawl settings › pages per source (60) | Horizon | 3 |
| **Link selection** | At each level of a website's crawl that finds more links than it may follow (the smaller of the pages left and 15, which is fixed in code) | Up to 8 per website, one per level (`SCRAPE_MAX_DEPTH`), × 11 websites = up to 88 | `{budget}` ← the pages left (Crawl settings › pages per source), at most 15<br>`{never_miss_names}` ← Signal list: the 29 never-miss names<br>`{links}` ← the links found at that level | Source: the 11 websites | **Not counted:** the crawler doesn't record these calls |
| **Article summary** | Once per new or changed page. A page longer than 120,000 characters (Crawl settings › page part size) is split: once per part, plus one merge | One per page | `{never_miss}` ← Signal list: the 29 never-miss types, each with what to look for<br>`{can_ignore}` ← Signal list: the 7 can-ignore rules<br>`{url}`, `{text}` ← the page, or one part of it | Source, then page | 645: 623 pages, of which 8 were split into 22 parts, plus 8 merges |
| **Technology resolve** | When technologies are organized: pass 1 over the names not yet in the register, then pass 2 over all names, in chunks of 4,000 (`RESOLVE_BATCH_SIZE`) | One per chunk | `{known_list}` ← the technology register: the top 1,500 by pages (`RESOLVE_KNOWN_LIMIT`)<br>`{tech_list}` ← the new names from collected pages | none | 5, together with Technology label (see note 3) |
| **Technology label** | Once per batch of up to 500 names that have no display capitals yet | One per batch | `{names}` ← technology names without a label (0 of 1,150 today) | none | Included in the 5 above |
| **Analyzer** | Once per assessment run. Agent instructions, at most 60 steps, after which the backup loop carries on | 1 | none | none | 1 |
| **Fabric relevance** | Once per technology per assessment run | One per technology | `{technology}` ← its name<br>`{fabrics}` ← Scoring method › Fabrics: the 6 switched on, each with id, name and definition<br>`{evidence}` ← its collected pages (each page's summary and scout's take), capped by Scoring method › Weights & Grid › evidence ceiling | Technology | 147 |
| **Measure scoring** | Once per measure, for each fabric that Fabric relevance picked, for each technology | 12 measures × up to 6 fabrics = up to 72 per technology | `{measure_name}`, `{definition}`, `{anchors}`, `{required_evidence}` ← Scoring method › Measures<br>`{fabric_name}`, `{fabric_definition}`, `{tcl_today}` ← Scoring method › Fabrics<br>`{technology}`, `{evidence}` ← as for Fabric relevance | Technology, fabric, measure | About 4,200; the exact count goes in once the run ends. For example, API security was scored in 4 fabrics, so 48 prompts |
| **Watch metrics** | Once per technology per assessment run | One per technology | `{technology}`, `{evidence}` ← as for Fabric relevance | Technology | 147 |
| **Point of View** | Once per technology, when Points of View are written | One per technology | `{technology}` ← its display name<br>`{assessment_data}` ← its latest assessment (scores per fabric, TORA, placement, priority, watch metrics and pages read), laid out with that run's measures and priority grid | Technology: only those with an assessment | 147, once this round's Points of View are written |

**Notes:**
1. **Agent instructions.** Orchestrator, Supervisor, Scout and Analyzer aren't one-off prompts. They're an agent's standing instructions, which the agent carries on every step it takes. Their "real one" is the instruction text exactly as the agent gets it. The steps themselves aren't counted.
2. **Stand-in data (decision D2).** Three skills are filled at run time with data the radar doesn't keep. For these, the example uses real data that's close to it, and says so:
   - **Link selection:** the crawler doesn't keep the links it was offered. `{links}` is that source's list of pages from the last collection instead.
   - **Technology resolve:** after an organize, no names are waiting. `{tech_list}` is the raw names found on the 50 newest pages instead. `{known_list}` is exact.
   - **Technology label:** no names are waiting for their capitals today. `{names}` is the first 500 names in the register instead.
3. **Resolve and label counts.** The organize record counts Technology resolve and Technology label calls together, so the section shows one count for the two.
4. **How "last run" is counted.** It counts prompts built, one per use. A retry after a refused or unreadable reply isn't counted again. Each count is worked out from what the runs already store, for example assessments × measures for Measure scoring. Nothing new is recorded.

---

## 3. How it's built (backend)

### 3.1 One fill function per skill, used by the run and the preview

Today each run step fills its skill inline. For example, `engine.py` builds the Measure scoring prompt inside `_score_measure`. This plan moves each of those few lines into a small named function next to where they are now. The function returns the values for the blanks, and the step calls `prompt.render(**values)` as before. The preview calls the same function.

| Skill | New function, in the same file as today's code | Used by the run in |
|---|---|---|
| Supervisor | `supervisor_values(category)` | `agent/supervisor/agent.py`, `Supervisor.build_agent` |
| Scout | `scout_values(category, sources, max_depth, max_pages)` | `agent/scout/agent.py`, `run_scout` |
| Link selection | `link_selection_values(links, budget, never_miss_names)` | `agent/scout/tools/crawl.py`, `select_links` |
| Article summary | `article_summary_values(url, text, lines)` | `agent/scout/tools/summarize.py`, `_analyse` |
| Technology resolve | `resolve_values(names, register)`, plus `known_register()` for the register query | `agent/resolver/resolver.py`, `_llm_groups` and `resolve` |
| Technology label | `label_values(names)` | `agent/resolver/resolver.py`, `label_missing` |
| Fabric relevance | `fabric_relevance_values(technology, fabrics, dossier)` | `agent/analyzer/engine.py`, `_relevant_fabrics` |
| Measure scoring | `measure_scoring_values(measure, technology, fabric, dossier)` | `agent/analyzer/engine.py`, `_score_measure` |
| Watch metrics | `watch_metrics_values(technology, dossier)` | `agent/analyzer/engine.py`, `assess_technology` |
| Point of View | `pov_values(run_id, tech_id)`: everything `compose_pov` does before the model call | `agent/analyzer/pov.py`, `compose_pov` |
| Orchestrator, Analyzer | none: they have no blanks | — |

`assess_technology` also looks up the evidence ceiling inline today. That lookup moves into `dossier_limit(scoring_config)`, so the preview builds the evidence with the same ceiling through the existing `build_dossier`.

These are moves, not rewrites. Each step sends the same text as today, and test 1 in §6 proves it.

### 3.2 The preview service

**New file:** `app/services/prompts/preview.py`. It has one small entry for each of the 12 skills, with:
- `fires`: the sentence for "When it's used";
- `versions()`: what multiplies the skill, with today's counts (measures, fabrics on, sources per horizon, signal types, settings);
- `last_run()`: the count from stored records, as in §2 note 4, or `null` with the reason;
- `blanks`: where each blank comes from, and a link. The list of blanks itself is `EXPECTED_VARIABLES` in `api/prompts.py`, which the Save check already uses, so it's kept in one place;
- `switches()`: the choices, read from stored data;
- `example(choices)`: loads the real data, calls the skill's fill function from §3.1 and renders it.

**Rules:**
- **Today's settings (decision D1).** The example uses fabrics, measures, the signal list, sources and crawl settings as they are now, so it shows what the next run would send.
  - Collection skills use `signals.snapshot.build()`, which a collection itself records at its start.
  - Point of View is the exception, because it reads a stored assessment. It uses that assessment's own run, as `compose_pov` does.
- **Marked parts.**
  - The rendered prompt is split into plain skill text and filled-in blanks. The split uses the same template reading as `str.format` (`string.Formatter`), and doubled braces come out single, as they do at run time.
  - A test checks that the parts join back to exactly what `Prompt.render()` returns.
- **Long values.**
  - Any blank over 200,000 characters comes back cut for display, with the number of characters left out. The model always gets everything; the cut affects display only.
  - Today's largest, Agentic AI's evidence (51 pages), is 99,862 characters, so nothing is cut today. The cut only guards the evidence ceiling's worst case, about 1.2 million characters.
- **Size.** Each example reports its characters and "about N tokens" (characters ÷ 4, the same rule as the evidence ceiling).
- **Defaults.** Each switch starts on a sensible real case: the technology with the most pages in the latest assessment run, its first scored fabric, M1, the newest page of the first source, and H1.
- **Read-only.** No model calls; a test fails if one is made. It's safe to use while a collection or an assessment is running.
- **A switched-off skill** still previews, with a note that its step fails or is skipped while it's off. Today `PromptStore.get` refuses switched-off skills, so the preview reads the skill's record directly.
- **No data yet,** as on a fresh radar: "How many versions" still shows today's numbers, and the example says why it's empty, for example "No collected pages yet: run a collection first."

**Switch choices:**

| Switch | Choices |
|---|---|
| Technology | The technologies in the latest assessment run, most pages first, each with its page count. If there's no assessment run yet: the 200 with the most pages. For Point of View: only those with an assessment, using the same "latest assessment" rule as the rest of the portal (`services/evidence.py`, `state()`) |
| Fabric | The 6 switched on. The ones Fabric relevance picked for that technology in the last run are marked |
| Measure | The 12, in their order |
| Source | The sources switched on. For Link selection, only the 11 websites |
| Page | That source's 50 newest pages, by title and date |
| Horizon | H1, H2, H3 |

### 3.3 A small fix found while planning

`EXPECTED_VARIABLES` in `api/prompts.py` has no entry for Technology label, so Save doesn't check that skill's blanks. A mistyped `{names}` would only show up later as a failed organize.
- **The fix:** add `"technology_label": {"names"}`.
- The preview reads its list of blanks from the same table, so the fix completes that list too.

---

## 4. API contract

Shared with the portal plan.

### `GET /api/prompts/{name}/preview`

**Query parameters** (all optional): `technology`, `fabric`, `measure`, `source`, `page`, `horizon`.
- A parameter that's left out takes its default.
- A value that doesn't exist is refused with 422 and a reason, for example "no technology 'x' in the latest assessment run".

**Response** for Measure scoring, shortened (the numbers are illustrative):

```json
{
  "skill": "measure_scoring",
  "version": 4,
  "enabled": true,
  "fires": "Once per measure, for each fabric Fabric relevance picked, for each technology in an assessment run",
  "agent": false,
  "versions": {
    "factors": [
      {"what": "measures", "count": 12, "from": "Scoring method › Measures", "href": "/admin/scoring/measures"},
      {"what": "fabrics switched on (only the relevant ones are used)", "count": 6, "up_to": true,
       "from": "Scoring method › Fabrics", "href": "/admin/scoring/fabrics"}
    ],
    "count": 72, "up_to": true, "per": "technology"
  },
  "last_run": {"kind": "assessment run", "run_id": "6d0c41a2d13d", "at": "2026-10-06T…",
               "prompts": 4224, "why_missing": null},
  "blanks": [
    {"name": "measure_name", "what": "the measure's code and name",
     "from": "Scoring method › Measures", "href": "/admin/scoring/measures"},
    {"name": "evidence", "what": "the technology's collected pages: each page's summary and scout's take",
     "from": "Collected pages, capped by Scoring method › Weights & Grid", "href": "/admin/scoring/config"}
  ],
  "switches": [
    {"key": "technology", "label": "Technology", "value": "api-security",
     "options": [{"value": "agentic-ai", "label": "Agentic AI · 51 pages"}, {"value": "api-security", "label": "API security · 4 pages"}]},
    {"key": "fabric", "label": "Fabric", "value": "security",
     "options": [{"value": "network", "label": "Network", "scored_last_run": true}],
     "note": "The last run scored API security in Network, Cloud, Interaction and Security: 48 prompts"},
    {"key": "measure", "label": "Measure", "value": "m1",
     "options": [{"value": "m1", "label": "M1 Addressable market"}]}
  ],
  "example": {
    "parts": [
      {"text": "You score one measure …"},
      {"blank": "measure_name", "text": "M1 Addressable market", "cut": 0},
      {"text": "\nDefinition: "},
      {"blank": "evidence", "text": "- [article] …", "cut": 0}
    ],
    "characters": 10671,
    "tokens_about": 2667,
    "built_from": "Today's settings and the pages collected so far",
    "stand_in": null,
    "why_missing": null
  }
}
```

**Fields:**
- `parts[].cut` is the number of characters left out for display. It's `0` when nothing was cut.
- `stand_in` holds the plain note for the three stand-in cases in §2 note 2, and is `null` otherwise.
- `example` is `null`, with `why_missing` saying why, when there's nothing to build it from.
- `agent` is `true` for the four agent skills. The portal then explains that an agent carries the text on every step.

**Errors:**
- 404 for an unknown skill.
- 422 for a switch value that doesn't exist, with the reason.

### Phase 3 only: `POST /api/prompts/{name}/preview`

**Body:** `{system, prompt}`, the unsaved text, plus the same switches.
- It returns the same shape as the GET, built from the draft.
- A draft whose blanks don't match is refused with 422 and exactly the message Save gives, because it uses the same checks (`_extract_variables`, `_check_variables`).
- Nothing is stored.

---

## 5. Phases

| Phase | What | Ends with |
|---|---|---|
| **1 · Backend** | The fill functions (§3.1), the preview service (§3.2), the fix (§3.3), `GET …/preview` and the tests (§6) | A demo of the preview for each of the 12 skills on real data, with the tests passing. Then your sign-off |
| **2 · Portal** | "What it turns into" on each skill's page ([portal plan](../../../../tech-lens/docs/2026-10-06/1/implementation-plan.md)) | A demo in the portal. Then your sign-off |
| **3 · Preview an unsaved edit** (decision D3) | `POST …/preview`; the section follows the text as you type | A demo. Then your sign-off |

**Timing.** The radar has to restart to pick up new code, and a restart would interrupt a running assessment or Point of View batch. So:
- the work is built and tested without touching the Docker radar (the tests use their own database);
- it's deployed to Docker only when no run or batch is going, so after this round's assessment and Points of View;
- the two apps are deployed together, because the portal section needs the new API.

---

## 6. Tests and checks

**Backend tests,** in a new file, `tests/test_skill_preview.py`:
1. **Same text as the run.** This is the key test. For each skill, run the real step with a stand-in model that records the prompt it's sent and calls no one. Compare that with the preview for the same inputs: the two must be identical, character for character. For the four agent skills, the instructions handed to the agent are recorded the same way.
2. **Blanks match.** Each fill function returns exactly the blanks that the skill's text uses (`EXPECTED_VARIABLES`).
3. **Marked parts join back** to exactly the rendered prompt, for every skill.
4. **No model calls** during any preview.
5. **Edge cases:**
   - an unknown skill gives 404;
   - a switch value that doesn't exist gives 422 with the reason;
   - with no collected pages, the example is empty and says why;
   - a switched-off skill still previews, with the note;
   - a blank over 200,000 characters is cut for display, with the right count.
6. **Phase 3:** a draft with a missing or unknown blank gets the same 422 message as Save, and nothing is written.

**Existing tests:** all 85 must still pass. The moves in §3.1 change no behaviour.

**After deploying:**
- Changes is 0, and the live settings equal the seeding data.
- All 12 previews work on Docker's data.
- **Spot check:** for one technology, the evidence in the Measure scoring example lists as many pages as its stored assessment read (`doc_count`).

---

## 7. Decisions for you

- **D1. Built from today's settings.** The example shows what the next run would send, not the copy of the settings frozen in the last run.
  - *Recommended.*
  - The other way shows what happened rather than what will happen. That suits an audit, not an admin who is about to make a change.
- **D2. Stand-in data where the real data isn't kept.** This covers Link selection, Technology resolve and Technology label (§2 note 2). The example uses close real data and says so.
  - *Recommended.*
  - The alternative is for each collection to keep one real sample per source of the links it was offered. That's a small change to the crawler, worth making only if Link selection gets edited often.
- **D3. Phase 3: preview an unsaved edit.**
  - *Recommended.* It answers "what will my edit do?" at the moment it matters.
  - It costs one more endpoint and no model calls.

---

## 8. Not in this plan

- Counts on the Skills list page. Your idea was about clicking into a skill.
- A record of every prompt actually sent.
- Costs in money.
- Editing measures, fabrics or signals from this view. The links take you to their own pages.
- Counting link-selection calls. D2's alternative would make that possible later.

---

## 9. Risks

- **Moving run code (§3.1).** Each move is small, and the text sent stays the same. Test 1 checks this for every skill, and the existing 85 tests still run. The change is deployed only between runs.
- **Large examples.** Evidence for a big technology runs to about 100,000 characters. The portal folds long parts, and the API cuts any blank over 200,000 characters for display.
- **The example can differ from a later run** if pages are collected or settings change in between. The section says what it was built from.

---

## 10. Build notes

Built on 6 Oct, after assessment run `6d0c41a2d13d` finished. It went live once the Points of View had been written, because a restart would have interrupted them. All three phases were built in one go, since you asked to be told once it was done. D1, D2 and D3 went as recommended.

**Built as planned:**
- **§3.1, the fill functions.** Each is a move, not a rewrite.
  - Two changes in shape beyond the plan's table:
    - Link selection was a function inside the crawl. It's now `select_links(llm, prompt, links, budget, never_miss_names)` at module level, so the test can run the real step.
    - Point of View's function is `pov_inputs(run_id, tech_id)`. It returns the assessments as well as the blanks, because `compose_pov` stores their ids.
  - One slip, found in review and fixed: the organize step's fill had moved outside its retry block, so a fill error would have stopped the organize instead of skipping one chunk. It's back inside.
- **§3.2, the preview service:** `app/services/prompts/preview.py`.
- **§3.3, the small fix:** `EXPECTED_VARIABLES` now checks Technology label too.
- **§4, the API:** `GET` and `POST /api/prompts/{name}/preview`, in `app/api/prompts.py`.

**Small differences from the contract in §4:**
- `example` is never `null`. When there's nothing to show, its `parts` list is empty and `why_missing` says why.
- Each blank also carries a short `tag`, such as "Measures" or "the page", for the label inside the example.
- `versions.sentence` holds the ready-made sentence, and `versions.set_in` lists where each part of it is set.
- `last_run` adds `status` and a `note`. The note explains, for example, that resolve and label are counted together.

**Tests:** `tests/test_skill_preview.py` has 14 tests, and all 99 backend tests pass.
- One test per kind of step runs the real step with a stand-in model that records what it's sent, and checks it against the preview, character for character. This covers all 12 skills, including the four agent skills, whose instructions are recorded as the agent receives them.
- **Proof the test bites:** I made the preview's scout page budget 61 instead of 60, and the test failed. Restoring it made the test pass again.

**On Docker's real data** (first in a throwaway, read-only container, then live):
- All 12 previews answer in under 0.06 s.
- Last-run counts: collection 645 page summaries; organize 5 (resolve and label together); assessment run 147 relevance checks, 4,152 measure prompts (the plan estimated about 4,200), 147 watch metrics and 147 Points of View. Link selection says "Not counted" and gives the reason.
- Largest example: Measure scoring for Agentic AI, at 103,061 characters (about 25,800 tokens). Nothing needed cutting.
- **Spot check:** for API security in Security, the example's evidence lists 4 pages, and the stored assessment read 4.
- Errors: an unknown skill gives 404, and an unknown technology gives 422 with "no technology 'zzz' in the latest assessment run".
- Changes is 0. Plan 8 changed no settings, so the seeding data is untouched.

**Portal:** see the [portal plan's build notes](../../../../tech-lens/docs/2026-10-06/1/implementation-plan.md).

**Saved as a version?** No. As usual, nothing is committed until you ask.
