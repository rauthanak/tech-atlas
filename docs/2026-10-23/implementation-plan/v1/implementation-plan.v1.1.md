# Implementation plan v1: 23 Oct 2026

The owner's review of 23 Oct: the token-limit message, a crawl that stops on one bad link, points 1–9, the Don Norman review of 22 Oct, and performance, memory and scale.

This is the master plan for both apps. The portal side is indexed in [tech-lens/docs/2026-10-23/implementation-plan/v1/implementation-plan.md](../../../../../tech-lens/docs/2026-10-23/implementation-plan/v1/implementation-plan.md).

**Status:** plan only, nothing built. v1.1 (23 Oct, later) adds your answers: lists come back to the same rows, indexes live in the seeds, signs to watch get their own collection, the Briefing shows 15, and path-step removal is explained. v1.0 is kept beside it as `implementation-plan.v1.0.md`. It waits for sign-off and the open decisions in §14.

**Evidence behind it:**
- Live data on 23 Oct: 10,514 technologies, 5,719 pages, 1,572 assessments.
- Read-only timings and `explain()` plans on the running API.
- A code read of both apps.
- Screenshots of all 36 pages at 1440 and 400 px.

No model calls are needed for anything in this plan.

**Rules kept throughout:**
- No functionality is dropped. Anything that moves says where it went.
- Every failure says why.
- Show the cost and ask, rather than cap.
- Plain words.
- Config changes go through the API and `update-seeding-data`.
- Each built item is checked as a first-time reader at 1440 and 400 px and gets a client docx entry.

---

## Contents

1. [Why Classify said "stopped"](#1-why-classify-said-stopped-at-a-token-limit)
2. [A bad link must not stop a source](#2-one-bad-link-or-page-must-not-stop-a-source)
3. [Signs that crossed their threshold (point 1)](#3-signs-that-crossed-their-threshold-point-1)
4. [A shorter Briefing (point 2)](#4-a-shorter-briefing-point-2)
5. [Pages of 50, not "Show more" (point 3)](#5-pages-of-50-not-show-more-point-3)
6. [One kind of filter (point 4)](#6-one-kind-of-filter-point-4)
7. [Technology Overview layout (point 5)](#7-technology-overview-uses-the-width-point-5)
8. [Operations › History tab (point 6)](#8-operations--history-as-its-own-tab-point-6)
9. [Path to scale: add, remove, reorder (point 7)](#9-path-to-scale-add-remove-and-reorder-steps-point-7)
10. [Don Norman review items (point 8)](#10-don-norman-review-items-point-8)
11. [Performance, memory leaks, scale (points 3 and 9)](#11-performance-memory-leaks-and-scale-points-3-and-9)
12. [Order of work](#12-order-of-work)
13. [How each phase is checked](#13-how-each-phase-is-checked)
14. [Decisions needed from you](#14-decisions-needed-from-you)

---

## 1. Why Classify said "stopped at a token limit"

**What happened.** The limit is gone, and nothing will stop at it again.

- The 22 Oct collection (run `3ba3d120703a`) started at 9:56 AM CDT. Its Classify step (`3819d781df18`) ran at 10:56 AM, under the old 8,000,000-token limit. It judged 2,908 of 8,715 technologies and stopped.
- We removed the limit that afternoon.
- The remaining 5,807 were judged on demand at 12:55 PM (`02ffcc39aa73`, completed, 0 failures).
- No collection has run since. The run page is still describing that one old event.

**Why the screen confuses.** It shows "Done" next to "It stopped at a token limit the radar no longer has. The rest were classified since". Operations › History shows the same Classify row with a bare STOPPED chip and no reason.

There is also a latent bug. For any run that isn't the latest, the step stays "stopped" and quotes today's pending count: "stopped before the end, with 0 technologies still to judge" (`tech-lens/components/RunSteps.tsx:264-287`).

**What I'll do**

1. **One plain sentence for a Classify finished in parts** (`RunSteps.tsx`). For example: "All 8,715 judged: 2,908 during this collection, the other 5,807 on Oct 22 at 12:55 PM."
   - The old cause goes in the details line under it: "The first part stopped at a spending limit that was removed on Oct 22."
   - To find which later Classify finished the work, `api/runs.py` adds `classify.finished_by: {id, at, done}`. This is the first completed on-demand classify after the run whose total covers the rest.
2. **Old runs never quote today's pending count.** They use only their own record.
3. **History (Operations):** the Classify row gets its reason, "Stopped at the old spending limit (removed Oct 22); finished on demand at 12:55 PM", and the chip reads "Finished in two parts".
4. **No code path can stop Classify for spending any more.** Confirmed in `agent/classifier/classify.py`: no budget. `RETIRED` in `api/settings.py` stays, so old settings records are cleaned.

**Files:**
- `tech-atlas/src/app/api/runs.py`
- `tech-lens/components/RunSteps.tsx`
- `tech-lens/app/admin/operations/page.tsx` (or the History tab, §8)

**Tests:** `tests/test_run_page.py` gets a case for "finished by a later classify".

**Size:** S.

---

## 2. One bad link or page must not stop a source

**What happened in the 22 Oct collection:**

| Source | Pages read before it died | Error | Where it escaped |
|---|---|---|---|
| Cisco blogs | 6 | `Invalid IPv6 URL` | one `<a href>` with a malformed bracketed host; `urljoin` raised in `crawl.py:82` |
| arXiv | 42 | `'utf-8' codec can't encode … surrogates not allowed` | a page's text held a lone surrogate (from an entity such as `&#xD83D;`); hashing it in `store.py:192` raised |

The whole source is wrapped in a single `except Exception` (`crawl.py:376`). Any per-link or per-page error therefore ends the source, and the "links left" note is skipped as well.

**Every escape point found:**

1. `crawl.py:82`: `urljoin` in `_extract_html`.
2. `crawl.py:173`: `urljoin` in `_advertised_feeds`.
3. `crawl.py:47, 65`: `urlparse` in `site_of` and `skipped`, called from `queue()`.
4. `crawl.py:257`: `urlparse` in `allowed()`.
5. `crawl.py:150, 183, 306`: `client.get` catches only `httpx.HTTPError`. `UnicodeEncodeError` and `httpx.InvalidURL` escape. The `:150` case is the sitemap read before the loop, so one bad `<loc>` kills the source at its start.
6. `crawl.py:72`: `trafilatura.extract` has no guard.
7. `store.py:192, 217, 226`: hashing and inserting text that holds surrogates.
8. `scout/adapters/base.py:186, 200`: one bad item ends a whole saved search.
9. `find_evidence/job.py:155-175`: one bad page aborts the job and leaves its run "running".

**What I'll do**

1. **Skip one bad link and carry on.** In `_extract_html` and `_advertised_feeds`, wrap each link: on `ValueError`, skip it and count it. `queue()` and `allowed()` do the same; robots falls back to "allowed".
2. **Skip one bad page and carry on.** In the crawl loop, wrap the body for each page in a `try`:
   - On any error except `InterruptedError` (a cancel), record the page as `{url, reason}` and continue.
   - Reasons are grouped in plain words, such as "a link with a malformed address" or "text the reader couldn't decode".
   - `finish_source` stores them as `page_errors: {reason: count}`, plus up to 5 example addresses.
3. **Clean text once, at the source.** A `clean_text()` in `scout/tools/crawl.py` replaces lone surrogates. It is applied to text, title and links in `_extract_html` and `extract_pdf`, and again in `save_document` before hashing. Uploaded files (Add evidence) go through the same function.
4. **Widen the fetch catches** at `:151`, `:184` and `:307` to `(httpx.HTTPError, ValueError, UnicodeError)`, each with its reason.
5. **Saved searches and Find evidence.** Add a per-item `try` in `adapters/base.py`. In `find_evidence/job.py`, wrap each page: a bad page is reported in the job summary ("2 of 5 pages couldn't be read: …") and the job finishes properly.
6. **What people see.** On the run's Sources table and the Run › source page:
   - "Read 60 pages; skipped 3: 2 links with a malformed address, 1 page whose text couldn't be read."
   - The examples sit under Technical details.
   - A source is shown as failed only when nothing could be read at all.

**What I won't do without asking:** start a collection to re-read Cisco and arXiv. The next collection picks them up.

**Tests** (`tests/test_crawl.py`, new cases):
- a page with `href="http://[bad"` still yields its other links and the next pages;
- text with `"\ud83d"` saves;
- a sitemap with one bad `<loc>`;
- a Find evidence job with one bad page finishes and says which page failed and why.

**Size:** S (about 40 lines plus tests).

---

## 3. Signs that crossed their threshold (point 1)

**What a "threshold" is today**

- **No person sets them, and no Setup page lists them.** When the model assesses a technology, the `watch_metrics` skill (stage "assess", one call per technology) proposes 2–4 *metrics to watch*. Each metric carries:
  - `metric`: what to watch;
  - `current_value` and the `source` it came from;
  - `inflection_threshold`: the point at which the answer changes;
  - `direction`;
  - `implication`: what it would mean for Tata.
- **They carry forward word for word.** Set at the first assessment, later assessments repeat them (`agent/analyzer/engine.py:221-231`).
- **"Crossed" is the model's call, checked by one rule.** The model compares the current value with the threshold. A "crossed" is kept only if its source is one of the pages that assessment read; otherwise it becomes "can't tell" (`engine.py:244-255`).
- **Where they show:**
  - the Briefing (`GET /api/scoring/crossed`, 5 today);
  - the technology's Fabrics tab ("Metrics to watch");
  - the Point of View.

Example (Software bill of materials):
- **Threshold:** "A published rule or directive that makes a software bill of materials mandatory for government or critical-sector software procurement."
- **Was:** "Guidance is non-binding…"
- **Now:** "A CERT-In … framework … mandates SBOM…"

**What's wrong:**
- A reader can't tell what a threshold is, who set it, or where to change it.
- Each item reads as one run-on paragraph: "Was … now … (threshold: …)".

**What I'll do**

1. **Say what it is, where it shows.**
   - On the Briefing, one line under the heading: "Each assessed technology has 2–4 signs to watch. The radar proposes each sign and the point at which the answer changes (its threshold) at its first assessment, and checks them at every assessment. A person can change a threshold on the technology's page."
   - The same line, shortened, under "Metrics to watch" on the Fabrics tab and on the Point of View.
2. **Lay each item out as labelled lines, threshold first:**

   ```
   Software bill of materials · assessed Oct 22                         Open →
   Watching   Whether national guidance on SBOMs becomes binding for government buying
   Threshold  A published rule that makes an SBOM mandatory for government or critical-sector buying
   Was        Guidance is non-binding (v2.0, July 2025)
   Now        CERT-In's space framework (Feb 2026) mandates SBOM for satellite operators   source ↗
   Means      Tata's supply-chain and compliance offers move from optional to expected in public bids
   ```

   On the Briefing, each item is one closed line (technology · what's watched · crossed on date) that opens to these lines (§4).
3. **Every assessed technology keeps its own signs, in their own collection** (agreed: Q1).
   - **Coverage today:** all 326 assessed technologies have signs (197 have 4, 117 have 3, 7 have 2, 5 have 5): about 1,150 signs. A technology gets its signs at its first assessment, and unassessed technologies have none until then.
   - **Today they are stored badly.** They live inside each assessment record, copied once per fabric (up to 6 copies), and are found again by their wording.
   - **New collection `watch_metrics`:** one record per technology per sign. It holds:
     - `tech_id` and a stable `metric_id`, given once and never reworded;
     - what's watched, the threshold, its direction and what it means;
     - `history`: one entry per assessment, with the value, its source, crossed yes/no/can't tell, and the assessment id and date.
   - **The Briefing becomes one indexed query** on the latest crossed signs. The Fabrics tab and Point of View read the same records.
   - **Assessment records keep their copy as a snapshot**, so Points of View and published editions already written don't change.
   - **One-off backfill** from the latest assessment of each of the 326 technologies. No model calls.
   - **A person's choice is a decision,** like every other person's choice (`kind: "watch_threshold"` with the new wording, `kind: "watch_crossed"` to overrule, both keyed by `metric_id`). That gives the same who / when / why, Undo, and "never overwritten by a new run". The sign shows the person's threshold, marked "(set by a person)".
   - On the Fabrics tab each sign gets "Edit threshold", "Not crossed" and Undo.
   - The `watch_metrics` skill receives each sign with its `metric_id` and a person's threshold as fixed. It reports the new value and may add a sign, but not reword or drop one a person set.
4. **No Setup page for thresholds.** They are per technology, so they live where the technology is. The Briefing line says so.

**Files:**
- **API:**
  - new `services/watch.py` (the collection: save after an assessment, apply people's choices, latest crossed);
  - `api/scoring_runs.py` (`/scoring/crossed` reads it);
  - `services/decisions.py` (two kinds);
  - `services/db/mongo.py` (`watch_metrics` in COLLECTIONS) and the index file (§11, P1-1);
  - `agent/analyzer/engine.py` (`previous_watch` reads the collection and marks fixed thresholds);
  - a one-off backfill script `scripts/backfill_watch.py`;
  - the `watch_metrics` skill, one sentence added through the API and `update-seeding-data`, version bump.
- **Portal:** `components/CrossedSigns.tsx` and `components/FabricAssessment.tsx` (the metrics block).

**Tests:**
- the backfill gives one record per sign, with no copies per fabric;
- a re-assessment adds a history entry and keeps the `metric_id`;
- a person's threshold survives a re-assessment;
- "Not crossed" removes the item from the Briefing;
- Undo restores it.

**Size:** M (the collection, backfill, editing, wording and layout).

---

## 4. A shorter Briefing (point 2)

**Today:** 3,450 px tall at 1440 (3.8 screens) and 6,723 px at 400 (7.5 screens).

| Section | Height at 1440 | At 400 |
|---|---|---|
| Header | 180 | 265 |
| Now line | 45 | 100 |
| To do | 230 | 580 |
| Signs that crossed | 800 | 2,560 |
| What the radar found (20 findings plus a 240 px side rail) | 2,045 | 3,060 |

**Goal (Norman: visibility of what matters, no hunting):**
- **At 1440,** the Briefing answers three questions within the first screen: where the run is, what I should do, and what changed. The whole page stays under about 2 screens (with 15 findings).
- **At 400,** it stays under about 3.7 screens.

**What I'll do (nothing removed; each part says where the rest is):**

1. **Header:** the scope ("Last 7 days · 6,728 findings from 4,780 pages · last collected …") becomes one line. "How to read this page" stays as a closed details element. Saves about 80 px.
2. **Now line:** unchanged (one line).
3. **To do:** unchanged at 1440 (three columns, first three items each). At 400 the columns become closed rows with their counts ("Before scoring · 3 ▸"). Saves about 400 px on phone.
4. **Signs that crossed:** one closed line each, the 3 newest first, plus "All 5 signs →".
   - The link goes to the Technologies list filtered to "a sign crossed" (a new status filter, §6). The full detail opens in place (§3).
   - Saves about 650 px at 1440 and about 2,200 at 400.
5. **What the radar found:**
   - 15 per page with a pager (§5): "1–15 of 2,011 · Next →" (agreed: Q2).
   - Findings about the same story are grouped into one card, "also reported by inc42.com, entrackr.com".
   - The signal-type rail becomes one "Kind of finding" dropdown above the list (§6), which frees the 240 px column for the findings.
   - Saves about 1,100 px at 1440.
6. **Projected heights:** about 1,700 px at 1440 and about 3,300 px at 400.

**Grouping duplicates (API).** `GET /signals/found` groups hits by a story key: the normalised title plus the same technology, within 3 days. It returns `also: [{source, url}]` on the first hit. Counts are per story. A person can still open each copy.

**Files:**
- **Portal:** `app/admin/page.tsx`, `components/GateList.tsx` (phone rows), `components/CrossedSigns.tsx`.
- **API:** `api/signals.py` (grouping).

**Tests:** grouping is unit-tested in `tests/test_signals.py`, and the page heights are checked in the walk.

**Size:** M.

---

## 5. Pages of 50, not "Show more" (point 3)

**I agree.** "Show more" keeps every earlier row in the DOM and in memory, and most of these lists already ask the server for more each time. Real pages keep the DOM small and the server work bounded, and they make the position clear: "51–100 of 10,512".

**One pattern for every long list:**
- **Server-paged lists:** `usePaged(url, 50)` in `lib/paging.ts`.
  - It reads and writes `page` in the URL, so Back and shared links keep the page.
  - It fetches `skip=(page-1)*50&limit=50` and replaces the rows rather than appending.
  - It cancels an older request when a newer one starts (`AbortController`). This also fixes rows from two filters getting mixed.
- **Lists that are already all in memory and small:** `useClientPage(rows, 50)`.
- **One `<Pager>` component:** "‹ Prev · 1–50 of 10,512 · Next ›", plus page numbers when there are 7 or fewer pages, and "Go to page" beyond that. It sits at the top and bottom of the table and is keyboard reachable.
- **Changing a filter resets to page 1.** After an action, only the current page reloads.
- **Coming back puts you on the same rows.** This applies to every paged list. If you were on 101–150 of Technologies, open a technology, go to Operations and then come back by any route (Back, a breadcrumb, the top menu), you see 101–150 with the same filters, sorting and search.
  - **How:** the list's place (filters, sort, search, first row) is in the address, so Back and shared links keep it. Each list also remembers its last place for the browser tab (`sessionStorage`, one key per list). Arriving at the list with a bare address, as from the top menu, restores that place.
  - **"Start over"** next to the pager goes to the first rows with no filters.
  - **If the list changed meanwhile:**
    - the same starting row is kept (101–150 stays 101–150);
    - if there are now fewer rows, it shows the last full page and says "The list is shorter now: showing 51–87 of 87";
    - the row you opened is scrolled into view and briefly marked.
  - Storage that fails or is empty (a private window) only means you start at the first rows. Nothing breaks.
  - Checked in the walk for every paged list: go to 101–150, leave by the top menu, come back, and assert 101–150.
- **Bulk actions across pages.** "Select all 10,512 matching" sends the *filter*, not 10,512 ids (§11, P2-6). Picking rows on a page still works.

**Lists to convert** (page size 50 unless noted; nothing else about them changes):

| List | File | Today | Server change |
|---|---|---|---|
| Technologies | `app/admin/technologies/page.tsx` | append 100; reload refetches up to 500 rows | slim rows plus a separate facets call (§11, P2-1) |
| Briefing › What the radar found | `app/admin/page.tsx` | append 20 | none (`skip`/`limit`/`total` exist); page size **15** here (§4, Q2) |
| Technology › Pages | `app/admin/technologies/[id]/page.tsx` | append 50, reset every 5 s while assessing | none |
| Run › source › pages | `app/admin/runs/[id]/sources/[sid]/page.tsx` | append 10 full texts | page size 10; full text loads only when a page is opened |
| Points of View | `app/admin/scoring/pov/page.tsx` | downloads all, shows 24 more each time | add `skip/limit/sort/fabric/priority` and counts |
| Operations › History | §8 | 3 full fetches, +20 | one merged `GET /api/history?skip&limit` |
| Assessment run table | `app/admin/scoring/assessments/[id]/page.tsx` | 6.3 MB once, and every 5 s while running | add `skip/limit/sort/fabric/q` and `GET …/grid` counts |
| Signal list › Set aside, Suggestions | `components/SetAsideList.tsx`, `SignalSuggestions.tsx` | append 20 | none |
| Import › list | `app/admin/import/page.tsx` | "Show all" | client pager |
| Setup › Changes | `app/admin/(setup)/changes/page.tsx` | every item open (1,981 cards, 432,000 px tall) | paged and grouped (§10, A4) |

**Size:** M, done in two parts: the shared hook and Pager, with Technologies and Briefing first, then the rest.

---

## 6. One kind of filter (point 4)

**Today the Technologies page has four looks for filters:**
- 10 rounded "group" chips;
- a status line made of underlined text links;
- an azure "Commercial availability" strip, a third button style;
- 8 dropdowns.

On top of that, "How the groups work" is open by default.

**Status can be set in three places:** the text links, the "Any status" dropdown and a "Showing" pill. The groups also overlap the availability strip (Emerging, Mature, New to Tata, Blind spots) and the catalog dropdown. The list starts about 740 px down at 1440.

**What I'll do: three controls, each with one job, and one look each**

```
[All] [Assessed] [Not assessed] [Emerging] [New to Tata] [Mature] [Blind spots] [Possibly nascent] [Catalog, thin] [Off]   ← 1. Group: segmented buttons
Status ▾   Commercial availability ▾   Domain ▾   Sub-domain ▾   TRL ▾–▾   Evidence ▾   Fabric ▾   Catalog ▾   🔍 Search   ← 2. Narrow: labelled dropdowns, each option with its count
Showing: Status: Ready to assess ✕   Catalog: In the catalog ✕   Clear all            1–50 of 37   ← 3. What's on: removable chips
```

1. **Group** (which kind of technology). One row of segmented buttons, the selected one filled.
   - The one-line meaning of the selected group sits under it.
   - "How the groups work" is closed by default.
2. **Narrow** (labelled dropdowns, all in the same style, each option showing its count).
   - The status text links and the availability strip become the Status and Commercial availability dropdowns. Every option they had is kept, with counts.
   - Sub-domain shows only once a domain is chosen, as now.
3. **What's on.** Every active filter, including the group, status, search and a Briefing link's filter, shows as one removable chip.
   - "Clear all" clears everything. Today it leaves status, group and search on.
   - Search is written to the URL, so Back keeps it.
   - The new "A sign crossed" status (§4) shows here when it comes from the Briefing.

**No link styling for filters anywhere.** A link goes to another page; a button or dropdown changes this one. The same pattern applies to:
- the Points of View list filters;
- Setup › Sources (kind and switched-on filters);
- the Briefing's kind of finding (§4).

**Projected:** the list starts about 330 px down instead of about 740.

**Files:** `app/admin/technologies/page.tsx`, split into `TechFilters.tsx`, `TechRow.tsx` (memoised, §11) and `TechBulkBar.tsx`. Plus a new `components/FilterChips.tsx`, shared.

**Size:** M.

---

## 7. Technology Overview uses the width (point 5)

**Today at 1440:** one stacked column.
- The Point of View card and "Waiting on you" fill only the left 70%.
- The catalog text and Look-for names sit in an 896 px `max-w-4xl` block, leaving about 470 px empty.
- The four answer cards (Availability, TRL, Domain, Evidence) are stretched to equal heights, so two are half blank.
- The Next-step box stops short of the edge.

**What I'll do: two columns at 1280 px and wider, one column below**

```
┌ Next step ──────────────────────────────────────────────────────────────────────── full width ┐
├──────────────────────────────────────────────────────────┬────────────────────────────────────┤
│ Point of View  headline · Read · Rewrite                 │ Commercial availability   Emerging │
│ Priority in each fabric  [Cloud P2] [Interaction P2] …   │ Readiness (TRL)   7 of 9           │
│ 50 of 60 measures scored; 10 wait for your figures →     │ Domain   AI › Agents               │
├──────────────────────────────────────────────────────────┤ Evidence   Strong · 391 pages Why? │
│ Waiting on you                                           ├────────────────────────────────────┤
│  Interaction  owner · next step · figures …              │ In Tata's catalog: "…" (2 lines)   │
│  Cloud        …                                          │ Looked for on pages as … Edit      │
└──────────────────────────────────────────────────────────┴────────────────────────────────────┘
```

- **Main column (about 2/3):** the Point of View and Waiting on you. Rows inside Waiting on you lay out in a grid (fabric · owner · next step · figures), so they use the width rather than ending at about x 1,100.
- **Side column (about 1/3):** the four answers as compact label–value rows with no forced equal height, then the catalog description and the names it's looked for by.
- **Width rules:** the `max-w-4xl` limits inside these columns go. Cards size to their content (`items-start`). The Next-step box spans the full width.
- **Below 1280 px:** one column in the order Next step, Point of View, answers, Waiting on you, catalog, names.
- **The wording fix** "50 of 60 measures had enough evidence" becomes "50 of 60 scored; 10 wait for your figures (threat, capture)" (§10, A5).

**Files:** `app/admin/technologies/[id]/page.tsx`, `components/TechAnswers.tsx`, `WaitingOnYou.tsx`, `LookFor.tsx`, `PageHeader.tsx` (Next step at full width).

**Size:** M.

---

## 8. Operations › History as its own tab (point 6)

**Today:** Operations tabs are Overview · Collections · Assessment runs. History is the largest block on Overview, about 1,035 of 2,731 px. It makes 3 fetches (100 + 200 + 300 rows) and repeats links to the other two tabs.

**What I'll do**

1. **Add a fourth tab,** Overview · Collections · Assessment runs · **History**, at `/admin/operations/history` (`components/OperationsTabs.tsx`).
2. **History, paged 50,** comes from one new endpoint, `GET /api/history?skip&limit&kind=`. It merges collections, assessment runs and model-usage events on the server, newest first.
   - The "Cost by skill" expander, status chips and every current fact stay.
   - A "Kind" dropdown filters it (Collection, Organize, Classify, Assess, Point of View, Find evidence).
3. **Overview keeps:**
   - the Latest run (six steps);
   - Problems;
   - Coverage;
   - Service health (with Technical details);
   - one line, "Last activity: Assess finished 10:14 PM · History →".

   Projected Overview: about 1,600 px instead of 2,731 at 1440.
4. **Names** follow the steps (§10, C1): "Organize · link known names" not "Linking known names", "Assess" not "Assessment", and so on.

**Files:**
- **Portal:** `app/admin/operations/page.tsx`, new `app/admin/operations/history/page.tsx`, `components/OperationsTabs.tsx`.
- **API:** new `api/history.py`.

**Size:** S–M.

---

## 9. Path to scale: add, remove and reorder steps (point 7)

**What "a technology has reached a step" means.** The path to scale is the seven steps from Evaluation to Investment, set in Setup › Path to scale. For each technology and fabric, a person records how far Tata has got, on the technology's page (Fabrics tab › Path to scale, "Reached Customer zero"). That record is what Points of View and leaders read as "Customer zero, step 2 of 7", and it decides which figures finance asks for next.
- **Today there are 2 such records,** both from the demo plan: Agentic AI reached Evaluation in Cloud and Customer zero in Interaction.
- **Removing a step happens on Setup › Path to scale,** where steps are added, edited and reordered.
- **If someone removes a step that a record points to** (say Customer zero), that record would point at nothing. Agentic AI in Interaction would lose its place on the path, and its Point of View would have no step to name. So the Remove button checks first and says, for example: "Agentic AI (Interaction) has reached Customer zero. Move it to another step first."
- **"Move them to…"** re-records those technologies at a step you pick, as a person's choice with Undo. The step can then be removed.

**Today:**
- **Setup page:** `ListItems list="path_steps"` with `canAdd={false} canRemove={false}`. Only the name, "proof needed" and "what it lets Tata decide" can be edited.
- **API:** has create (`POST /lists/path_steps`) and delete. But:
  - delete has **no guard**: it would orphan recorded progress;
  - `needs` (which proof figures a step requires) **can't be edited**;
  - reordering means one `PUT` per step.
- **Hard-coded text:** the page says "The seven steps" and "Beta, Roadmap and Investment have no proof written yet".
- **Data:**
  - Recorded progress is stored as decisions pointing to the step's id (`kind: "path_step"`). Adding a step can't break it, but removing one could.
  - Finance treats "Proof of concept" as the step from which figures are needed (`services/finance.py:41`).
  - Points of View say "step N of M".
  - Published editions keep each step's *name*.

**What I'll do**

1. **Add step** (Setup › Path to scale): name, proof needed, what it lets Tata decide, and "insert after…".
   - The id comes from the name (`slug`) and never changes, even if renamed.
   - The new step's `order` goes in place; later steps move down by one in one call: `PUT /lists/path_steps/order {ids: [...]}`.
2. **Reorder** with ↑/↓ on each row. It saves in one call and shows "Saved: Beta is now step 5 of 8".
3. **Remove step,** guarded:
   - **If no technology has reached that step,** remove it after a confirm. Undo puts it back with its order.
   - **If some have,** the button says so: "4 technologies have reached Beta (Agentic AI in Interaction, …): move them to another step first." A "Move them to…" picker re-records their progress, as a person's choice, with a reason.
   - "Proof of concept" can't be removed, because finance starts asking for figures from it. Its row says so.
4. **Proof needed (`needs`) becomes editable,** as a checklist of the figures finance knows (`finance.NEEDS`). The API validates against that list.
5. **Text follows the data.** "The N steps", and the line listing steps without proof is computed.
6. **Effects, said on the page before saving:**
   - New Points of View say "step N of M" with the new count.
   - Points of View already written keep their wording until rewritten.
   - Published editions keep the step names they were published with.
7. **Seeds.** A step change shows on Setup › Changes like any config edit, and "Keep as defaults" writes it to `seeds/path_steps.json` through `update-seeding-data`.

**Files:**
- **API:** `api/lists.py` (order endpoint, `needs` editable, delete guard with "move to"), `services/decisions.py` (move progress).
- **Portal:** `app/admin/(setup)/path/page.tsx`, `components/ListItems.tsx` (add, remove and reorder already exist for other lists, so turn them on with the guards), `components/PathToScale.tsx` (no hard-coded counts).

**Tests** (`tests/test_lists.py`):
- add or insert keeps the order;
- delete is refused with names when a step is in use;
- "move to" re-records progress;
- POC can't be removed;
- `needs` is validated.

**Size:** M.

---

## 10. Don Norman review items (point 8)

All the recommendations from the 22 Oct review, with ids for tracking. Items already covered above are cross-referenced, not repeated.

### A. Wrong or misleading numbers (first: small, and they erode trust)

| # | Item | Fix | Files | Size |
|---|---|---|---|---|
| A1 | Assessment run priority grid counts by *priority*, not *cell*: "P2 121" in two cells; the 9 cells add up to 1,099 for 607 rows | count and filter by cell (how-soon band × how-big band); "How the grid works" unchanged | `app/admin/scoring/assessments/[id]/page.tsx:224,410` (server grid counts in §5) | S |
| A2 | Leaders' grid: the help says the corners are split by the dotted priority lines at 4 and 7, but they're drawn at 5.5, so "Act" holds P3s and best bets ≠ P1 | draw Act/Plan/Wait/Watch on the priority lines, so "Act" = P1 territory; the first card becomes "Act now: P1", best bets after it; help text matches | `components/frontier/Grid.tsx:246-247`, `app/frontier/page.tsx:300-310` | S–M |
| A3 | Weights shown as % but rescaled to 100% in scoring (40/50/30 is really 33/42/25) | edit a score's three weights together on Weights & Grid with a live total that must reach 100%; Measures shows the real share | `app/admin/(setup)/scoring/config/page.tsx`, `measures/page.tsx`; `api/scoring_config` validation | M |
| A4 | "Setup 1981" badge and Changes: all 1,981 are model-proposed sub-domains not yet reviewed, not people's edits; Changes is 432,000 px; "Select all → Keep as defaults" would make unreviewed proposals defaults (and exceeds the API's 1,000 cap) | sub-domains waiting for review leave Changes and the badge, shown as one line "1,981 sub-domains the model proposed: review on Domains →"; Changes groups by kind, closed, paged 50; badge = people's edits only, labelled in the menu ("3 unsaved setup changes"); `GET /api/changes/count` | `services/db/seeding.py`, `api/changes.py`, `lib/changes.ts`, `changes/page.tsx`, `TopBar.tsx` | M |
| A5 | "50 of 60 measures had enough evidence": the 10 wait for Tata's figures | "50 of 60 scored; 10 wait for your figures (threat, capture) →"; the same on the Fabrics tab priority line | `technologies/[id]/page.tsx`, `FabricAssessment.tsx` | S |
| A6 | 77 vs 66 sources "reached the page limit"; missing thousands separators ("1452", "2226"); the same story 3× on the Briefing (§4) | one shared count (`r.incomplete`); `toLocaleString` everywhere counts show | `runs/[id]/page.tsx:339`, `GateList.tsx`, `domains/page.tsx` | S |
| A7 | Assessment-run "Evidence from" ends with an unnamed "a collection"; the catalog explainer lists one file twice | name the collection by date, or say "a collection whose date wasn't recorded"; list each import file once | `EvidenceLine.tsx`, `technologies/page.tsx:112` | S |
| A8 | Regulators (CISA, ENISA, CERT-In, SEBI, RBI, BIS) filed under the kind "Government funding" | a "Regulator" kind via the Sources API plus `update-seeding-data` | sources config | S |

### B. Phones (400 px)

| # | Item | Fix | Size |
|---|---|---|---|
| B1 | Tables lose their key column: the Assessment run (no technology names, headers overprint), the run's Sources (failure reasons off-screen), Operations History, Collections, Setup › Sources | one `<ResponsiveTable>` that shows each row as a label: value card below 640 px; the reason sits under the source name | M |
| B2 | Leaders' grid is a blob of 390 dots | below 640 px the leaders' site opens as Table (P1/P2 first); Grid one tap away | S |
| B3 | Leaders' view link missing from the phone menu; status pill cuts off "4 problems" | add it to ☰; on phone the pill drops "Last collected" and keeps the problems count | S |
| B4 | Briefing "Why it matters" cut to one line | wrap to 3 lines | S |
| B5 | Fabrics tab chip row cut off; PoV accordion ▸ alone on a line; stepper with a dangling "—" | wrap or scroll cue; inline ▸; fix the separator | S |

### C. Words and the reader's model

| # | Item | Fix | Size |
|---|---|---|---|
| C1 | "Run", "collection" and "assessment run" mixed; "scoring" vs "assess"; History names ≠ step names | **collection** = the six-step pass ("Collection of Oct 22", "Latest collection"); **assessment** = a scoring batch ("Before assessing"); **scores** only for numbers; History rows named by step | S |
| C2 | "✓ COMPLETED" in mono capitals next to "Done"; "+ ADDED" vs "Confirmed" | one sentence-case status chip everywhere (`lib/run-states.ts`, replacing 6 local maps) | S–M |
| C3 | A collection says Completed while "Now: step 4 waits"; Next skips step 5 | chip names what finished ("Collected · 4 sources couldn't finish"); Next is the next step in order | S |
| C4 | Fabrics vs Domains never explained ("Cloud" in both) | one line on each page linking the other: domains file a technology by subject; fabrics are Tata's business areas it's scored in | S |
| C5 | The assessment's home is a tab called "Fabrics"; the Fabrics card shows priority (soon × big) and the three scores with no link between them | rename the tab "Assessment" (subtitle "by fabric"); one line: "Priority comes from how soon × how big; the three scores describe the case and feed the Point of View." | S |
| C6 | Assessment-run names don't tell runs apart ("5G, Contact center … and 3 more" twice) | "Oct 22 · 262 technologies · ready batch", the same as the page title | S |
| C7 | Two priority grids are mirror images (P1 top-left on one, top-right on the other) | flip the assessment-run grid to FAR · MID · NEAR so P1 is top-right, with the leaders' corner words | S |
| C8 | Dates in 5 formats ("21 Oct 2026", "2026-10-15", "Oct 22, 2026, 9:56 AM CDT", mono dates) | every date through `formatDay`/`formatAt`, including edition labels from the API and ISO dates | S |
| C9 | Back navigation 4 ways; "Run of Oct 22" has neither back link nor tabs | `BackLink` on every child page ("← Collections", "← Skills", "← Sources"); collection pages keep the Operations tabs | S |
| C10 | "Assessed, placed / not placed"; "P1 H1" without words; Tata's progress on two scales; "Gap" column not in the legend | "Assessed, has a priority / no priority yet"; the word next to H1–H3; show both progress scales together; add Gap to the legend | S |
| C11 | Run › source page: raw "H1", "depth 0", ISO date, lowercase tags, "Scout's take … a downstream analyst should…" | category and depth under Technical details; normal dates; tags with catalog names as links; "The radar's read"; the `article_summary` skill addresses the reader (skill edit through the API) | S–M |
| C12 | Setup menu and Skills list not in pipeline order; Settings under System | Collect → Organize → Classify → Assess → Point of View, Skills grouped by step like the map; group labels kept on phone | S |
| C13 | Editable rows: whole-row click on Sources and Skills, "Edit" elsewhere | "Edit" link on every editable row | S |

### D. Feedback, cost, undo

| # | Item | Fix | Size |
|---|---|---|---|
| D1 | Switching a signal on or off is one click; it marks every stored page "not yet checked" (about 1 call each) with no count | confirm in place: "Marks 5,719 stored pages to be checked again: about 5,719 model calls when you run the check"; "Saved" shows on the row | S |
| D2 | Domains "Merge into…" merges as soon as you pick; Changes has no "put back the default" | choose, then confirm, with Undo; each Changes card gets "Put back the default" (`POST /api/changes/revert`) | M |
| D3 | Point of View: "38 pages arrived after this was written" sits next to Rewrite, which won't take them in | the bar offers "Assess again · about 6 calls"; Rewrite's confirm adds "the 38 newer pages won't be included" | S |
| D4 | Cost shown before a job in model calls, after it in tokens | model calls before and after; tokens move under "Cost by skill" and Technical details | S |
| D5 | Problems' "Open collection" doesn't fix anything; a missing key doesn't say who acts | link each problem to its source; "Needs a free OpenAlex key: ask whoever runs the server to add OPENALEX_API_KEY"; or "Nothing to do; the next collection retries" | S |
| D6 | Settings switches ("Judge the evidence after each collection", "Let the model reason") show no estimate | an estimate per collection next to each | S |
| D7 | Scoring edges: "Save the edges" doesn't say what moves | before saving: "With these edges: 14 move P2 → P3, 3 move P1 → P2" (arithmetic on the latest run, no calls) | M |
| D8 | Points of View list: "1 was written after the edition" but which one isn't shown | "Not in the Oct 22 edition" chip on the card; the count is a filter | S |
| D9 | Looks clickable but isn't (Import step pills); clickable but doesn't look it (Collections rows, To do lines) | flat progress strip for Import steps; a real link with "→" in the first cell; To do lines link to their lists | S |
| D10 | "1981" badge unexplained (hover only) | covered by A4 | — |

### E. Leaders' site

| # | Item | Fix | Size |
|---|---|---|---|
| E1 | Three answers to "what do we act on" | covered by A2 | — |
| E2 | Overview never shows the verdict or how far to trust it (tooltip only) | under each P1 and best bet: the one-line Point of View headline and the evidence word ("Strong") | S |
| E3 | "Moved since 21 Oct · 57" takes 2.5 screens, each "new scores" | the 8 biggest moves first (into P1/P2), "Show all 57"; the reason says what moved ("how big 5 → 7 after 40 new pages"; the API adds a `why`) | M |
| E4 | Leaders' Point of View opens with the commitment box in run-on text, repeated in the Recommendation | headline first; commitments after the five answers as labelled lines (Owner · Next · By · People · Budget); "No owner yet" once; fix "next, Sign …" and ". by" (`components/frontier/items.ts:130`) | S–M |
| E5 | Words don't match the grid (Market Potential, "3 of 3", "H2", a file name) | the priority sentence the admin side writes ("P2 because it arrives mid-term (how soon 6.5) and the prize is big (how big 8)"); "From Tata's technology list, Oct 2026" | S |

### F. Density

| # | Item | Fix | Size |
|---|---|---|---|
| F1 | Technologies: about 740 px of controls before the list | covered by §6 | — |
| F2 | Briefing crossed signs: a wall of text | covered by §3 and §4 | — |
| F3 | Classification counts run together ("TRL 3 1,212" reads "TRL 31,212"); about 6,265 technologies with no level are not shown | each count on its row as a link; add "No level yet: 6,265" | S |
| F4 | Domains: "Other · 1,275 new to review" one at a time | bulk Accept / Merge with selection, as on Technologies (confirm plus Undo) | M |

---

## 11. Performance, memory leaks and scale (points 3 and 9)

### What was measured (23 Oct, live, read-only)

- **`GET /technologies?limit=50`:** 0.68–0.84 s *at any page size, even `limit=1`*, and **3.8 s each with 5 at once**.
  - Each call works out the status of all 10,514 technologies in Python: 379 database round trips, 46k records read, 136 MB of memory at peak.
  - It then filters, sorts and pages the result in Python.
- **`GET /pipeline`:** polled by every open tab every 5 s while anything runs, otherwise every 30 s. Each poll costs 0.19 s (0.8 s with 5 at once).
  - It recomputes the evidence states (one query per assessed technology, 326 today), the Classify backlog (unwinds every page) and Problems.
  - **Problems reads all 5,719 pages (82 MB) on every poll,** because an index is missing.
- **Heavy responses:**
  - `/scoring/runs/{id}` is 6.3 MB, re-fetched every 5 s while an assessment runs.
  - `/scoring/runs` is 3.4 MB.
  - `/changes` is 764 KB, polled every 30 s by every admin tab (twice on Setup pages) just to read one count.
  - `/gates` takes 0.94 s; `/scoring/povs` 0.40 s.
- **Since the API started, it has read 28.8 GB from the database.** The likeliest single cause: assessing re-reads the whole scoring-run record, 1.7 MB at 262 technologies, once per technology (`engine._load`). Cost grows with the square of the run size.
- **Portal:**
  - no `React.memo` anywhere and 3 uses of `useMemo`, so the Technologies table (100–500 rows) re-renders on every keystroke and every poll;
  - 53 files fetch in their own effect, and none cancels a request;
  - 9 different "Show more" implementations;
  - "Select all" on Technologies fires about 105 cost previews at once;
  - the leaders' grid re-places all ~400 labels on every hover.
- **Memory:**
  - **No listener or interval leaks** were found in the portal: all are cleaned up.
  - The real growth: lists that keep appending, polling that never pauses, uncancelled downloads.
  - **API:** 8 zombie Chromium processes (nothing reaps them); a hung browser fetch leaks a thread and a browser; a new model client (with its own connection pool) per Find-evidence call.
- **Already fine:** the portal runs a production build in Docker (`next start`); the findings endpoints page in the database (35–45 ms); module caches are bounded; executors and cursors are closed.

### What breaks first at 10× (about 100k technologies, 60k pages, several admins)

1. **Technologies, `/gates`, `/pipeline`:** about 8 s per list call, about 1.3 GB peak per request, polls overlapping.
2. **The scoring-run record** reaches MongoDB's 16 MB document limit at about 2,400 technologies in one run (`tech_calls`, about 6.5 KB each). Re-reading it per technology becomes about 13 GB per run.
3. **Editions** break at about 16k placements (one document). **Edition Point of View copies** add about 30 MB per edition today, about 300 MB at 10×.
4. **`restamp_all`** rewrites every page and technology *inside* the HTTP request for an edit, merge or alias claim: minutes at 10×.
5. **Everything runs in one process.** The API, crawl parsing, and every job's threads share one process and one GIL. Busy flags and locks are in-process, so a second API worker would break them. Nothing limits model calls across jobs: about 44 can run at once.

### P1: quick wins (S each; together about 2 days)

| # | Change | Where | Expected effect |
|---|---|---|---|
| P1-1 | **Indexes, kept in the seeds:** every index the API needs is listed in one new seed file, `seeds/indexes.json` (collection, fields, options). This covers the 22 created in code today and the new ones. The startup step that loads seeds creates any that are missing, so a fresh install and the live database end up the same. It never drops an index silently; an extra one is reported in the API log. A test checks that the file and the database match. New ones: `technologies{name}` unique, `{"imported.import_id"}`, `{enabled}`, `{doc_count:-1,_id:1}`; `povs{tech_id, composed_at:-1}`, `{composed_at:-1}`; `documents{"analysis_error.at"}` sparse, `{source_id, scraped_at:-1}`, `{technologies_resolved, scraped_at:-1}`, `{mentions}`; `decisions{active, kind, at}`; `assessments{tech_id, created_at:-1}`, a partial on `watch_metrics.crossed` | `seeds/indexes.json` (new), `services/db/bootstrap.py` (reads it instead of a hard-coded list), `tests/test_indexes.py` | Problems: 82 MB scan → index lookup; povs and decisions sorts in the index |
| P1-2 | **Pipeline poll:** cache the response for 3 s across tabs; drop the `tech_ids` list (fetched when an action needs it) | `api/pipeline.py` | N tabs cost one computation |
| P1-3 | **`/changes/count`** and one shared portal store, refreshed on a config change or every 5 min | `api/changes.py`, `lib/changes.ts`, `TopBar.tsx`, `(setup)/layout.tsx` | removes about 3 MB a minute per Setup tab |
| P1-4 | **Scoring-run reads:** `_load` skips `tech_calls` and `gates`; `GET /scoring/runs` excludes `tech_calls`, `gates`, `technologies` | `agent/analyzer/engine.py:390`, `api/scoring_runs.py:60` | 3.4 MB → about 30 KB; ends the quadratic re-reads |
| P1-5 | **Pause polling in hidden tabs;** refresh on return (at most every 5 s) | `lib/pipeline.ts` and the 5 local pollers | idle tabs cost nothing |
| P1-6 | **Technologies table:** memoised `<TechRow>`; search box as its own component; `pickedKey` memoised | `app/admin/technologies/page.tsx` | typing doesn't re-render 100–500 rows |
| P1-7 | **Leaders' grid:** memoise dots, label placement and `frontierOf`; tooltip outside the dots layer; drag throttled to animation frames | `components/frontier/Grid.tsx`, `items.ts`, `app/frontier/page.tsx` | hover stops re-placing 400 labels |
| P1-8 | **Zombie browsers:** `init: true` for the atlas service | `docker-compose.yml` | no zombies |
| P1-9 | **Classify and Find evidence:** after a restart, mark a "running" record as stopped with its reason (as collections and scoring already do) | `app/main.py` lifespan, `agent/classifier/classify.py` | a restart can't block Classify forever |
| P1-10 | **One model client per process and model** | `services/llm/llm.py`, `find_evidence/job.py`, `websearch.py` | no connection pool per call |
| P1-11 | **`useJob`** clears its timer on unmount | `lib/findEvidence.ts` | no fetch after leaving |
| P1-12 | **Crawler robustness** (§2) | `scout/…` | sources finish |

### P2: structure (M each; together about 5–6 days)

| # | Change | Where | Expected effect |
|---|---|---|---|
| P2-1 | **Technologies list in two calls:** `GET /technologies?…&skip&limit=50` returns slim rows (about 15 fields, not 4.4 KB each); `GET /technologies/facets?…` counts, fetched only when filters or search change | `api/technologies.py`, `technologies/page.tsx` | 220 KB → about 40 KB per page |
| P2-2 | **Reuse the status of every technology between requests,** keyed on a cheap "has anything changed" fingerprint (latest technology update, decision, assessment, Point of View, page) with a short time limit | `services/radar_status.py`, `services/evidence.py` | list calls: 0.7 s → well under 0.1 s when nothing changed |
| P2-3 | **One query instead of one per technology** for "new pages since its assessment" | `services/evidence.py:65` | 326 queries → 1 |
| P2-4 | **People's choices grouped once by technology** (`decisions.by_tech`); one `effective.apply_many` | `gates.py`, `editions.py`, `classify_effective.py`, `scoring_runs.py` | removes technologies × decisions loops |
| P2-5 | **Paged assessment run:** `GET /scoring/runs/{id}/rows?skip&limit&sort&fabric&q` plus `GET …/grid`; refresh while running only when a technology finishes, at most every 15 s | `api/scoring_runs.py`, `assessments/[id]/page.tsx` | 6.3 MB every 5 s → about 40 KB when needed |
| P2-6 | **Bulk actions take the filter, not the ids:** "Select all 10,512 matching" → the API resolves the filter; cost preview by filter | `api/technologies.py`, `api/scoring_runs.py` (`/scoring/preview?<filter>`) | 105 parallel previews → 1 |
| P2-7 | **`restamp_all` off the request:** only pages whose links change, run as a background job behind the busy lock; the edit returns at once and says "re-linking pages…" | `services/…restamp`, `api/technologies.py:370,436,456` | edits stay instant at any size |
| P2-8 | **Page counts by aggregation, not Python sets** | `agent/resolver/resolver.py:404-417`, `classify.pending()` | memory flat as pages grow |
| P2-9 | **A hung browser fetch kills its browser** and starts a fresh one | `scout/tools/browser.py:53-71` | no leaked threads or Chromium |
| P2-10 | **Shared portal hooks:** `useApi` (cancel on change or unmount, drop stale responses), `usePaged`/`useClientPage` plus `<Pager>` (§5), `useRefreshOn(key, minMs)` for the ~10 ad-hoc pipeline refreshes, `useAction` for busy/note/error, shared `useLists`/`useEditions` stores | `lib/` | fewer requests; no out-of-order rows; less code |
| P2-11 | **DRY, API:** one `povs.latest(tech_ids)` (written 4 ways today); one "newest visit per page" helper (4 ways); `display_name(t)` (28 copies); `/scoring/povs` paged | `services/` | — |
| P2-12 | **DRY, portal:** one `lib/run-states.ts` (6 status maps); `AXIS_LABELS` once; split the largest files: `import/page.tsx` 912, `PovText.tsx` 852, `runs/[id]/page.tsx` 807, `assessments/[id]` 721, `technologies/page.tsx` 689, `Grid.tsx` 554, `RunSteps.tsx` 531 | `tech-lens` | smaller, readable files |

### P3: scale (L; plan now, build when volumes call for it, decision Q4)

| # | Change | Why |
|---|---|---|
| P3-1 | **Store each technology's status on the technology** (status, state, new pages, effective availability, domain, TRL, evidence, catalog), updated by whoever changes it (assessment, Point of View, decision, Classify, linking) | the list becomes a plain database query with sort, page and counts: constant time at 100k |
| P3-2 | **Move `tech_calls` into its own collection** (`scoring_tech_calls`, one record per technology per run) | removes the 16 MB limit on run size |
| P3-3 | **Edition placements as their own rows;** share unchanged Point of View copies between editions | removes the 16k-placement limit; storage grows with what changed |
| P3-4 | **A worker process** (same image) that takes jobs from a `jobs` collection, with the busy lock in the database; the API only queues | crawl parsing stops slowing the API; the API can run several workers; a restart resumes jobs |
| P3-5 | **One limit on model calls in flight across all jobs,** set to the provider's rate limit | no bursts of about 44 calls; predictable cost and speed |

### How performance is checked

- A read-only `checks/perf.py` (API timings, 1 and 5 concurrent).
- A short browser check: DOM nodes and memory on Technologies, Briefing and Assessment run, at page 1 and after paging 5 times.
- Run before and after each phase, with numbers recorded in the docx entry.

**Targets after P1 and P2:**
- `/technologies` under 100 ms (5 concurrent under 300 ms);
- `/pipeline` under 20 ms when cached;
- Technologies page under 3,000 DOM nodes at any page;
- memory flat after 5 page turns;
- nothing over 100 KB polled.

---

## 12. Order of work

Each phase is deployed, checked (§13), written into the client docx and reported before the next one starts. **Rebuilding the API stops a running job**, so the API is only rebuilt when the pipeline is idle; I check first.

| Phase | Contents | Size |
|---|---|---|
| **1. Correctness and robustness** | §1, §2, A1–A8, P1-1, P1-4, P1-8, P1-9, P1-11, P1-12 | about 2 days |
| **2. Speed without new screens** | P1-2, P1-3, P1-5, P1-6, P1-7, P1-10, P2-2, P2-3, P2-4, P2-9 | about 2–3 days |
| **3. Lists and filters** | §5 (Pager and shared hooks, P2-1, P2-5, P2-6, P2-10), §6, §8 | about 3–4 days |
| **4. Briefing, technology page, path to scale** | §3, §4, §7, §9 | about 3 days |
| **5. Words, phones, feedback** | B1–B5, C1–C13, D1–D9, F3–F4 | about 3 days |
| **6. Leaders' site** | E2–E5 (A2 is in phase 1) | about 1–2 days |
| **7. Clean-up** | P2-7, P2-8, P2-11, P2-12 | about 2 days |
| **Later (Q4)** | P3-1 to P3-5 | about 1–2 weeks |

**About 17–20 working days for phases 1–7.** Phases 1 and 2 give the biggest relief soonest.

## 13. How each phase is checked

- **API tests:** `TEST_MONGO_DB=tech_atlas_test_ux1 uv run pytest -q`, with new tests named in each section.
- **Portal:** `npx tsc --noEmit` and `npx eslint`.
- **Walk:** a first-time-reader walk on live data at 1440 and 400 px (new `checks/plan10-phaseN.py`) asserting:
  - the text a reader sees;
  - no sideways scroll;
  - no page errors;
  - page heights for §4, §6 and §8.
- **Performance:** `checks/perf.py` before and after (§11).
- **Earlier walks** (items 0–40) are re-run, so nothing earlier breaks.
- **Client docx:** a "changes after the midpoint review" entry per phase (changes 41 onward), with before and after screenshots and the measured numbers.

## 14. Decisions needed from you

| # | Question | Answer |
|---|---|---|
| Q1 | Can a person edit a sign's threshold and overrule "crossed"? (§3) | **Agreed.** Signs get their own collection, one record per technology per sign; a person's change is a decision, with Undo |
| Q2 | Briefing findings per page (§4) | **Agreed: 15** on the Briefing; 50 everywhere else |
| Q3 | Removing a path step that technologies have reached (§9) | **Open.** Recommended: refuse with their names and offer "Move them to…"; Proof of concept can't be removed |
| Q4 | When to do P3 (stored status, worker process, call limit) | **Open.** Recommended: after phases 1–7 |
| Q5 | Assess the technologies with new evidence | **Done by you:** run `8f2220f78cf6` for all 71, started 23 Oct 10:01 AM CDT (58 of 71 done when this was written). Their Points of View are then written from the Briefing's To do |
