# Answering the 28 Oct review: design and implementation plan (v1)

This builds what `specification.md` (same folder) says, which Akshay agreed. That document says *what* changes and why. This one says *how*: the design, the files, the order, the tests and the documents.

This file is the master and holds the API contract both apps share. The portal's part is `../../../../../tech-lens/docs/2026-10-31/review-28-oct/v1/implementation-plan.md`.

**Status: waiting for Akshay's approval. No code until then.**

## 0. Design in one page

Every change reuses something the radar already does. Nothing new is built beside it.

| Req | Reuses | New |
|---|---|---|
| R1 Tata's 2×2 | The priority-grid configuration; the Grid component | One shared orientation module in the portal; a config edit |
| R2 Panel behind a dot | The edition's frozen Point of View (it already holds each measure's score and reason); the `hand_score` decision and its form (`ChoiceForm`) | The edition records which measures make each axis (one field); the panel component |
| R3 Add source | The source edit checks; Setup › Changes ("added in the app" already works for sources) | `POST /api/sources`; the edit form made a shared component |
| R4 Sources | R3; switching sources on | Data only |
| R5 Trends | The "digest" connector mode (job boards: one page per saved search per run); the OpenAlex and EPO connectors; the `watch_metrics` skill | Two digest connectors in one module; skill text |
| R6 Use-case size | The `value_levers` skill and its checker; `market.band`; Find evidence (use-case gap) | A `size` field on each use case; bands in config; one table column |

What is **not** added: no new run type, service, collection, job, dependency or side call. The data still enters as pages from sources during a collection; judgement stays in skills; numbers that may change stay in configuration.

---

## 1. R1: the 2×2 as Tata draws it

### Design
- **Configuration.** One edit: `PUT /api/scoring/config/priority_grid`, body `{"grid": {...}}` with Tata's map:

  ```
  near_high P1  near_mid P3  near_low P5
  mid_high  P2  mid_mid  P4  mid_low  P6
  far_high  P2  far_mid  P4  far_low  P6
  ```

  - The existing check (`src/app/api/scoring.py` `_reasons`, the `grid` rule) already validates it.
  - Then **Redo scores** on the latest scoring run (`POST /api/scoring/runs/{id}/recompute`). It is free, with no model calls, and restamps the priorities.
  - Then Setup › Changes → Keep as defaults, so `seeds/scoring_config.json` matches.
  - Its `open_question` is updated in the same edit to "Tata's own map, from its reference radar."
- **Portal** (details in the tech-lens plan):
  - one module `lib/grid.ts` holds the layout: which axis is vertical, the quadrant names and the band order for tables;
  - `Grid.tsx`, both priority tables and the leaders' help text read it;
  - the dot's x is `upOf(item, lens)` (how big, or threat) and its y is `how_soon`;
  - the frontier staircase takes its points as (up, soon);
  - quadrants: top = now (how soon above its upper cut-point), right = bigger;
  - the legend `PRIORITY_LEGEND` in `lib/scoring.tsx` becomes "Priority P1 (act now) to P6 (no action yet)".
- **No backend code change.** Bands, priorities and horizons are computed as before.

### Tests
- **`tests/test_scoring_config.py`**: the seeded priority grid maps each of the nine band pairs to Tata's priority, written as a table in the test.
- **Existing tests that assume the old map** (`test_editions.py`, `test_frontier.py`, `test_edges_preview.py`): their expectations are updated to the new seed, and nothing else changes.

---

## 2. R2: the measures behind a dot

### Design
- **The edition records which measures make each axis.** `services/editions.py` `live()` already reads the `priority_grid` document for the cut-points. It also reads `timeline_from` and `potential_from` and returns:

  ```json
  "grid_from": {"how_soon": ["maturity-trl", "commercial-adoption"], "how_big": ["addressable-market", "growth", "disruption-threat", "serviceable-capture"]}
  ```

  - `publish()` copies every key of `live()` except the rows, so the edition stores it with no further change.
  - `GET /api/frontier` adds `"grid_from"` to the keys it passes through (`api/frontier.py`, the tuple next to `cutpoints`).
  - An edition without it returns `null`, and the panel then lists every measure.
- **The measure details** come from the existing `GET /api/frontier/pov/{tech_id}`: `fabrics[].measures[id]` holds `score`, `state`, `justification`, `counter_case`, `missing`, `model_score`, `reason` and `refs`, and `measures[]` holds the names. Nothing is added to it.
- **Change (admins)** calls the existing `POST /api/decisions` with `{kind: "hand_score", tech_id, fabric_id, measure_id, value, reason}`.
  - For a technology-wide measure the portal sends `fabric_id: null`. The scope comes from the frozen measure list, the same rule the Assessment tab follows (`services/decisions.py:110-121`).
  - Leaders can't call it (`services/auth.py` `LEADER_CALLS`), and the portal doesn't show it to them.
- **Portal**: the panel component and the click change are in the tech-lens plan.

### Tests
- **`tests/test_editions.py`**: a published edition stores `grid_from` equal to the grid configuration at publish time; `GET /api/frontier` returns it.
- **`tests/test_frontier.py`**: an edition document without `grid_from` returns `null`, not an error.
- **`tests/test_decisions.py`**: already covers `hand_score` by scope. A new case checks that the exact body the panel sends for a technology-wide measure (`fabric_id: null`) is accepted, and that one with a fabric for that measure is refused with its reason.

---

## 3. R3: add a source by hand

### API contract
`POST /api/sources`, admins only (the default for every call that isn't on the leaders' list). Body:

```json
{"name": "Converge Digest", "url": "https://convergedigest.com", "horizon": "H1",
 "cluster": "analysts_trade_press", "cost": "free", "enabled": true,
 "access": "crawl",                       // "crawl" | "query"
 "adapter": null,                         // required when access is "query": a REGISTRY name
 "entry_urls": ["https://convergedigest.com/category/optical/"], "follow_outbound": false,
 "searches": null}
```

- **Reply**: the stored source, as `GET /api/sources/{id}` returns it.
- **Refusals** (422 unless shown), each saying why:
  - the id made from the name is taken (409, "A source with the id converge_digest exists: give it another name.");
  - the name makes no id;
  - `query` without a known adapter;
  - `adapter` given for a website;
  - start pages or outbound links on a data source;
  - saved searches on a website;
  - licensed and switched on while paid sources aren't allowed;
  - plus the field rules `SourceEdit` already has (http/https, lengths, horizon, cost).

### Design
- **`src/app/api/sources.py`**:
  - `class SourceNew(SourceEdit)` adds `access: Literal["crawl", "query"]` and `adapter: str | None`.
  - The access checks inside `update_source` move into one function, `_refusal(access, edit, note) -> str | None`. `PUT` and `POST` both call it, so a rule is written once.
  - The licensed rule is part of it. Today no licensed source is switched on (checked on live, 31 Oct), so `PUT` refuses nothing it accepts now.
  - **The id**: `re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]`.
  - **The insert**: `{_id: id, source_id: id, **fields, access, adapter?, updated_at, updated_by}`. Empty lists and an off switch are left out, as `update_source` already does, so the seeding data shows no noise.
- **Setup › Changes and Keep as defaults: no change.** `seeding.py` already lists sources added in the app and appends them to `seeds/sources.json` (`_write_list`, "added in the app").
- **Group choices** come from `GET /api/sources` (the groups in use). No new endpoint.

### Tests (`tests/test_sources_add.py`, new)
- add a website, then add a data source (the reply and the stored document);
- a taken id → 409 with its message;
- start pages on a data source, saved searches on a website, an unknown adapter, and a licensed source switched on → 422 with their messages;
- after an add, the Changes listing shows it as "added", and writing defaults into a temporary copy of the seed folder appends it (the pattern is in `tests/test_seeding.py`);
- `PUT` keeps passing its existing tests, now that the shared check sits underneath.

---

## 4. R6: a ballpark size on each use case

### Data
Each use case in `assessments.use_cases[]` gains `size`:

```json
"size": {"basis": "evidence" | "comparable" | "none",
         "amount_usd_bn": 2.4,          // or null
         "saving_pct": null,            // or a number 0–100 (one of the two, for evidence/comparable)
         "covers": "what the figure covers, in a few words",
         "year": 2025,
         "comparable": null,            // comparable only: the market compared with
         "why_comparable": null,        // comparable only: one sentence
         "page": "<doc id>",            // the cited page (evidence/comparable)
         "reason": null,                // none only: why there is no reliable figure
         "evidence_needed": null}       // none only: what would settle it
```

- The band isn't stored. It is worked out when read, so a change to the band list applies everywhere.

Configuration: a new `scoring_config` document `market_bands`:

```json
{"name": "market_bands", "version": 1,
 "bands": [{"below_usd_bn": 0.1, "label": "under $100M"}, {"below_usd_bn": 1, "label": "$100M–1B"},
           {"below_usd_bn": 10, "label": "$1–10B"}, {"below_usd_bn": 100, "label": "$10–100B"},
           {"below_usd_bn": 1000, "label": "$100B–1T"}, {"below_usd_bn": null, "label": "over $1T"}],
 "open_question": "Hasan's scale (hundreds of millions, billions, trillions); confirm with Tata."}
```

- It is a new setting, so it ships in `seeds/scoring_config.json` with the code. The seeding load adds it.
- After that, edits go through `PUT /api/scoring/config/market_bands`. A `bands` rule in `_reasons` checks: ascending limits, the last one null, a label on each.

### Design
- **`src/app/services/market.py`**:
  - `BANDS` is removed;
  - `band(amount_usd_bn)` reads `market_bands` (one `find_one`) and falls back to the seeded list when the document is missing (a database from before);
  - `market_size()` is unchanged apart from that;
  - a new `use_case_size(size) -> dict | None` returns the stored size plus `band` (or `saving`), for the readers below.
- **`src/agent/analyzer/value.py`**:
  - A new `size(given, cite) -> dict` builds the stored `size` from the answer. It **never raises**. Anything unusable becomes `basis: "none"` with the reason in plain words:
    - "No size was given."
    - "The size cited no page from the evidence."
    - "The size gave no usable figure."
    - "A comparable must say what it is compared with and why."
  - `check().run` adds `"size": size(uc.get("size"), cite)` to each use case.
  - The `MONEY` check stays on the lever chain and the capital note only. The size is its own field, so the regex needs no change.
  - The module docstring gains one paragraph on the size.
- **`src/agent/analyzer/pov.py`**:
  1. **VALUE block** (`_extras`, around line 269):
     - The heading becomes "VALUE, per fabric (cite as [n]; never write a figure other than the ballpark sizes given):".
     - Each use case gains a line `    ballpark size: <band or about N% saving on …> (<covers>, <year>)[n]`. For a comparable: `(comparable: <name>: <why>)`. For none: `    ballpark size: no reliable data: <reason>`.
  2. **`pov_view`**: each `use_cases[]` entry gains `size` (from `market.use_case_size`, refs numbered through `src.docs([page])`). The entries are listed biggest first, then savings, then none, ties by the skill's `rank`. That is a sort key in one place.
- **`src/agent/find_evidence/job.py` `query_for`**:
  - When `gap["kind"] == "use_case"` and `gap.get("key")` names a use case of the latest assessment, `needed = f"{title} market size"`.
  - **`api/find_evidence.py`**: the request model gains `key: str | None = None`, passed into the gap.
  - The re-run is the existing `rerun_use_cases`. The daily budget and the cost preview are unchanged.
- **Skills, edited in the portal** (Setup › Skills, then Changes → Keep as defaults). Exact text in Appendix A:
  - `value_levers` v4 → v5: adds step 6 (the size) and its JSON field;
  - `pov` v11 → v12: one rule on quoting a ballpark size.
  - **Order matters**: the code that reads `size` ships first. It treats a missing size as "No size was given", so the skill edit can follow without a broken run in between.

### Tests
- **`tests/test_value_levers.py`**:
  - each `size` outcome above;
  - a size from the evidence keeps its page id;
  - a comparable needs both its name and the reason;
  - a lever chain with a figure is still refused;
  - a missing `size` is "No size was given."
- **`tests/test_watch_and_market.py`**:
  - `band()` reads `market_bands`, and falls back to the seeded list when that document is absent;
  - the edges: 0.1 is "$100M–1B"; 1000 is "over $1T".
- **`tests/test_pov_view.py`**: use cases carry `size` with numbered refs, sorted biggest first.
- **`tests/test_pov_digest.py`**: the VALUE block prints the size lines and the new heading.
- **`tests/test_find_evidence.py`**: `query_for` with a use-case key gives "<technology> <fabric> <title> market size".
- **`tests/test_scoring_config.py`**: the `market_bands` rule refuses limits out of order and a missing last null.

---

## 5. R5: counts over the last 2–3 years

### Design
- **New module `src/agent/scout/tools/adapters/trends.py`**, with two digest adapters registered in `adapters/__init__.py` `REGISTRY`. Both use the existing digest path in `base.py` (`adapter.digest = True` → `_digest`): one page per saved search per collection, stored and read like any page.
  - The text is stable, with no day or time, so an unchanged count stores a stub, as job boards do.
  - `digest_item(query, last_count) -> (Item, count)` returns this year's count so far as `count`.
  - The page URL is the search's own web address, so a reader can open it, and it is stable per search.
- **`OpenAlexTrends`** (`name = "openalex_trends"`, `kind = "trend"`, no keys; `OPENALEX_API_KEY` is used when set, as now). It reuses `openalex.BASE`, `_words`, `fetch`. For years Y-3 … Y (Y = this year):
  1. `GET /works?filter=title_and_abstract.search:"<words>",from_publication_date:<Y-3>-01-01&group_by=publication_year`: papers per year.
  2. `GET /works?filter=<same>&sort=cited_by_count:desc&per_page=200&select=counts_by_year`: citations per year, summed over these 200 papers.
  3. `GET /works?filter=<same>&group_by=authorships.institutions.country_code`: papers by country. The text lists US, IL, CA, SG and CN first, then the next five.
  4. **Grants started per year**, only if `/awards` supports `group_by=start_year`; build step 5.1 checks this against the live API. The text calls them "public research grants", never venture funding. If the API doesn't support it, this line is left out and the specification is noted.
- **`EpoTrends`** (`name = "epo_trends"`, `kind = "patent-trend"`, `keys = ("EPO_OPS_KEY", "EPO_OPS_SECRET")`). It subclasses `EpoOps` to reuse its token and `_search`. For each year Y-3 … Y:
  - `_search(client, f'({query}) and pd within "{y}0101 {y}1231"', 1, 25)` gives that year's total (`@total-result-count`).
  - For the latest full year, the 25 documents are parsed with `parse_document`, and their applicants are counted by name.
  - That is 4 to 5 calls per search, within EPO's free weekly allowance.
- **One text builder**, `trend_text(heading, lines, source_url)`, used by both, so the two pages read alike:

  ```
  Research activity for "quantum key distribution" (OpenAlex, titles and abstracts)
  Papers per year: 2023: 1,204 · 2024: 1,377 · 2025: 1,512 · 2026 so far (to October): 1,290
  Citations per year to the 200 most-cited of these papers: 2023: … · 2024: … · 2025: … · 2026 so far: …
  Papers by authors' country, 2023–2026: United States 412 · Israel 18 · Canada 61 · Singapore 44 · China 655 · then …
  Source: https://api.openalex.org/works?filter=…
  ```

- **Errors** follow the existing path. A failing search records its error on the source's progress and in the run report (`base.collect`); the other searches go on. An empty result says "No results for this search in these years."
- **Sources** are added through R3 (Section 6): "OpenAlex: trends" (`openalex_trends`, H3, `preprints_journals`) and "EPO: patent trends" (`epo_trends`, H3, `patents`), with the same saved searches as `openalex_works` and `espacenet`. EPO stays off until the keys are set.
- **Skill `watch_metrics` v4 → v5**, edited in the portal. Text in Appendix A. There are no new blanks, because the trend pages arrive in `{evidence}`.
- **Check in build step 5.4.** A trend page must keep its numbers through page reading (`article_summary`) and reach a technology's evidence. Job-board digests already do, so this is expected to hold. If the summary drops the counts, the fix is one sentence in `article_summary` ("keep every count and year on a counts page"), made in the portal. No code.

### Tests (`tests/test_adapters.py`, following its existing recorded-answer pattern)
- **OpenAlex trends**: papers per year, citation sums (two papers with overlapping years), country order (the five named first), and the text and URL;
- **OpenAlex trends, no results**: the "No results" text;
- **EPO trends**: per-year totals; applicants counted from parsed documents; no results (OPS 404) → "No results"; missing keys → "not configured" (the existing `missing_keys`);
- **Both**: the same answers give the same text, so a stub is stored on the second run.

---

## 6. R4: add the sources (data, through the portal)

Everything here goes through the portal or its API on the **live** radar, as admin edits. They are configuration, not data writes by a walk. At the end they are written into the seeding data from Setup › Changes.

1. **Check each new website first, read-only.** Open its start pages with the radar's own fetcher (`fetch_page`, from a one-off script that saves nothing) and record:
   - whether readable text comes back;
   - the pages linked from it;
   - the robots answer.

   A source that gives nothing readable is fixed (another start page) or left off, with the reason in the build notes.
2. **Add through Setup › Sources › Add source (R3)**:

   | Name | Kind | Start pages (to confirm in step 1) | Group | Horizon |
   |---|---|---|---|---|
   | Outshift by Cisco | website | outshift.cisco.com/blog | corporate research | H2 |
   | The Next Platform | website | nextplatform.com | analysts and trade press | H1 |
   | Lightwave | website | lightwaveonline.com (data-center and optical sections) | analysts and trade press | H1 |
   | Converge Digest | website | convergedigest.com | analysts and trade press | H1 |
   | Google DeepMind | website | deepmind.google/research/publications, deepmind.google/discover/blog | corporate research | H3 |
   | Technion | website | its research news page | university labs | H3 |
   | Weizmann Institute | website | its research news page | university labs | H3 |
   | Tel Aviv University | website | its research news page | university labs | H3 |
   | Vector Institute | website | its research news page | university labs | H3 |
   | Mila | website | its research news page | university labs | H3 |
   | University of Waterloo IQC | website | its news page | university labs | H3 |
   | IEEE Standards Association | website | standards.ieee.org news | standards and foundations | H2 |
   | OpenAlex: trends | data source, `openalex_trends` | the same searches as `openalex_works` | preprints and journals | H3 |
   | EPO: patent trends | data source, `epo_trends` | the same searches as `espacenet` | patents | H3 |

3. **Edit**: add `https://arxiv.org/list/cs.LG/recent` to arXiv's start pages.
4. **Switch on**: Fierce Network, MIT CSAIL, Stanford AI Lab, Y Combinator, GitHub, and EPO Open Patent Services once Akshay has put `EPO_OPS_KEY` and `EPO_OPS_SECRET` in `.env`. That needs a restart of `atlas` and `worker` to read them.
5. **Pages per source** 60 → 120 in Setup › Sources › Settings.
6. **Confirm** that no start page or saved search contains a test name (a grep over the sources' JSON). Then Setup › Changes → Keep as defaults. At the end, Changes shows nothing waiting.

---

## 7. Order of work

Each step is built, tested (`uv run pytest` green; `npm run build` and lint green in tech-lens), shown to Akshay where it changes a screen, and then the next starts. Its client documents are updated within the step (Section 9).

| Step | What | Apps | Depends on |
|---|---|---|---|
| 1 | R1: `lib/grid.ts`, Grid, tables, legend, help text; config edit + Redo scores + Keep as defaults; tests | lens, config | — |
| 2 | R2: `grid_from` in `live()` and `/frontier`; the panel; tests | atlas, lens | 1 (same component) |
| 3 | R3: `POST /api/sources`, shared check; the Add source form (the edit form made a component); tests | atlas, lens | — |
| 4 | R6 code: `size` in `value.py`; `market_bands` config and `market.py`; `pov.py` VALUE block and `pov_view`; Find evidence key; the use-case column and line; tests | atlas, lens | — |
| 4b | R6 skills: `value_levers` v5, `pov` v12 in the portal; check one technology's use cases with Find evidence on the scale copy; Keep as defaults | config | 4 |
| 5 | R5 code: `trends.py`, REGISTRY; check the awards grouping (5.1); tests | atlas | 3 (to add the sources) |
| 5b | R5 skill: `watch_metrics` v5 in the portal; one small collection on the **scale copy** with the two trend sources to check that pages arrive and keep their numbers (5.4); Keep as defaults | config | 5 |
| 6 | R4: check the start pages; add, edit and switch on the sources; pages per source 120; Keep as defaults | data | 3, 5 |
| 7 | Client documents and change log (Section 9), screenshots from the running product | docs | 1–6 |
| 8 | The full run (Section 8) | operations | 1–7, and Akshay's go-ahead |
| 9 | Prepare only: a note for Hasan (leader's response parked, export offered, focus list to discuss) and a mapping for Abhishek (Tata's PoV format against ours) | docs | — |

Steps 1, 3 and 4 don't depend on each other.

---

## 8. The full run (after step 7, with Akshay's go-ahead)

1. **Run preview** (Operations): check the sources and pages-per-source budget, and any saved search marked "too broad". Narrow those before starting. The preview shows the estimated model calls and cost, and Akshay confirms it (no silent caps).
2. **Collect**: the whole source list, unattended.
3. **Gate 1**: merge names that are one thing. QRNG's two names ("quantum random number generators" and "… generation") are an expected merge. Ignore the rest, then start scoring.
4. **Score** and write Points of View. Gate 2. Publish an edition.
5. **Test-case report** (read-only, a short page for Akshay). For each of Abhishek's eight cases:
   - found or not;
   - its pages and sources;
   - in the catalog or "New to Tata";
   - its quadrant with Tata's meanings.

   We compare it with the 28 Oct result in the specification (R4 diagnosis) and say what changed and why.
6. **Calibration of PQC and QKD** is its own next piece of work, planned from that report.

---

## 9. Client documents (AGENTS.md; re-render with the scripts listed there)

| Step | Document | Change |
|---|---|---|
| 1 | Product Guide | The 2×2 section: Tata's axes and corners, the P1–P6 meanings, the figure |
|  | Training Manual | The leaders' view and Weights & Grid descriptions, screenshots |
| 2 | Product Guide, Training Manual | The panel behind a dot; Change for admins |
| 3 | Training Manual | "Add a source" (a new short section); Setup › Changes shows it as added |
|  | Product Guide | One line in the sources section |
| 4–4b | Product Guide | Use cases now carry a ballpark size; how comparables and "no reliable data" read; the Market size bands |
|  | Training Manual Part 4 | `value_levers` v5 and `pov` v12 (what each blank is filled with is unchanged); Find evidence on a missing size |
| 5–5b | Training Manual Part 4 | `watch_metrics` v5; the two trend connectors in the sources part |
|  | Technical architecture | `architecture.html` and `architecture()` in `make_classic.py`: the digest connectors |
|  | Business process | Only if a step's wording changes (the Evidence step may name trend pages) |
| every step | Client change log | `docs/2026-10-20/1/make_change_log.py`: one entry per requirement, before and after screenshots |

Rules: plain words; no dates; no counts of configurable things; screenshots from the running product, never pressing a button that changes data.

---

## 10. Risks, and what we do about each

| Risk | What we do |
|---|---|
| A broad saved search is "too broad" | The trend digests count; they don't page through results, so they are never "too broad". The window searches keep their 30-day look-back. |
| OpenAlex or EPO answers slowly or refuses | Each search's error is recorded with its reason, and the others go on (existing behaviour). EPO uses its existing token refresh. |
| A trend page loses its numbers when read | Checked on the scale copy (5b). The fix is skill text (`article_summary`), not code. |
| A new website gives no pages | Checked before the run (6.1). The run report says why if one still gives none. |
| 120 pages per source raises the run's cost | The run preview shows the estimate before starting, and Akshay decides. |
| The new priority map moves many dots | Expected, and the point of the change. "Moved since…" on the leaders' page explains moves. Older editions keep theirs. |
| A skill edit lands before its code | Code ships first (4 before 4b, 5 before 5b) and tolerates a missing new field. |

---

## Appendix A. Skill text changes (made in the portal, then kept)

### `value_levers` v4 → v5
- **Description**: "…and the capital it needs, **and a ballpark size for each use case, from a cited page.** Never writes a figure **in the levers or the capital note.**"
- **System**: "You never write a financial figure **except a use case's ballpark size, and only from a cited page.**"
- **New step 6**, after step 5:

  > 6. Give each use case a ballpark size, in this order of preference:
  >    (a) "evidence": a page states the size of the market this use case addresses, or the saving it brings. Give the figure in US$ billions (0.3 for $300 million) or as a percentage saving, what it covers, its year, and the page's [n].
  >    (b) "comparable": no page sizes this use case, but a page states the size of a comparable market, recent or historical. Name the comparable market, say in one sentence why it is comparable (same buyers, same spend it replaces, same stage), and give its figure, year and page [n] as above.
  >    (c) "none": no page gives either. Say why, and what figure would settle it.
  >    Never give a figure from your own knowledge, and never convert currencies.

- **The rule "never write a figure…"** gains: "(a use case's ballpark size in step 6 is the one exception)".
- **JSON**: each use case gains:

  ```
  "size": {"basis": "evidence|comparable|none", "amount_usd_bn": null, "saving_pct": null, "covers": "", "year": null, "comparable": null, "why_comparable": null, "page": n, "reason": null, "evidence_needed": null}
  ```

### `pov` v11 → v12
- **System, after the rule on market size**:

  > A use case's ballpark size may be quoted as given in VALUE, with its [n]; when it is a comparable, say so and name it ("comparable: the SD-WAN market in 2018"). Never turn a size into a forecast or a share for Tata.

### `watch_metrics` v4 → v5
- **Prompt, before "Then add new metrics…"**:

  > Tata decides when to act from four signs: startup activity; seed and incubator funding; patent filings per year; research papers and citations per year. Use each one the evidence gives — a counts page (papers, citations or patent filings per year) gives its series: put the counts per year in current_value and that page as source. Then add metrics of your own so there are 2 to 4 in all. Never guess a count the evidence doesn't give.

- The JSON shape is unchanged.
