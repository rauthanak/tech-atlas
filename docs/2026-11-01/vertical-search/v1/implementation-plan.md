# Vertical search, and pages per source: design and implementation plan (v1)

This builds what `specification.md` (same folder) says. That document says *what* changes and why. This one says *how*: the design, the files, the order, the tests and the documents.

This file is the master and holds the API contract both apps share. The portal's part is `../../../../../tech-lens/docs/2026-11-01/vertical-search/v1/implementation-plan.md`.

**Status: approved and built on 1 Nov; live; 516 tests pass. Differences from this plan are listed at the end of the master plan.**

## 0. Design in one page

Every change reuses something the radar already has.

| Spec | Reuses | New |
|---|---|---|
| S1 Pages per source | The source edit form and its checks; `page_budget()` (the one place the budget is read); Setup › Changes | One optional field on a source; the run records each source's budget |
| S2 Crawl depth | The level-by-level crawl and its link picking; the crawl settings and their snapshot | Two settings (levels, links per level: Automatic or fixed); the width per level follows the budget left when Automatic; a ceiling the forms show |
| S3 Vertical search | Find evidence (the job, its reading and filing, its re-run, its budget, its panel); the data-source connectors; the trends connectors; the web search | A list of "places" built from the sources; a one-off `top()` search on each listing connector; a site list for the web search; per-place results |
| S4 Write waits for Assess | `busy.reason("scoring")`, already used by Publish; `blockedReason()` in the portal | One server check; one portal rule |
| S5 Plural; Organize's wording | `plural()`; the resolve record's `replace` and `new_pages` | Nothing |
| S6 Publish on Operations | `usePublish()` (the Briefing's panel); publish's existing refusal during Assess | Nothing on the server |

What is **not** added: no new run type, collection, job type, service or dependency. A vertical search is still a Find evidence job. Its pages are still read and filed like any collected page. Judgement stays in skills.

---

## 1. S2: crawl depth and links per level, in Setup

**Settings** (`src/app/api/settings.py`, the crawl settings model, and `seeds/settings.json`):
- `link_depth: int = Field(ge=1, le=20)`, default 8. It replaces `SCRAPE_MAX_DEPTH` in `.env`; `.env` stays as the fallback when the setting is absent, so an older database still works.
- `links_per_level: int | None = Field(default=None, ge=1, le=200)`. `None` means Automatic.
- Both go into the run's crawl-settings snapshot, as `pages_per_source` does.

**Crawl** (`src/agent/scout/tools/crawl.py`):
- `max_depth` is read from the snapshot (`crawl_settings.link_depth`), falling back to `settings.scrape_max_depth`.
- The width per level:
  ```python
  levels_left = max(1, max_depth - depth)
  fixed = crawl_settings.get("links_per_level")
  width = min(remaining, fixed or max(LINK_SELECTION_WIDTH, math.ceil(remaining / levels_left)))
  ```
- `LINK_SELECTION_WIDTH` stays as the fewest links Automatic keeps.

**The ceiling** (one function, `services/crawl_reach.py` or beside `page_budget`): `reach(depth, links) = 1 + depth × links` with a fixed number; unlimited with Automatic. Also `links_needed(budget, depth) = ceil((budget − 1) / depth)`.
- `GET /api/settings/crawl` returns `reach` and `links_needed` for the default budget.
- `GET /api/sources/{id}` returns `reach` and `links_needed` for its own budget, so the forms can word the warning without doing the arithmetic themselves.

**Reports:** `problems.coverage()` already tells "stopped by the page limit" from "stopped by the link depth". Its wording uses the settings' names: "Levels of links to follow" and "Links kept per level".

**Tests** (`tests/test_crawl_robust.py`, `tests/test_settings.py`):
- **Automatic:** a fake site whose levels each offer 50 links, budget 150, depth 8, reaches 150. Today it stops near 121.
- **Fixed 15:** the same site stops at 121, and the source's `reach` is 121 with `links_needed` 19.
- **Depth 2:** the crawl stops after level 2.
- **No setting:** falls back to `.env`.
- The snapshot carries both settings.

## 2. S1: pages per source

**Data.** A source may carry `pages` (a whole number from 1 to 500). If it's absent, the source uses the default. The seeding data writes it only where it's set.

**API** (`src/app/api/sources.py`):
- `SourceEdit.pages: int | None = Field(default=None, ge=0, le=500)`. `0` means "use the default" and clears the field. The form sends 0 for a blank box, the same way `note` is cleared.
- `"pages"` joins the `cleared` keys in `_fields`.
- Add source (`POST /api/sources`) takes it too, through the same model.

**Collection** (`src/agent/scout/tools/collect.py`):
- `page_budget(snapshot, override=None, source=None)` returns `override or source.get("pages") or crawl_settings.pages_per_source`.
- In `collect_source`, each source gets its own context, `dataclasses.replace(ctx, max_pages=page_budget(snapshot, max_pages_override, source))`. The scout's other sources keep theirs.
- `store.start_source` records the budget on the run's source row (`budget`).

**Reports:**
- `problems.coverage()` and the run page judge "stopped by the page limit" against the row's own `budget`, falling back to the run's `crawl_settings` for older runs.
- `GET /api/runs/preview` adds `pages_in_all`, the sum of each website's budget. `pages_per_source` stays.

**Tests** (`tests/test_sources_add.py`, `tests/test_collect_budget.py`, new):
- a source with pages 300 is crawled to 300;
- a blank one uses the default;
- 0 clears it;
- a test run's own limit beats both;
- the preview sums the budgets.

## 3. S4 and S5: Write waits for Assess; the plural

**Server** (`src/app/api/scoring_runs.py`, `compose_all`): if `busy.reason("scoring")` gives a reason, return 409 with it, as `editions.py` does for Publish. Writing a single Point of View from a technology's page is unaffected.

**Portal:** see the portal plan (`blockedReason(p, "pov")`, and the plural form passed to `Progress`).

**Test** (`tests/test_pov_compose_all.py` or the nearest existing file): compose_all during a running scoring run gives 409 with "An assessment run is in progress."

## 4. S3: Find evidence as a vertical search

### 4.1 Places

**New:** `src/app/services/places.py`, about 60 lines. It answers "where can this technology be searched now?" from the sources themselves.

```python
def places() -> list[dict]:
    # [{id, label, kind, source_id?, available, why}]
```

| kind | Built from | id |
|---|---|---|
| `search` | each switched-on listing data source whose connector takes words (OpenAlex papers, grants, Espacenet) | its source_id |
| `counts` | each switched-on digest data source whose connector takes words (OpenAlex trends, EPO trends, USAJOBS) | its source_id |
| `websites` | all switched-on, collectable websites, as one place | `radar_websites` |
| `web` | the web search | `web` |

`available` and `why` reuse checks that already exist:

| Check | Message |
|---|---|
| `adapter.missing_keys()` | "needs EPO_OPS_KEY and EPO_OPS_SECRET (see the Deployment Guide)" |
| the source's `enabled` and its `note` | "switched off: …" |
| `cost == "licensed"` and paid sources not allowed | "licensed: off until Tata gives access" |
| `websearch.configured()`, for `websites` and `web` | "no web search set up" |

Switched-off sources are listed greyed out only when they have a connector, so the panel isn't filled with websites.

### 4.2 Searching each kind of place

**Names.** `names(tech)` returns the label, the name and the aliases: unique, at most 3. Each place is searched once per name. Results are merged by address and cut to *n*.

**`search` places:** a new method on the connector, `Adapter.top(query, n) -> list[Item]`. It makes one request for the *n* best results; it doesn't page through a window.

| Connector | Request |
|---|---|
| `openalex.Works.top` | `title_and_abstract.search`, last 3 years, `sort=cited_by_count:desc`, `per_page=n` |
| `openalex.Awards.top` | `default.search`, `sort=start_date:desc`, `per_page=n` |
| `epo_ops.EpoOps.top` | the same CQL search it uses now, newest first, range 1–*n* |

A connector says whether it takes words with a class flag, `by_name = True` (Works, Awards, EpoOps, OpenAlexTrends, EpoTrends, UsaJobs). The others are shown greyed out as "searched by company, not by a technology's name": SEC EDGAR (company numbers) and JobBoards (company boards). The base `Adapter.top` raises `NotImplementedError`.

**`counts` places:** the existing `digest_item(query, None)` gives one counts page per name. The first name's page is enough; the others are only searched when it finds nothing.

**`websites` place:** `websearch.search(query, n, sites=[...])`.
- `LLM.web_search` passes `allowed_domains` to the web search tool when sites are given.
- The domains are each switched-on website's host.
- If the tool rejects a list that long, it is split into groups of K, one search per group. K is found in the pre-build test (section 6).
- A page found is saved under the radar source whose host it matches.

**`web` place:** as today: `websearch.search(query, n)`, saved under "Web search".

**Query.** From the gap, as today (`query_for`): the technology, the fabric, and what's missing. "Everything about it" is the technology's names alone. For data sources, only the names are used: research and patent search engines match words in titles and abstracts, and gap phrases would narrow them to nothing.

### 4.3 The job

**File:** `src/agent/find_evidence/job.py`. It stays one job.

- The gap gains `places: list[str] | None` and `per_place: int | None` (1 to 50). Absent means every available place and `find_evidence_results` (5). Old jobs read as `["web"]`.
- `_run` loops over the chosen places:
  - a `search` or `counts` place gives Items that already have text, so there's no fetch;
  - a `websites` or `web` place gives addresses, which are fetched as today.
- Every result row gains `place`.
- Reading, saving (`store.save_document` with the place's own source), filing, Can ignore and "not read, because…" are all unchanged.
- The re-run is unchanged: a measure gap re-scores that measure; a use-case gap re-does that fabric's use cases; the technology gap re-runs Classify (one call). Nothing is assessed automatically.
- The job records `places_done: [{place, found, new, filed, set_aside, failed, why}]` for the panel.

### 4.4 The API

**File:** `src/app/api/find_evidence.py`.

`GET /api/find-evidence/preview` takes `places` (comma-separated, optional) and `per_place`, and returns:

```json
{
  "query": "…",
  "names": ["post-quantum cryptography", "pqc"],
  "places": [{"id": "openalex_works", "label": "Research papers", "kind": "search",
              "available": true, "why": null, "chosen": true}],
  "per_place": 5,
  "cost": {"pages": 30, "searches": 4},
  "why_not": null
}
```

- `POST /api/find-evidence` takes the same two fields. It refuses unknown or unavailable places with the place's `why`.
- No daily budget: `searches_today()`, `_why_not()`'s budget check and the setting `find_evidence_daily_budget` are removed (settings model, seeds, the Settings form). `why_not` remains for "no web search set up" and "no place chosen".

### 4.5 Tests (`tests/test_find_evidence_places.py`, new; `tests/test_find_evidence.py`, extended)

- **places:** a missing key, switched off with its note, licensed, and no web search each give `available: false` with the right `why`. A data source without `top()` says so.
- **`Works.top`** asks for most-cited, last three years, `per_page=n` (a fake HTTP client, as the existing connector tests do).
- **A job over two places** files data-source items under their own source, web pages under "Web search", and a radar-website page under that website. Each row carries its place.
- **Names:** two names are both searched, and duplicates are merged.
- **No budget:** a search starts however many were run today.
- **Re-runs:** existing tests stay green.
- **An old job without places** still shows.

## 5. Order

| Step | What | Restart needed |
|---|---|---|
| 1 | S5, S4, S6: plural and Organize's wording; Write waits for Assess; Publish on Operations | yes (portal only for S5/S6) |
| 2 | S2, S1: crawl depth and links per level; pages per source | yes |
| 3 | Tests (all), then deploy steps 1–2 together, only when nothing is running: check first as its own step, then ask Akshay | — |
| 4 | Pre-build tests for S3 (section 6), read-only, nothing stored | no |
| 5 | S3: places, `top()`, the job, the API, then the portal panel | yes |
| 6 | Tests, deploy (same rule as step 3), then a walk on a real technology, read-only except for one Find evidence Akshay agrees to | — |
| 7 | Documents (section 7), then the reply note to Abhishek (section 5 of the notes) is updated from what the walk shows | no |

## 6. Pre-build tests for S3 (read-only)

1. **Web search with a site list.** In the worker, call the Anthropic web search with `allowed_domains` set to all switched-on website hosts, for "post-quantum cryptography".
   - Record: is the list accepted, and how many results come back, from which sites?
   - If it's refused, halve the list until it's accepted. That size is K.
2. **OpenAlex with the key.**
   - Run `Works.top` (as a script, not yet in the code) and the trends query for three names: post-quantum cryptography, quantum key distribution, quantum random number generation.
   - Record the requests made and the allowance OpenAlex reports as used.
3. **Espacenet:** skipped until the EPO keys are set. The place shows greyed out with why.

The results go into this folder as `pre-build-tests.md` before step 5 starts.

## 7. Documents (in the same piece of work)

| Document | What changes |
|---|---|
| Business process, cards and flowchart (`process()` in `make_classic.py`) | Find evidence: "choose where to look" and "per place, how many"; "Write Points of View waits for Assess" as a rule on that step |
| Technical architecture (`architecture.html`, `architecture()`) | Find evidence also reads through the data-source connectors, and the web search can be limited to the radar's websites |
| Product Guide | The two directions (collection across sources; Find evidence down one technology); pages per source |
| Administrator's Training Manual | Find evidence panel (what, where, how many, cost, per-place results); Pages per collection on the source page; Write them waiting for Assess; screenshots retaken read-only |
| Deployment Guide | `SCRAPE_MAX_DEPTH` becomes a fallback only: the depth is now set in Setup › Settings ("Levels of links to follow"). If the web search needs a setting, it goes here too |
| Client change log | A new change number, "Find evidence searches across the radar's sources", and "Pages per source" |
| Seeds | Settings (`find_evidence_daily_budget` removed) and any source with its own pages, through Keep as defaults: Changes 0 |

## 8. As built (1 Nov): where it differs from the plan

- **The ceiling's arithmetic is in the portal** (`tech-lens/lib/crawl.ts`, `readingLine`), not returned by the API: it is two lines of arithmetic, used by the Settings page and the source page.
- **A Find evidence request without places searches the web only**, as before, so older callers keep working. The panel always sends the places it shows, which start as every place that can be searched.
- **The job re-checks only data sources' availability.** The web search was checked when the search started, and if it fails the place says why.
- **No splitting of the website list:** the web search accepted all 123 hosts in one search (`pre-build-tests.md`).
- **A field no seeded item had yet** (a source's `pages`, the crawl's `link_depth` and `links_per_level`) didn't show on Setup › Changes. `seeding.EDITABLE` lists those fields, so they are compared, kept as defaults and put back like any other.
- **The Sources list shows a source's own budget** ("its own budget: 300 pages") but not the amber "can't be reached" note; the source's own page shows that.
- **The daily budget was removed** (Akshay, 1 Nov), as the spec now says.
- **A collection records each source's budget** on its row (`budget`), so the run page judges "reached its page limit" against the source's own number.
