# Implementation plan 3: findings first, backend (tech-atlas)

**Date:** 2026-10-04 · **Plan:** 3, filed in the 2026-10-03 folder beside GPT's review · **Status:** built on 4 Oct, after you said "complete the implementation, I want to see the end product". All three phases are built, tested and deployed to Docker. The build notes are in §8.

**Portal plan:** [tech-lens implementation-plan.md](../../../../tech-lens/docs/2026-10-03/3/implementation-plan.md), with the screens and words.

**Mockup:** https://claude.ai/artifact/VfGNP5Dr9YvvCu1WRpBtGD shows the Briefing as phase A would build it, on the real Oct 3 findings. It is private to you.

**Builds on:**
- [plan 2](../2/implementation-plan.md), which is built and deployed;
- GPT's [UX review](../../../../tech-lens/docs/2026-10-03/3/ux-review-and-recommendations.md).

From the review, this plan:
- takes its diagnosis and about two-thirds of its fixes;
- leaves out its extra machinery: a collection picker, five tabs, three sort orders and new results endpoints;
- adds what it missed (§1).

This file is the master. It holds:
- the phases;
- the backend work;
- the API contract (§6);
- tests and deployment.

The screens are in the portal plan.

---

## 1. Why

You still find the portal confusing after plan 2. Measured on the deployed data from the Oct 3 collection:

| What you see | Why |
|---|---|
| The Briefing is about 9 screens long, yet shows only 31 of the week's 212 findings. 11 of those appear 2 to 4 times, so you scroll past 53 rows. | It groups findings by technology. It shows 5 per group and only the top 10 groups. |
| Findings appear under unrelated technologies, with tags like "+19 more". For example, the Cisco–NVIDIA agent story sits under post-quantum cryptography. | Technologies are tagged per page: usually 6, up to 30. Every finding inherits all of its page's tags. One week touched 827 technologies; 635 of them came from a single page. |
| Half of "What's new" is old. | 93 of the 212 findings come from pages published more than 30 days before they were collected. Rows show only the collection date, though 421 of the 423 stored pages have a publication date. |
| Reader pages carry operator work. | **Batch buttons:** Check 240, Assess 890, Write 35.<br>**Also:** Organize technologies, inventory counts, and "6 problems" that are six websites reaching their page limit. |
| Two pages list findings. | The Briefing and Signals do the same job with different rules. |
| The text reads like a database. | **Headlines:** start "The document reports that…".<br>**Findings:** a paper's funding acknowledgement shows up as a "Government programme" finding.<br>**Names:** stored as lowercase keys. |

**The goal:**
- one screen tells a reader what was found, what matters most and what waits for them;
- every finding is reachable;
- operator work lives in Operations and Setup.

## 2. Two decisions for you

Both reverse decisions from plan 2:

1. **The Briefing stops grouping by technology.** It becomes one ranked list of every finding (phase A). Technology groups can't work while every finding carries all of its page's tags.
2. **The Signals page folds into the Briefing.**
   - Its suggestions ("Not on the list") and its set-aside pages move to Setup → Signal list, where you act on them.
   - The menu becomes Briefing · Technologies · Points of View │ Operations · Setup.

Everything else keeps plan 2's decisions:
- Never miss / Can ignore;
- Set aside;
- one portal and the Tata look;
- failures always say why;
- the technology register as it is.

## 3. Phases

| Phase | What you'll see | Backend | Seed files reload on deploy | Model calls |
|---|---|---|---|---|
| A | **Briefing:** one complete, ranked list.<br>**Also:** Signals folds into it; you can reorder signal types. | a signal order; one shared order for findings; a reshaped Briefing summary | yes (`order`) | none |
| B | **Technology page:** conclusions first.<br>**Technologies:** a filter by state.<br>**Also:** page limits are no longer counted as problems; the full menu on laptops. | a state filter on technologies; problems separated from coverage | no | none |
| C | **From the next collection:** short headlines, each finding's own technologies, natural-case names. | summary prompt v6; technologies per finding; technology labels | yes (prompts) | no extra calls per page; about 4 once for labels |

Each phase ends with a demo on the dev copy and your sign-off. It is deployed to Docker after that.

### Phase A: the Briefing becomes one complete list

**A1. Signal types get an order.**

- Every `signals` row gets `order`, an integer.
- `seeds/signals.json` gets `"order": 1…33`, following today's file order. That order already runs from money, to public bodies, research, standards and the market, to people.
- `GET /api/signals` sorts by mode, then `order`. `POST /api/signals` adds a new row at the end.
- **New: `PUT /api/signals/order`** with `{"ids": [...]}`, the never-miss ids in their new order.
  - It sets each row's `order` to its position.
  - It stamps `updated_at` only on rows that moved.
  - It returns 422 unless the ids are exactly the never-miss rows.
- `order` stays out of `signals_hash()`, which keeps hashing id, name, look-for text and mode. Reordering marks no page as "not yet checked" and costs no model calls.
- Changes lists a move as an edit to `order`. "Update seeding data" writes it like any other edit.

**A2. One order for findings.** The Briefing, its filters and the technology page all use it. `hits()` gains `sort="briefing"`, which sorts by these keys in turn:

1. **Recent before older.**
   - A finding is older when its page was published more than 30 days before it was collected. That compares `published_date` with `scraped_at`; the limit is `OLDER_AFTER_DAYS = 30`.
   - A page without a publication date counts as recent.
2. **The signal list's order.**
   - A finding whose row was deleted or switched off comes after the listed rows.
   - Other comes last.
3. **Newest publication date first.** The collection date stands in when there's none.
4. **Tie-breakers:** `scraped_at`, `doc_id`, then `n`, so the order is stable.

The aggregation computes these keys before `skip` and `limit`, using `$dateFromString`, `$dateDiff` and `$indexOfArray`. So paging walks one fixed order across all findings. `/signals/found` still sorts newest-collected first by default, so other callers don't change.

**A3. Findings carry their dates.**
- Hit rows add `published_date` and `older`.
- Technology chips come in a useful order: the filtered technology first, then the page's technologies with the most pages.

**A4. A fixed window.** `/signals/found` gains `until`, an upper bound on collection time. A loaded Briefing then pages through one fixed window, even while a collection runs.

**A5. The Briefing summary is reshaped.** `GET /api/briefing` returns what the page needs around the list; the list itself comes from `/signals/found?sort=briefing`.

- **Scope:** `days` (7, 30, 90 or `all`), or `run_id` for one collection, by membership. Both together returns 422; an unknown run returns 404.
- **Filters:** `tech` and `source`, the same as the list's, so the counts and the list always agree.
- **Returns:**
  - `scope`: the window's `from` and `to`, or the collection's dates, status and error;
  - `counts`: findings, new or changed pages, and older findings;
  - `types`: one row per signal type found (`signal_id`, `name`, `count`), in the list's order. The signal list's rows come first, then deleted or switched-off rows, then Other;
  - `freshness`, as today but without `problems`;
  - `new_povs`, as today.
- The technology groups go: `groups`, `more_groups`, `no_technology`, `FULL_GROUPS` and `ITEMS`.

**A6. Nothing else changes in the backend.**
- `/signals/other` and `/signals/set-aside` keep supplying their lists, which now live on Setup → Signal list.
- `pipeline.for_analyst` stays as it is.

**Tests (A):**
- **Signal order:** sorting, adding at the end, and the endpoint's validation; reordering leaves `signals_hash()` unchanged.
- **Shared order:**
  - recent before older, at the 30-day boundary;
  - the signal list's order, with deleted rows after listed ones and Other last;
  - newest first;
  - the same order on every request.
- **Paging:** visits every finding exactly once.
- **Briefing summary:** counts; types in order; the collection scope; the 422 and 404 cases.
- **Window:** `until`.

**Demo (A):** the dev copy's Briefing beside the mockup. Move a signal type up in Setup → Signal list. The Briefing follows, and the count of pages not yet checked stays the same.

### Phase B: conclusions first, operator work off reader pages

**B1. Technology page.** This is portal work only; `/technologies/{id}/summary` already returns everything. The page's order becomes:
1. the state in one sentence, with the main button;
2. Assessment;
3. Point of View;
4. Findings: the top 5 in the shared order, then "View all";
5. Pages.

**B2. Technologies list by state.** `GET /api/technologies` gains:
- a `state` filter;
- per row: `state`, `new_pages`, `assessed_at` and `has_pov`;
- `state_counts`.

States come from `evidence.states()` for the whole matching set, and the filter applies before `skip` and `limit`. `/api/pipeline` already computes the same states, in 20–30 ms on the deployed data. The inventory summary (`summary`, `last_resolve`) stays, for the portal's "Details" view.

**B3. Page limits aren't problems.**
- `problems()` stops listing websites that reached their page limit.
- `/api/problems` returns those websites as `coverage` instead. Its `count`, and the pipeline's `problems`, then count only real problems.
- These stay problems, each with its reason:
  - searches that are too broad;
  - source errors;
  - unconfigured sources;
  - failed pages;
  - failed jobs.

**B4. The rest is portal work:**
- the Points of View page lists written ones first, with batch Write on the waiting list;
- Organize technologies moves to Operations;
- the next-step banner links to results and lists instead of to buttons that cost model calls;
- the full menu shows from 1,024 px.

**Tests (B):**
- the state filter applies before paging;
- `state_counts` agree with `evidence.states()`;
- problems and coverage are split, and the pipeline count matches.

**Demo (B):**
- Open a technology from the Briefing; its conclusion and next step are on the first screen.
- Filter Technologies to "New evidence"; it lists the 25 with "Assess these 25 · about 890 model calls".
- The status pill no longer says "6 problems".

### Phase C: better words at the source

These changes apply from the next collection. Stored pages keep their text until they're checked again.

**C1. Summary prompt, `article_summary` v6.** Each finding gains two fields:
- `headline`: at most 12 words saying who did what, never starting with "The document", "The paper" or "The page".
- `technologies`: the 1–3 names from this page's `technologies` that the finding is about.

The prompt also says to skip acknowledgements, funding notes and author biographies. It's the same call with a slightly longer reply. `signals_hash()` covers signal rules only, so no page turns "not yet checked".

**C2. Parsing** in `summarize.py` keeps:
- `headline`, as text;
- `technologies`, lowercased, at most 3, and only names from the page's list.

**C3. Each finding's own technologies.**
- The organizer's `_stamp_documents` also sets `signals.N.technologies_resolved` from the finding's `technologies`, through the same alias map.
- Set-aside pages get none, as now.
- `restamp_all()` therefore covers renames and merges.

**C4. Readers prefer them.**
- `hits()` returns a finding's own technologies when it has them, otherwise its page's. The `tech` filter matches the same way.
- Assessments keep reading pages by their page-level tags, so evidence and readiness don't change.

**C5. Natural-case names.** This part can be dropped without affecting C1 to C4.
- Technologies get a `label`: "Agentic AI", "ML-KEM", "6G networks".
- At the end of each organize, technologies without a label go in batches of about 500 to a small seeded `technology_label` prompt. It may change capitals only; a label whose lowercase isn't the name is ignored.
- **Cost:** about 4 model calls once for today's 1,853 names, then about 1 per organize.
- A rename sets the label to the name as typed.
- The portal shows `label` wherever it shows a technology's name.

**Tests (C):**
- parsing keeps headlines, and keeps technologies within the page's list;
- stamping per finding;
- `hits()` prefers per-finding technologies;
- the label guard.

**Demo (C):**
- the new prompt on 10 stored pages from the dev copy, before and after, side by side. This costs about 10 model calls, and needs your go-ahead at the time;
- the register with labels.

## 4. What doesn't change

- Collecting, checking, assessing and writing, and what they cost.
- The readiness rule (`services/evidence.py`) and the waiting lists.
- The technology register (MIN_DOCS_PER_TECH stays 1), Never miss / Can ignore, Set aside, the Tata look and one portal.
- Old links: the Signals addresses redirect (portal plan §3).

## 5. Deployment

- Phases A and C change seed files. Check that Changes shows 0 on Docker before deploying them, as the existing rule says. The reload makes the configuration match the seed files.
- Rebuild atlas and lens. Phases A and B need no collection and no check.

## 6. API contract (changes only)

| Endpoint | Change | Phase |
|---|---|---|
| `GET /api/signals` | rows carry `order`; sorted by mode, then `order` | A |
| `PUT /api/signals/order` | **New.** Takes `{ids}` and returns `{signals}`; 422 unless the ids are exactly the never-miss rows. | A |
| `GET /api/signals/found` | **Parameters:** adds `sort=briefing` and `until`.<br>**Rows:** add `published_date` and `older`; chips are ordered (A3). | A |
| `GET /api/briefing` | **Returns (A5):** `scope`, `counts`, `types`, `freshness` and `new_povs`.<br>**Takes:** `days` or `run_id`, plus `tech` and `source`. | A |
| `GET /api/technologies` | **Parameters:** adds a `state` filter.<br>**Rows:** add `state`, `new_pages`, `assessed_at` and `has_pov`.<br>**Response:** adds `state_counts`. | B |
| `GET /api/problems` | **Response:** adds `coverage`.<br>**Count:** `count` leaves coverage out, and so does the pipeline's `problems`. | B |
| `GET /api/signals/found` | **Rows:** add `headline`.<br>**Technologies:** each finding's own when it has them. | C |
| technology rows | add `label` | C |

A Briefing summary from the Oct 3 data, abridged:

```json
{
  "scope": {"days": 7, "from": "2026-09-27T…", "to": "2026-10-04T…"},
  "counts": {"findings": 212, "pages": 183, "older": 93},
  "types": [{"signal_id": "funding-round", "name": "Funding round", "count": 6},
            {"signal_id": "other", "name": "Other", "count": 77}],
  "freshness": {"run_id": "20628e1f592e", "finished_at": "2026-10-04T02:09:50Z", "sources": 6, "new_pages": 183},
  "new_povs": []
}
```

## 7. Risks and notes

- **Publication dates.** "Older" trusts the page's publication date from its metadata; all 421 dated pages use YYYY-MM-DD. A wrong date mislabels a finding, but the panel shows both dates, so the error is visible.
- **The 30-day limit** is one constant. Changing it needs no other work.
- **Two kinds of tags.** Page-level tags stay for assessments. Only what's displayed, and the filters, move to per-finding tags (phase C).
- **Broad technologies** such as "artificial intelligence" and "machine learning" stay in the register, as you decided. Phase C shows them on fewer findings.
- **The 240 pages from 11 Sep** still have no findings until they're checked again. That stays your choice.

## 8. Build notes (4 Oct)

All three phases were built together, as you asked. Nothing is committed.

**Where the build differs from the plan.** All of these are small; none changes a decision.
- **Briefing types:** `/api/briefing` types also carry `older` per type, so a list filtered to one type can count its bands.
- **Point of View column:** `GET /api/technologies` returns `pov` (`{scoring_run_id, composed_at}`, or null) instead of `has_pov`, so the list can link to it.
- **Fast state list:** a new `evidence.list_states()` gives the full state only to technologies a scoring run included. The rest can only be off or not assessed, so all 1,853 load in about 25–130 ms.
- **Name capitals:** they come from `GET /api/technologies/labels`, read once by the portal (`lib/tech-labels.ts`), instead of being added to every API.
- **A finding's own technologies** are stored only when at least one of its names is on the page's list (and stamped only when one resolves). Otherwise the finding uses its page's, so no finding loses its technologies.
- **Removed options:** `/signals/found` lost `facets` and `on_list`; only the Signals page used them.
- **Back links:** they now refuse addresses like `/administrator`.
- **Organize technologies** is now the Organize step's button on the Operations board.
- **Page-limit wording:** summaries say "reached the page limit": history rows, the collections list and the next-step banner. The per-source badges on a collection's page still say "Didn't finish", because they cover data sources too.
- **A collection's page:** step 2 is now "Findings", with "See its findings on the Briefing" opening the Briefing for that collection.
- **Code tidy-up:** `AnalystBox` is gone. `lib/waiting.ts` words each waiting item and says where it's handled, for the Briefing, the status pill and the next-step banner.
- **Renames:** typing a name with capitals keeps them as the label.

**Checks:**
- 79 backend tests pass; the 7 new ones cover the signal order, the shared order and paging, the Briefing summary, the state filter, problems and coverage, parsing, per-finding stamping, labels and renames.
- Portal type-check, lint and build are clean.
- Headless Chromium on the dev copy, refreshed from Docker's data: 18 routes at 400, 1,100, 1,280 and 1,440 px, with no errors and nothing scrolling sideways. The old Signals addresses redirect.
- Clicked through:
  - the side panel, including Esc returning focus;
  - type filters, "Show more" and the older-article note;
  - a collection's scope and the technology filter.
- Reordering a signal type in Setup changes the Briefing's first finding, and leaves "not yet checked" at 240 → 240.

**Phase C demo on the dev copy:** 18 model calls in total.
- **Summaries:** 8 Oct 3 pages through `article_summary` v6, for 10 calls. Two first replies weren't valid JSON, and the existing retry fixed both.
- **Probes:** 2 calls re-asking those two pages; both parsed first time.
- **Organize:** 6 calls, labelling 1,863 of 1,864 names.

| Before | After |
|---|---|
| "The document acknowledges partial support from several Horizon Europe projects…" (as a Government programme) | gone |
| "Cisco has announced end of life for UCS Manager and is directing its infrastructure-management approach toward…" (tags: agentic ai, post-quantum cryptography, +12) | "Cisco retires UCS Manager in favor of Intersight" (infrastructure management) |
| "Cisco and NVIDIA are described as building context-aware, distributed controls…" (15 page tags) | "Cisco and NVIDIA build controls for safe enterprise AI agents" (Agentic AI, network security) |
| "O-ID raised $1.2M in pre-seed funding to develop fully modular humanoid robots…" | "O-ID raises $1.2M pre-seed to build modular humanoid robots" |

**To watch:** the two first-attempt JSON failures. If the next collection shows "reply not in the expected format" under Problems more than before, the v6 prompt is the first place to look.

**Docker (4 Oct):**
- **Before deploying:** Changes showed 1 item, the new `technology_label` prompt. Docker mounts `./seeds`, so it already saw the new file; it was not a live edit. No job was running.
- **The deploy:** rebuilt atlas and lens. The seed files reloaded: 12 prompts, with `article_summary` v6; signals with `order`. Changes then showed 0.
- **Labels:** a one-off `label_missing()` labelled all 1,853 technologies in 4 model calls.
- **Numbers:**
  - Briefing: 212 findings from 183 pages, 93 of them older;
  - Problems: 0, plus coverage for 6 websites, so the status pill no longer says "6 problems";
  - waiting: 240 pages to check, 25 technologies to assess, 35 Points of View to write.
- **Browser check:** all 18 routes at four widths, with no errors and nothing scrolling sideways.
- **Stored findings** keep their old wording until the next collection. Their headlines and per-finding technologies come with it. Re-checking the Oct 3 pages would also refresh them, at about 183 calls; that wasn't done.

## 9. After review: what the states mean (4 Oct)

The user asked for definitions of the Technologies filters, and for why so many technologies aren't assessed. Approved and built the same day; the portal side is in the lens plan's §10.

**Why 1,793 aren't assessed:** the only assessment (Sep 11) took the 60 technologies with at least 3 pages. Of the rest, 1,465 have one page and 229 have two. **99 have 3 or more pages** but got there after Sep 11, and no waiting list counted them.

**API:** `GET /technologies` adds `over_floor`: `{min_pages, started_at, tech_ids, technologies, calls, calls_max}` or `null`.
- `min_pages` is `params.min_docs` of the newest assessment run started by page count (`started_at` is that run's).
- The group is the search's matches whose state is `not_assessed` and whose new pages (every page, for these) reach `min_pages`.
- It's `null` when no run used a page count, or when nothing qualifies.
- Not added to the pipeline's waiting items, so the Briefing and the status pill don't show it.

**Cost:** about 4,950 model calls for the 99: 50 each, because a technology with no assessment has no fabric choice yet, so the estimate counts every fabric. The real figure may be lower.

**Tests:** 80 pass (a new test covers `over_floor`: none before a run by page count, the group after, none while it's being assessed).

## 10. The Briefing without new Points of View (4 Oct)

The user asked for the Briefing to stop listing new Points of View: one "Write all" would add dozens of names, and the Points of View tab already lists them newest first. `GET /briefing` no longer returns `new_povs` (`_new_povs` is removed), and `test_briefing.py` asserts it's absent. Page descriptions are portal-only; see the lens plan's §11.

Deployed at 08:10 UTC, after the 99-technology assessment run finished: 99 of 99 technologies, 2,719 model calls against an estimate of 4,950. Waiting first kept the API restart from stopping the run. Changes was 0 before and after, and 80 tests pass.
