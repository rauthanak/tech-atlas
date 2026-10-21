# Implementation plan 2: the Tech Lens redesign, backend (tech-atlas)

**Date:** 2026-10-03 · **Plan:** 2, the day's second · **Status:** frozen and signed off on 2026-10-03. Implementation is under way, phase by phase.
**Revised 3 Oct:** phase 0 now also:
- keeps a renamed technology as one technology;
- records why a page couldn't be analysed;
- ends with one collection on the deployed stack.

**Revised again 3 Oct, after review:**
- new evidence compares the page versions an assessment actually read (§5.1);
- one readiness rule for assessments and Points of View, including runs that stop partway (§5.1);
- back links keep your filters (portal plan §6.2);
- estimates are approximate and come from the configured measures and fabrics (§4.1).
**Design it builds:** [UI-suggestions.md](../../../../tech-lens/docs/2026-10-03/2/UI-suggestions.md), as revised on 3 Oct.
**Portal plan:** [tech-lens implementation-plan.md](../../../../tech-lens/docs/2026-10-03/2/implementation-plan.md).
**Builds on:** [plan 1](../1/implementation-plan.md), which is built and running.

This file is the master. It holds:
- the phases;
- the backend work;
- the API contract both apps share (§9);
- testing and deployment.

The screens are in the portal plan.

---

## 1. What we're building

The redesign has five parts:
- findings first, on the Briefing;
- one page per technology, the hub;
- the whole process in one place, Operations;
- all configuration in one place, Setup;
- plain words and the Tata Communications look.

It comes in five phases. Each ends with a demo and your sign-off before the next starts.

| Phase | What you'll see | Backend work | Seeding data reloads on deploy | Size |
|---|---|---|---|---|
| **0 · Before the next collection** | "Can ignore" everywhere; a renamed technology stays one technology; every page that couldn't be analysed says why | Rename the stored value and the skill text; the organizer keeps existing ids; failure reasons are stored | Yes: signals, skills | Small |
| **1 · Look and words** | Tata Communications look; top menu with Operations and Setup; status pill; plain words; the cost on every model button | Cost estimates, plain words in API messages, error count | No | Large, mostly portal |
| **2 · Briefing** | Briefing home; one Signals feed with a side panel; next-step prompts; "For the analyst" | New evidence per technology, the briefing feed, signal filters | No | Large |
| **3 · Technology hub** | One page per technology, from signals to Point of View; Assessments leaves the menu | Technology summary, Point of View extras | No | Medium |
| **4 · Operations board** | Process board, Problems, History; page budget in Crawl settings | Problems list, page budget setting | Yes: settings | Medium |

**Phase 0 has a deadline: before the next collection, and before anyone checks the 240 stored pages.**
- Renaming the stored value changes the signal list's fingerprint. Every page analysed before the rename then reads as "not yet checked", and checking it again costs a model call.
- Nothing on the deployed stack has been analysed against the current list yet. Its only collection, on 11 Sep, predates signals, so phase 0 costs nothing today.
- Phase 0 ends with one collection on the deployed stack. Its results give real numbers for deciding whether the 240 old pages are worth checking at all (§3.5).

## 2. Ground rules

- **Keep it simple.** Use the simplest thing that works, and reuse what plan 1 built.
- **The API returns data; the portal owns the words.** Messages the API already sends, such as the reasons for refusing a start, are reworded where they are.
- **One function per fact.** Every endpoint that shows the same fact gets it from the same function.
- **The agents' behaviour doesn't change.** Collecting, summarizing, organizing and scoring work as today. The only exceptions are phase 0 (the rename, and the organizer keeping existing ids) and the page budget setting (phase 4).
- **Tests:**
  - every new endpoint gets a test;
  - the 34 existing tests keep passing;
  - API tests use FastAPI's `TestClient(app)` without the lifespan, so nothing is seeded at start, together with the existing `db` fixture.

---

## 3. Phase 0 · Before the next collection

Three small changes that must be in place before the next collection, followed by that collection itself.

### 3.1 Never miss / Can ignore

**Goal:** one name from the seeding data to the screen.

**Behaviour stays the same:**
- A Can ignore rule sets a page aside only when the whole page is that kind of content and it carries no signal.
- Never miss always wins.

**Changes.** Make them in one commit. The skill text, its variables and the code must match; a mismatch makes summarizing fail with a KeyError.

| File | Change |
|---|---|
| `seeds/signals.json` (lines 189–231) | The 7 rows' `"mode": "always_ignore"` → `"can_ignore"` |
| `seeds/prompts.json`, article_summary | `Always ignore:\n{always_ignore}` → `Can ignore:\n{can_ignore}`; in the reply shape, "an Always ignore entry" → "a Can ignore entry"; `variables`: `always_ignore` → `can_ignore`; `version` 4 → 5 |
| `src/app/api/prompts.py:23` | EXPECTED_VARIABLES for article_summary uses `can_ignore` |
| `src/app/api/signals.py` | `mode: Literal["never_miss", "can_ignore"]` (:24); docstrings :2 and :180; "ignore rule" → "Can ignore rule" (:54) |
| `src/app/services/signals/snapshot.py:47–53` | The `prompt_lines` key and the mode filter become `can_ignore` |
| `src/agent/scout/tools/summarize.py` | `can_ignore=lines["can_ignore"]` (:103); `r["mode"] == "can_ignore"` (:146); docstrings :3 and :144 |
| `src/agent/resolver/resolver.py:147` | Comment |
| `tests/test_signals.py:14` | The fixture row's mode |

**Left alone, on purpose:**
- **The model's reply key `"ignore"`.**
- **The document field `ignored_by`.** It holds the rule's id, such as `single-job-ad`, not the mode.
- **Past runs' recorded `signal_list`.** It is read only while that run is live, and no screen shows it.

**New test, `tests/test_prompts.py`.** For every skill in the seeding data, three things must match:
- the placeholders in its text;
- its `variables`;
- `EXPECTED_VARIABLES[name]`.

This catches the KeyError class of mistakes before anything is deployed.

### 3.2 A renamed technology stays one technology

**The problem:**
- A technology's id is made from its name when it is first created.
- A rename keeps that id, which is right: assessments and Points of View are attached to it.
- But on every run, after every collection and every check, the organizer works each id out from the current name again (`resolver.py:237–244`).
- After a rename that changes the id-form of the name (letters and digits; capitals and punctuation don't count), it finds no record with that id. It creates a second technology with the same name.
- Merging the copy away doesn't last: the next organize run creates it again.

**Today, neither database is affected.** Checked on 3 Oct:
- the deployed stack has 1,151 technologies, and the dev copy 1,903;
- none has been renamed, and no name appears twice.

**The fix** sits in one place and is a few lines long. When the organizer writes the register, it first looks each name up among the existing technologies:
- **A name that already exists** keeps its technology's id.
- **A new name** gets a new id made from the name. If that id is already taken, by a technology that was renamed away from that name, a number is added.

**Cost and scope:**
- It reads every technology's name and id once per run. That is 1,151 records today, and still cheap at a hundred times that.
- Nothing else changes, and no data needs cleaning up.

**Tests**, in `tests/test_resolver.py` (new), with the organizer's model calls replaced by a fake as in the other tests:
- rename a technology and organize again: there is still one record, under the old id, with its aliases;
- a new name whose id is already taken gets a numbered id.

### 3.3 Every page that couldn't be analysed says why

**The problem:**
- When the summarizing step fails, the page is saved with a placeholder summary, or with the model's unusable reply, and with no technologies or signals.
- Nothing records that it failed, or why. The step does return the failure, but saving drops it (`store.py:181`).
- Pages where only some parts failed are marked "partly analysed", again without a reason.

**The change:** the page keeps the reason, and every place that reports a failure shows it.
- **`analysis_error` on the document,** with three fields:
  - **`reason`** is one of three: "model call failed" (it kept failing after the retries), "reply not in the expected format", or "some parts failed" (with how many).
  - **`detail`** is the error text, up to 200 characters, such as "Error code: 429 – rate limit reached", or the start of the unusable reply.
  - **`at`** is when it happened.
- **When it's set and cleared:**
  - A collection or a check again sets it when the step fails.
  - A check again that fails keeps the page's earlier analysis and records the reason.
  - Any later success removes it.
  - Stubs copy it, like the other analysis fields.
- **Where it shows:**
  - `GET /api/runs/{id}` gains `analysis_errors`: that collection's failures grouped by reason, with page counts and sources.
  - `/api/runs/{id}/documents` already returns every field, so each page's reason comes through as it is.
  - Phase 2 adds the reasons to the next-step prompts (§5.3, §5.5), and phase 4 lists them in Problems (§7.1).

**Today** neither database has failed or partly analysed pages, so there's nothing to backfill.

**Tests**, in `tests/test_signals.py`:
- a failed call and an unusable reply each store their reason;
- a partly analysed page stores "some parts failed";
- a failed check again keeps the earlier summary and records the reason;
- a later success removes it.

### 3.4 Deploy

1. **Check Changes on the deployed stack.** It must show 0; today it does. If it doesn't, write the wanted edits into the seeding data first, because the load replaces the live configuration.
2. **Rebuild** with `docker compose up -d --build`. The seeding data's fingerprint changed, so the API loads it at start.
3. **Verify:**
   - `GET /api/signals` lists 7 rows with `can_ignore`;
   - `GET /api/prompts` shows article_summary at version 5;
   - Changes shows 0;
   - `stale_pages` is still 240.

### 3.5 Then one collection on the deployed stack

**It uses the 6 sources that are switched on:** Amazon Science, Cisco Blogs, Hacker News, Techstars, arXiv and IETF.

**Expected cost:**
- The last collection with them, on 11 Sep, visited 240 pages.
- This one can visit up to 240 again.
- Each new or changed page uses at least one model call; unchanged pages cost nothing.
- Choosing links adds a few calls per source.

**What it shows, on real data:**
- Never miss and Can ignore at work: the signals found and the pages set aside;
- whether any page fails, and why;
- the organizer running with the fix in place;
- what a collection with these sources actually costs.

**Why it comes after phase 0, not before:** the rename would flag every page the collection analysed as "not yet checked". That would be up to 240 more pages to check again.

**Then decide on the 240 old pages:**
- They were collected on 11 Sep, before signals existed.
- They already feed technologies and assessments.
- Checking them only adds signals and set-asides to three-week-old news, at about 240 model calls.
- The new collection's results show whether that's worth paying for.

### 3.6 Demo

- **Signal list** shows "Never miss" and "Can ignore", and pages that match a Can ignore rule are set aside.
- **The collection's page** lists any pages that couldn't be analysed, each with its reason.
- **Technologies:** none appears twice after the collection.

---

## 4. Phase 1 · Look and words (backend part)

Most of this phase is portal work. The backend adds three things.

### 4.1 Cost estimates

Every button that uses the model shows its cost before you press it. Two of those estimates need the backend.

**Collection: `GET /api/runs/preview`** returns `{websites, data_sources, pages_per_source}`.
- `websites` and `data_sources` count the enabled sources a run will collect, those with `access` other than `none`. That is the same set the supervisor reads (`src/agent/supervisor/tools/sources.py`).
- `pages_per_source` is the run default: `MAX_PAGES_PER_SOURCE`, which is 40. It moves to Crawl settings in phase 4.
- The portal turns this into a sentence: "Up to 40 pages from each of 4 websites, plus the saved searches of 2 data sources. Each new or changed page uses at least one model call."

**Assessment: `GET /api/scoring/preview`** gains two fields, `calls` and `calls_max`. It also accepts a `technologies` parameter (comma-separated tech ids) as an alternative to `min_docs`.
- **Calls per technology:** 1 gate call, plus one call per configured measure for each fabric it qualifies for, plus 1 watch-metrics call (`engine.py:172–353`). The counts come from the scoring setup, not fixed numbers. With today's 12 measures and 4 enabled fabrics, that's 14 to 50 calls per technology.
- **`calls`** uses each technology's last recorded gate (`scoring_runs.gates`) when there is one. Without one, it assumes every enabled fabric. **`calls_max`** always assumes every enabled fabric.
- **Code:** in `src/agent/analyzer/estimate.py` (new, about 30 lines), so phases 2–4 reuse it. It replaces the portal's hard-coded "×26".

Two other buttons need no new endpoint:
- Check again: the count is already `stale_pages` in `/api/pipeline`.
- Points of View: 1 call each, and the counts are already in `/api/scoring/povs`.

**Every estimate is an approximate baseline.** Pages long enough to be split into parts, and calls that have to be retried, add to it. The portal always says "about".

### 4.2 Plain words in API messages

| Where | Today | New |
|---|---|---|
| `src/app/services/busy.py:15–22` | "A re-check of stored pages is in progress." | "A check of stored pages is in progress." |
| `src/app/services/signals/recheck.py:52–60` | "Nothing to re-check: every stored page was checked against the current list." | "Nothing to check again: every stored page was checked against the current list." |
| `src/agent/scout/tools/crawl.py:371–375` | "page budget reached: N links not visited" / "N links not visited" | "didn't finish: N links left" |

- Data-source notes ("N still to collect …", "too broad: narrow the search …") already say what happened, so they stay.
- Old runs keep the notes they recorded.

### 4.3 Pipeline: count errors too

`GET /api/pipeline` gains `collect.errors`: the number of sources in the latest collection whose row has an `error`, such as "not configured: set CONTACT_EMAIL in .env". Until phase 4 brings the full Problems list, the status pill shows `incomplete + errors` as its problem count.

### 4.4 Tests

- `tests/test_estimates.py`:
  - the assessment estimate with a recorded gate, without one, and for a list of ids;
  - the runs preview counts only enabled sources that a run collects.
- `tests/test_pipeline.py`: `collect.errors` and `collect.incomplete` from a stored run.

---

## 5. Phase 2 · Briefing (backend part)

### 5.1 New evidence, and when a technology is ready for its next step

**A page is new evidence for a technology when its latest version wasn't read by the technology's latest assessment.**
- **Linked:** `technologies_resolved` holds the technology's current name. Set-aside pages are never linked.
- **Latest version:** the newest stored version of the page. A visit that found the page unchanged (a stub) isn't a new version; it points to the version it repeats.
- **Read:** the assessment records the page versions it read.

**Why page versions, not collections or dates:**
- **Unchanged revisits.** The dossier uses each page's newest visit, which is often an unchanged revisit. If we recorded that visit's collection, the page's original version would look unread. After any repeat collection, almost every page would wrongly count as new.
- **Partial reads.** Recording a collection doesn't prove every page from it was read.
- **Late linking.** Pages are linked to technologies only at the end of a collection. A date boundary would miss pages from a collection that overlapped an assessment.

**What the dossier builder records** (`build_dossier` in `engine.py`). Each assessment stores:
- **`dossier_pages`:** the ids of the page versions it read. An unchanged revisit is recorded as the original version it repeats (`ref_doc_id`).
- **`dossier_from`:** set only when the size guard dropped the oldest pages from a very large dossier. The builder orders pages by their newest visit, unchanged revisits included. So `dossier_from` holds the newest-visit time of the oldest page it read.
  - A page whose newest visit is older than that doesn't count as new, because reassessing would drop it again.
  - The cutoff only ever compares visit times; whether a page was read is always decided by version ids. If an unchanged revisit lifts a dropped page back above the cutoff, the page counts as new, since its version wasn't read.
- **`doc_count`** ("read N pages") now counts the pages actually included, after the size guard. Today it counts them before.

`evidence_runs` stays as it is, for the collection pages' "Used in" links. Old assessments without `dossier_pages` fall back to a date: a page is new if its latest version was collected after the assessment was created.

**One readiness rule, used everywhere.** The technology page, the waiting count, "Write the waiting ones", "Rewrite all" and the analyst box all read the same rule.
- **A technology's latest assessment** is the newest run in which every fabric its gate chose was scored, whatever happened to that run afterwards.
- **A run that stopped partway** leaves the technology's previous assessment in place. The technology shows "Assessment stopped partway", with the existing Resume action.
- **Ready for a Point of View** means no Point of View has been written from the run of its latest assessment. An older Point of View doesn't count.
- **"Rewrite all"** covers every technology with a latest assessment, each written from that assessment.
- **This replaces today's batch rule** (`scoring_runs.py:99–136`). That rule counts any Point of View as cover, and looks only at the last 10 completed runs.

**The states that follow** (the first match wins):

| State | When | Main button on the technology page |
|---|---|---|
| `off` | The technology is switched off, so runs don't assess it | none; the page says "Assessment switched off" |
| `assessing` | A run is assessing it right now | none; progress shows |
| `stopped_partway` | Its newest run stopped before all its fabrics were scored | Resume (that run) |
| `not_assessed` | It has no latest assessment | Assess now |
| `new_evidence` | It has new pages since its latest assessment | Assess now |
| `no_pov` | Ready for a Point of View | Write Point of View |
| `current` | Otherwise | Open Point of View |

**Code: `src/app/services/evidence.py` (new):**
- `latest_assessment(tech_id)` returns two things:
  - the latest assessment: run, created time, `dossier_pages`, `dossier_from` and per-fabric placements;
  - any newer run that is still going or stopped partway.
- `new_pages(name, assessment)` returns the count, plus a query helper for listing the pages. It does two checks:
  - each page's newest non-stub version against `dossier_pages`;
  - each page's newest visit against `dossier_from`.
- `state(tech)`: the technology's one state, from the table above.
- **Three waiting lists, each read off the states,** so no technology is ever in two of them:
  - `stopped_runs()`: the runs that stopped partway, each with the `stopped_partway` technologies it left;
  - `with_new_evidence()`: `[{tech_id, name, new_pages, assessed_at}]` for the switched-on technologies in `new_evidence`;
  - `pov_targets()`: the technologies in `no_pov`, each with the run to write from. `_pov_state()` and compose-all use it.

Because each technology has a single state, the waiting lists follow the same priority as the technology page: resume, then assess, then write. For example, a technology with new evidence whose latest assessment has no Point of View waits to be assessed, not written.

Only tens of technologies are assessed, so one query per technology is cheap. It uses the existing `technologies_resolved` index.

### 5.2 `GET /api/briefing?days=7`

One call gives the Briefing everything it needs (contract in §9.3).
- **Window:** the last `days` days (1–90), by the collection time (`scraped_at`) of new or changed pages.
- **Freshness:** the latest collection's finish time, number of sources, number of new pages, and the problem count the status pill shows.
- **Groups:** the technologies with new pages in the window.
  - **Each group has:**
    - counts of new pages, signals on the list, and signals not on the list;
    - the technology's state and assessed date;
    - up to 5 signal items, on-the-list first and newest first;
    - the number of new pages that carry no signal.
  - **Order:** by signals on the list, then signals not on the list, then new pages, then name.
  - **Limit:** the first 10 groups come in full; the rest come as a short list of `{tech_id, name, new_pages, signals}`.
- **No technology:** signal items on new pages that aren't linked to any technology.
- **New Points of View:** those written in the window, with headline, technology and date.
- **Signal items** have the same shape as in `/api/signals/found` and come from the same query function, refactored out of that endpoint.

### 5.3 Pipeline additions

- **`assess.techs_with_new_evidence`** is the count from `with_new_evidence()`. It replaces the timing-only `assess.new_evidence` flag. The portal's two readers of the flag switch over in the same phase.
- **`for_analyst`** lists what is waiting for the analyst, in process order. At most three items show, taken in this order:
  - `{kind: "check", count, calls}`, from `stale_pages`;
  - `{kind: "resume", scoring_run_id, count, calls}`, from `stopped_runs()`: the technologies a stopped run left;
  - `{kind: "assess", count, calls, calls_max, tech_ids}`, from `with_new_evidence()`;
  - `{kind: "write", count, calls}`, from `pov_targets()`. `pov.pending` uses the same list.

  - **One list per item.** Each item comes from one of §5.1's waiting lists, so a technology appears in at most one item.
  - **Only non-empty items** appear.
  - **The portal** words the items and decides whether a running job blocks them.
- **Finished-job details:**
  - `signals.recheck.id` and `pov.job.id`;
  - `assess.skipped` and `pov.job.failed`, both counts;
  - `collect.analysis_errors`: the latest collection's failures grouped by reason (§3.3).

  With these, the portal can tell when a job has just finished and say how it went, including the reason for any page that couldn't be analysed.

### 5.4 Signals endpoints

- **`/api/signals/found`** gains:
  - `doc_id`, which returns one page's signals; the side panel uses this for its own address;
  - `facets=true`, which returns counts by signal and by source within the same `since` window.
- **`/api/signals/other`** gains `since` and `skip`, and returns `total`.
- **`/api/signals/set-aside`** gains `since`.

### 5.5 Re-check job counters

While it runs, `recheck._run` counts four things:
- `found`: signals on the list;
- `other`: signals not on the list;
- `set_aside`: pages;
- `failed_reasons`: pages that couldn't be analysed, by reason (§3.3).

The prompt after a check can then say "40 signals found, 32 set aside. 2 couldn't be analysed: model call failed (rate limit reached)".

### 5.6 Index

Add `documents (is_stub, scraped_at)` in `bootstrap.py` for the window queries.

### 5.7 Tests

- **`tests/test_evidence.py`:**
  - **the dossier builder** records the page versions it read, with unchanged revisits resolved to the original; it sets `dossier_from` only when the size guard trips; and `doc_count` counts after the guard;
  - **an unchanged revisit,** before or after the assessment, doesn't make a page new;
  - **a changed page** is new;
  - **pages the size guard dropped** aren't new, until an unchanged revisit lifts one back above the cutoff, which makes it new;
  - **set-aside pages** never count;
  - **the date fallback** for old assessments;
  - **the readiness rule:**
    - a technology reassessed after its Point of View is ready for a new one;
    - a run that stopped partway keeps the previous assessment and gives `stopped_partway`;
    - the technology page, the waiting count and compose-all all agree;
    - a technology with new evidence and no Point of View from its latest assessment is only on the assess list;
    - a technology stopped partway is only on the resume list;
  - **each state;**
  - **`with_new_evidence`** skips switched-off and deleted technologies.
- **`tests/test_briefing.py`:** grouping, order, the 5-item cap, pages without signals, the no-technology group, and the window's edges.
- **`tests/test_signals_api.py`:** `doc_id`, facets, and `since` on Other and Set aside.
- **`tests/test_pipeline.py`:** the `for_analyst` items and their counts.

---

## 6. Phase 3 · Technology hub (backend part)

### 6.1 `GET /api/technologies/{tech_id}/summary`

Built from §5.1's functions (contract in §9.4), it gives the hub's header and sections everything they need:
- **the technology, and its state;**
- **the latest assessment:** run, date, pages read, and each fabric's priority, horizon and TORA scores, plus its evidence runs;
- **any newer run** that is still going or stopped partway, so the page can offer Resume;
- **the newest Point of View**, and whether it was written from the latest assessment;
- **new pages:**
  - counted since the assessment and since the Point of View;
  - the 5 newest new pages, for "What's happening";
- **cost estimates:** assessing comes from the estimate function; writing is 1 call.

`GET /api/technologies/{tech_id}/documents` also marks each page `new` with the same rule, so the evidence list doesn't have to work it out.

### 6.2 Points of View list

`GET /api/scoring/povs` gives each written Point of View two new fields:
- **`new_since_written`**, from the rule in §5.1. It is counted against the assessments the Point of View was written from: its `assessment_ids`, and through them the page versions they read (`dossier_pages`).
- **`placements`:** `[{fabric_id, fabric, priority, horizon}]` from those same assessments, for the library cards.

The `uncomposed` list comes from `pov_targets()` (§5.1). A technology reassessed after its Point of View is therefore listed again, and "Write the waiting ones" includes it.

### 6.3 Tests

`tests/test_tech_summary.py` covers:
- each state;
- `stopped_partway` returns the run to resume;
- a Point of View from an older run gives `no_pov`, and the older Point of View is still returned;
- new pages since the Point of View;
- the estimates.

---

## 7. Phase 4 · Operations board (backend part)

### 7.1 `GET /api/problems`

It is worked out on each request; nothing is stored. It returns data, and the portal words it:

| Kind | Where it comes from | Example in the portal | Fix the portal offers |
|---|---|---|---|
| `didnt_finish` | Website rows marked `incomplete` in the latest collection | "IETF didn't finish: 1,081 links left." | Crawl settings: raise the page budget, or add skip patterns |
| `too_broad` | "too broad" notes on data sources in the latest collection | "OpenAlex: a saved search is too broad." | Open the source to narrow it |
| `not_configured` | Enabled data sources whose adapter is missing keys, from `describe()` | "SEC filings isn't configured." | How: "Add CONTACT_EMAIL to .env, then restart tech-atlas." |
| `source_error` | Any other `error` on a source row in the latest collection | "Inc42 failed: …" | Open the collection |
| `failed_pages` | Pages from the latest collection or check again that carry an `analysis_error` (§3.3), grouped by reason | "4 pages couldn't be analysed: 3 × model call failed (rate limit reached), 1 × reply not in the expected format." Each page is listed with its reason | Check again; they are already in its queue |
| `job_failed` | The latest collection, check, assessment run or Point of View job, if it failed, stopped with an error, or was interrupted | "The assessment run stopped: …" | Resume, Check again, Write again, or Open |

A data source showing "N still to collect" is not a problem: the next collection carries on where this one stopped.

`/api/pipeline` gains `problems`, the count from the same function. It replaces phase 1's `incomplete + errors`.

### 7.2 Page budget in Crawl settings

- **The setting.** In `seeds/settings.json`, crawl gains `pages_per_source: 40`. Setup → Crawl settings edits it (1–500), and Changes lists it like the other crawl settings.
- **Where it's read.** `collect.py:32` and `agent.py:29` read it from the run's recorded crawl settings instead of `MAX_PAGES_PER_SOURCE`. A run's own `max_pages_per_source` still wins.
- **One place for the number.** `MAX_PAGES_PER_SOURCE` is removed from settings.py, .env.example and the README.
- **`/api/runs/preview`** reads it.

### 7.3 Tests

- **`tests/test_problems.py`:** each kind, from stored runs, sources and jobs; "still to collect" doesn't count as a problem; failed pages come grouped by reason.
- **`tests/test_crawl_rules.py`:** the page budget comes from settings, and a run's override wins.

**Deploy:** settings.json changes, so the seeding data loads at start. Check Changes first, as in phase 0.

---

## 8. Order of work inside each phase

For every phase:
1. Backend changes and their tests.
2. The full test suite.
3. A live check on the dev copy (`tech_atlas_dev`, API on 8100).
4. The portal work, from the portal plan.
5. Your demo on the dev servers.
6. Docker rebuild and a check.
7. Your sign-off.

---

## 9. API contract (shared by both apps)

New and changed shapes only. Everything else stays as plan 1 left it.

### 9.1 Phase 0
- `mode` is `"never_miss"` or `"can_ignore"` in `GET /api/signals` rows and in `POST` / `PUT /api/signals` bodies.
- A document that couldn't be analysed carries `analysis_error`. Every endpoint that returns whole documents passes it through, including `/api/runs/{id}/documents`.
- `GET /api/runs/{id}` gains `analysis_errors`, that collection's failures grouped by reason.

```
document:          "analysis_error": {"reason": "model call failed",
                                      "detail": "Error code: 429 – rate limit reached",
                                      "at": "2026-10-04T09:12:00Z"}

GET /api/runs/{id}  "analysis_errors": [{"reason": "model call failed",
                                         "detail": "Error code: 429 – rate limit reached",
                                         "pages": 3, "sources": ["ietf", "arxiv"]}]
```
`reason` is one of "model call failed", "reply not in the expected format" or "some parts failed (2 of 5)".

### 9.2 Phase 1
```
GET /api/runs/preview
{"websites": 4, "data_sources": 2, "pages_per_source": 40}

GET /api/scoring/preview?min_docs=3          (or ?technologies=id1,id2)
{"technologies": 6, "calls": 168, "calls_max": 300}

GET /api/pipeline                            (one field added)
"collect": {…, "incomplete": 1, "errors": 2}
```

### 9.3 Phase 2
```
GET /api/briefing?days=7
{
  "window":    {"days": 7, "from": "2026-09-26T18:00:00Z", "to": "2026-10-03T18:00:00Z"},
  "freshness": {"run_id": "591da7fbf3c9", "finished_at": "…", "sources": 6,
                "new_pages": 30, "problems": 3},
  "groups": [{
    "tech_id": "open-weight-language-models", "name": "open-weight language models",
    "new_pages": 3, "signals": 2, "other_signals": 0, "pages_without_signal": 1,
    "state": "new_evidence", "assessed_at": "2026-09-07T…",
    "items": [ …up to 5 signal items, shaped as in /api/signals/found… ]
  }],
  "more_groups":   [{"tech_id": "…", "name": "…", "new_pages": 2, "signals": 1}],
  "no_technology": {"signals": 1, "items": [ … ]},
  "new_povs": [{"id": "run:tech", "scoring_run_id": "…", "tech_id": "…",
                "technology": "…", "headline": "…", "composed_at": "…"}]
}

GET /api/pipeline                            (added; assess.new_evidence removed)
"assess":  {…, "techs_with_new_evidence": 6, "skipped": 0}
"collect": {…, "analysis_errors": [{"reason": "model call failed", "detail": "…",
                                    "pages": 1, "sources": ["ietf"]}]}
"signals": {…, "recheck": {…, "id": "…", "found": 40, "other": 9, "set_aside": 32,
                           "failed_reasons": {"model call failed": 2}}}
"pov":     {…, "pending": 6, "job": {…, "id": "…", "failed": 0}}     (pending follows the readiness rule, §5.1)
"for_analyst": [
  {"kind": "check",  "count": 216, "calls": 216},
  {"kind": "resume", "scoring_run_id": "…", "count": 3, "calls": 78},
  {"kind": "assess", "count": 6, "calls": 168, "calls_max": 300, "tech_ids": ["…"]},
  {"kind": "write",  "count": 6, "calls": 6}
]

GET /api/signals/found?…&doc_id=<id>&facets=true
{…, "facets": {"signal": {"<signal_id>": 12, "other": 3}, "source": {"<source_id>": 9}}}

GET /api/signals/other?since=…&skip=…        {…, "total": 14}
GET /api/signals/set-aside?since=…

assessments (stored)                         + "dossier_pages": ["<doc_id>", …]
                                             + "dossier_from": "…"   (only when the size guard trips)
                                             "doc_count" now counts the pages actually read
GET /api/scoring/runs/{run_id}               leaves dossier_pages out of its assessment rows (they can be long)
```

### 9.4 Phase 3
```
GET /api/technologies/{tech_id}/summary
{
  "technology": {"id": "…", "name": "…", "aliases": [], "enabled": true,
                 "page_count": 12, "source_count": 4},
  "state": "new_evidence",
  "assessment": {
    "scoring_run_id": "…", "run_status": "completed", "assessed_at": "…",
    "pages_read": 9, "evidence_runs": ["…"],
    "fabrics": [{"assessment_id": "…", "fabric_id": "cloud", "fabric": "Cloud",
                 "priority": "P2", "horizon": "H1",
                 "tora": {"market_potential": {"score": 7.0, "partial": false},
                          "strategic_fit": {…}, "adoption_readiness": {…}}}]
  },
  "unfinished": {"scoring_run_id": "…", "status": "terminated"},
  "pov": {"id": "…", "scoring_run_id": "…", "composed_at": "…", "version": 2,
          "headline": "…", "from_latest_assessment": true},
  "new_pages": {"since_assessment": 3, "since_pov": 3,
                "recent": [{"doc_id": "…", "title": "…", "url": "…",
                            "source_id": "…", "scraped_at": "…"}]},
  "estimate": {"assess_calls": 26, "assess_calls_max": 50, "write_calls": 1}
}
```
- `state` is one of `off`, `assessing`, `stopped_partway`, `not_assessed`, `new_evidence`, `no_pov` or `current` (§5.1).
- `assessment`, `unfinished` and `pov` are `null` when absent. `unfinished` is a newer run that is still going or stopped partway.

```
GET /api/scoring/povs                        (each written Point of View gains)
{"new_since_written": 3,
 "placements": [{"fabric_id": "cloud", "fabric": "Cloud", "priority": "P2", "horizon": "H1"}]}
                                             "uncomposed" now comes from the readiness rule (§5.1)

GET /api/technologies/{tech_id}/documents    each document gains "new": true | false   (rule in §5.1)
```

### 9.5 Phase 4
```
GET /api/problems
{"count": 4, "problems": [
  {"kind": "didnt_finish",   "source_id": "ietf", "source_name": "IETF", "run_id": "…",
                             "note": "didn't finish: 1,081 links left"},
  {"kind": "not_configured", "source_id": "sec-edgar", "source_name": "SEC EDGAR filings",
                             "keys": ["CONTACT_EMAIL"]},
  {"kind": "failed_pages",   "count": 4,
                             "reasons": [{"reason": "model call failed", "detail": "Error code: 429 – …", "pages": 3},
                                         {"reason": "reply not in the expected format", "detail": "…", "pages": 1}],
                             "pages": [{"doc_id": "…", "title": "…", "url": "…", "source_id": "ietf",
                                        "reason": "model call failed", "detail": "…"}]},
  {"kind": "job_failed",     "job": "assessment", "id": "…", "status": "terminated",
                             "error": "interrupted — service shutdown"}
]}

GET /api/pipeline                            "problems": 4   (replaces incomplete + errors in the pill)
GET / PUT /api/settings/crawl                + "pages_per_source": 40   (1–500)
```

---

## 10. Testing

- **Today's suite:** `pytest`, 34 tests, against a live MongoDB test database (`tech_atlas_test`).
- **Added by phase:**
  - Phase 0: `test_prompts.py` and `test_resolver.py`, plus failure reasons in `test_signals.py`.
  - Phase 1: `test_estimates.py` and `test_pipeline.py`.
  - Phase 2: `test_evidence.py`, `test_briefing.py` and `test_signals_api.py`.
  - Phase 3: `test_tech_summary.py`.
  - Phase 4: `test_problems.py`.
  - Existing files are extended where noted.
- **After each phase:**
  1. The full suite.
  2. The new endpoints checked by hand against the dev copy, using real data: the pilot runs 591da7fbf3c9 and 5e813b4d0e8a, and assessment 8891e851079b.
  3. Docker.

## 11. Deployment

- **Each phase runs first on the dev servers** (`./start.sh`), then on Docker (`docker compose up -d --build`).
- **Phases 0 and 4 change the seeding data**, so the API reloads it at start. Check Changes first and write any edits you want to keep. The other phases leave the seeding data alone.
- **Phase 0 goes first,** before the next collection and before the 240 deployed pages are checked (§1). It ends with one collection on the deployed stack (§3.5).

---

## 12. Found along the way

Two findings from this reading are now part of phase 0:
- renamed technologies turning into duplicates (§3.2);
- pages that couldn't be analysed leaving no reason (§3.3).

Still outside the plan:

1. **A Point of View written from a newer assessment run starts again at version 1, and the older one stays.** That's because its id is run plus technology. The hub always shows the newest one; this note is so the version numbers don't surprise anyone.
2. **A misleading comment in `.env.example`.** It suggests `MIN_DOCS_PER_TECH` filters what gets scored. In fact it's the organizer's floor for how often a name must appear (`resolver.py:170–171`).

## 13. Where this plan refines UI-suggestions.md

- **Setup gets its side menu in phase 1, not phase 4.** A route group gives Setup a shared menu without changing any address. That is less work than building a temporary dropdown and then removing it.
- **New evidence is defined by the page versions an assessment actually read (§5.1).** That is what the doc's "new or changed since the latest assessment" means in practice.
- **Azure also marks work in progress,** such as the status pill's dot while something runs.
- **The page budget becomes one Crawl setting, not a per-source field.** In the operator journey, the fix opens Crawl settings.
- **Next-step prompts appear only for work that finishes while the portal is open.** Anything that finished while you were away shows under "For the analyst".

## 14. Sign-off

- **Approve the plan as a whole, or phase by phase.** Phase 0 can start straight away.
- **For the client's brand team (doesn't block anything):**
  - the Gotham licence; until then, Montserrat;
  - the logo files; until then, the wordmark;
  - the Interaction fabric's colour; until then, purple.

---

## 15. Build notes

### Phase 0, built 3 Oct

- **Built as planned:**
  - the Can ignore rename (article_summary is now version 5);
  - the organizer keeping ids;
  - `analysis_error` on pages;
  - `analysis_errors` on `GET /api/runs/{id}`;
  - `tests/test_prompts.py` and `tests/test_resolver.py`.
- **Tests:** 40 pass, the 34 existing and 6 new. Both rename tests fail against the old organizer code and pass with the fix, so the duplicate bug is reproduced and fixed.
- **Small deviations, each needed to make the change complete:**
  - **The partial-failure reason is always "some parts failed",** and the counts go in `detail`, for example "1 of 3 parts: model call failed: boom". This keeps grouping by reason clean: "(2 of 5)" and "(1 of 3)" would otherwise be separate groups.
  - **A fourth reason, "unexpected error",** covers an exception that isn't the model's during a check again. The page still says why.
  - **`GET /api/signals/found` items gain `technology_ids`,** aligned with `technologies`, and the Signals page links its technology chips by id. A renamed technology keeps its original id, so ids can no longer be derived from names; the old name-based links would have broken after a rename.
- **Deployed:**
  - **Dev copy:** 26 Never miss and 7 Can ignore rows, article_summary version 5, Changes 0.
  - **Docker:** the same. The 240 pages are still waiting to be checked, so the rename cost nothing.
- **The phase 0 collection on Docker** (run `20628e1f592e`, 3 Oct, the 6 switched-on websites):
  - **Duration and pages:** 37 minutes. 216 pages visited; 183 new or changed, and 33 unchanged revisits that cost nothing.
  - **Signals:** 135 on the list, across 18 never-miss types (Partnership 35, Research breakthrough 24, Product launch 21, Standard milestone 14, and so on), and 77 not on the list. IETF Internet-Drafts are the most common of those.
  - **Set aside:** 12 pages, by 4 Can ignore rules: Marketing echo 4, Event promotion 3, Opinion without news 3, Single job ad 2.
  - **Failures:** none. No page failed or was only partly analysed.
  - **Long pages:** 9 were split, into 27 parts.
  - **Didn't finish:** 5 of 6 sources hit the 40-page budget, with 120–1,712 links left.
  - **Technologies:** organizing used 2 model calls and took the register from 1,151 to 1,853, with no duplicate names.
  - **Cost:** about 210 summary calls (174 pages at one call each; 9 split pages at 27 part calls plus 9 merges). On top of that come choosing links and the agents' own steps, roughly 20–40 calls, which today's run records don't count; and 2 for organizing.
  - **Still to check:** 240 pages, the 11 Sep ones only; every new page was checked against the current list.

### Phases 1–4 backend, built 4 Oct

The user signed off phase 0 on 3 Oct and asked for phases 1–4 to be built in one go, stopping only for a design or implementation change.

- **Built as planned:**
  - **Phase 1:** `GET /api/runs/preview`; `calls` and `calls_max` on `GET /api/scoring/preview`, which also takes `technologies`; `agent/analyzer/estimate.py`; the plain words in API messages; `collect.errors` in the pipeline.
  - **Phase 2:** `services/evidence.py` (states, waiting lists, new pages); assessments store `dossier_pages`, `dossier_from` only when the size guard trips, and `doc_count` after the guard; `GET /api/briefing`; the pipeline additions (`techs_with_new_evidence`, `skipped`, `for_analyst`, job ids, check counters, `collect.analysis_errors`); `doc_id`, `facets`, `since` and `skip` on the Signals endpoints; the check-again counters; the `(is_stub, scraped_at)` index.
  - **Phase 3:** `GET /api/technologies/{id}/summary`; `new` on a technology's pages; `new_since_written` and `placements` on written Points of View. Their waiting list now follows the readiness rule.
  - **Phase 4:** `GET /api/problems` and `problems` in the pipeline, also used for the Briefing's freshness line; `pages_per_source` in Crawl settings (seeds, the editor's model, the run's recorded settings; a run's own override still wins). `MAX_PAGES_PER_SOURCE` is gone from settings.py and .env.example; the README never mentioned it.
- **Tests:** 70 pass; 30 are new across `test_estimates`, `test_pipeline`, `test_evidence`, `test_briefing`, `test_signals_api`, `test_tech_summary`, `test_problems`, `test_crawl_rules` and `test_signals`. Shared builders are in `tests/factories.py`.
- **Small additions, each needed by a screen:**
  - **Signal items carry `n`,** the hit's place on its page, so the side panel's address `?signal=<doc_id>:<n>` comes straight from the item.
  - **The resume item in `for_analyst` carries `started_at`,** for "The assessment run of 3 Oct stopped …".
  - **`GET /api/scoring/povs` returns `assessed`:** the number of technologies with a latest assessment, which is what "Rewrite all" covers and costs.
  - **Crawl settings fill any missing setting from the seeding data.** So the page budget has one source, `seeds/settings.json`, even before a load.
- **Choices inside the rules:**
  - **The latest assessment can span several fabric rows.** Each row's dossier is built when that fabric is scored, so a resumed run can have rows that read different pages. New evidence uses the union of the pages they read, the latest size-guard cutoff, and the earliest row's time for the date fallback.
  - **Problems:**
    - `failed_pages` covers pages from the latest collection, plus pages whose failure is newer than the latest check's start.
    - `job_failed` leaves out jobs a person stopped ("terminated by user"). An assessment run stopped by hand still shows as "stopped partway" with Resume.
    - A source error that `not_configured` already reports isn't repeated.
- **Checked on real data, read-only:**
  - **Docker:**
    - 60 assessed technologies: 25 have new evidence since 11 Sep (agentic AI 10 pages, large language models 8, …), and 35 are waiting for a Point of View, since none was ever written there;
    - Problems: the 6 sources that didn't finish;
    - working out every state takes 0.05 s.
  - **Dev copy:** the pipeline answers in about 60 ms.
- **Found along the way:**
  - **A listing page can crowd the Briefing.** The dev copy holds one arXiv listing page (`arxiv.org/list/cs/new`, 14 parts) with 87 signals and 246 technologies. Each of those technologies inherits all 87 signals, so they top the Briefing's order. The deployed stack's pages carry at most 7 signals, so nothing changes now. If listing pages come back, the fix belongs in collecting (follow their links rather than store them), not in the Briefing.
  - **Old collection notes keep their old wording** ("page budget reached: …"). The portal reads the number of links left from the note.
- **Added after the portal check, each a small gap the screens exposed:**
  - **Signals endpoints:**
    - `on_list=true` on `/api/signals/found`, so "On the list" fetches only those signals, with source counts to match;
    - `tech` and `run_id` on `/api/signals/other`, so its filters behave like the other tabs.
  - **"Didn't finish" counts websites only, everywhere.** One function, `didnt_finish()` in `services/problems.py`, serves the pipeline, `GET /api/runs` (rows gain `incomplete`) and Problems. A data source with results still to collect isn't counted: the next collection carries on.
  - **The pipeline's `collect` carries `error`,** so the status pill turns red only when a collection really failed.
  - **The summary's `evidence_runs` is null when never recorded,** so the page says "not recorded" rather than "none".
- **Tests:** 72 pass.
- **Deployed to Docker on 4 Oct:**
  - Changes was 0 first.
  - The seeding data reloaded with `pages_per_source: 40`; Changes is 0 again.
  - The deployed numbers:
    - 6 websites to collect;
    - 25 technologies with new pages (about 890 model calls to assess them);
    - 35 waiting for a Point of View;
    - 240 pages not yet checked;
    - 6 problems, all "didn't finish".
  - Every portal page loads in a headless browser with no errors.
