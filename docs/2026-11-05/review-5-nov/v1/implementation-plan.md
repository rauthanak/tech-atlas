# Review of 5 Nov: design and implementation plan (v1)

This builds what `specification.md` (same folder) says. That document says *what* changes and why. This one says *how*: the design, the files, the order, the tests and the documents.

This file is the master and holds the API contract both apps share. The portal's part is `../../../../../tech-lens/docs/2026-11-05/review-5-nov/v1/implementation-plan.md`.

**Status: built and live on 6 Nov; 529 tests pass; Changes 0. Differences from this plan are listed at the end of the master plan.**

## 0. Design in one page

Every change reuses something the radar already has.

| Spec | Reuses | New |
|---|---|---|
| S1 Hand changes at Publish | `decisions` (who, when, tz, reason, undo); `editions.since()` and its one-minute cache; the Publish panel (`usePublish`) | One list in `since()`: `hand_changes` |
| S2 Too early to place | `classify_effective.effective()` (the evidence verdict and reason); `decisions.in_catalog()`; `editions.live()`, `publish()` and `edition_rows`; the "Not placed yet" section; radar settings | A third kind of edition row, `too_early`; one setting; one line in the Wait corner |
| S3 Checked figures | `engine._figure()`, `value.size()`; `page_texts` and the page's `summary_text`; `market.py` | One small module, `services/quotes.py` (find the words on the page, read a dollar amount); `quote` and `cagr_pct` on a figure |
| S4 Industry | The `value_levers` skill and its `check()`; the use-case table | One field on a use case |
| S5 New Point of View parts | The `pov` skill, its section list and its citation numbers (`Sources`); `PovText`'s `Section` and `Fold` | Five keys in `sections`; page summaries in the sources list; a citation check per bullet |

What is **not** added: no new collection (only a new `kind` in `edition_rows`), job, service, endpoint, page, dependency or Setup list. Judgement stays in skills. Every check that guards against made-up content is code.

## API contract (both apps)

| Endpoint | Change |
|---|---|
| `GET /api/editions/since` | `since` gains `hand_changes: HandChange[]` (below), newest first. |
| `GET /api/frontier` | Gains `too_early: TooEarly[]`, all of them whatever the fabric asked for. It's `[]` for editions published before this change, or with the setting off. |
| `GET /api/settings/radar`, `PUT` | Gain `frontier_too_early: bool`. |
| `GET /api/scoring/runs/{run}/pov/{tech}` and the edition's frozen copy | `sections` may hold `customer_need`, `alternatives`, `players`, `risks`, `whats_new` (each `string[]`, may be empty). `fabrics[].measures[...]` and the market size gain `quote`; a new `growth_rate`; `use_cases[].industry`. |
| `GET /api/technologies/{id}/assessment?fabric=` (the value fold) | `use_cases[].industry`, and `size.quote`. |

```ts
type HandChange = {
  decision_id: string; tech_id: string; name: string;
  kind: "hand_score" | "tata_entry" | "override";
  fabric: string | null;            // null: every fabric (a technology-scope measure)
  measure: string | null;           // the measure's name; null for a priority
  before: number | string | null;   // the radar's score, or the priority the scores give; null: none
  after: number | string | null;    // null when undone
  undone: boolean;
  by: { name: string } | null; at: string; tz: string | null; reason: string | null;
  pov_before: boolean;              // its latest Point of View was written before this change
};
type TooEarly = { tech_id: string; name: string; verdict: "thin" | "not_credible"; reason: string | null };
type Quoted = { quote: string | null };   // the page's own words; null on figures stored before this change
type GrowthRate = { cagr_pct: number; from_year: number | null; to_year: number | null; scope: string | null; quote: string; refs: number[] } | { cagr_pct: null } | null;
```

---

## 1. S1: hand changes at Publish (`src/app/services/editions.py`)

**`_hand_changes(since_at)`**, called from `_since_now()`:
- Reads `decisions` with `kind in ("hand_score", "tata_entry", "override")` and either:
  - `at > before.published_at` (made since); or
  - `undone_at > before.published_at` (undone since).

  An inactive record that a newer one replaced (`replaced_at`) is skipped: the newer one is listed.
- For each record:
  - **before:**
    - for `override`, the record's `computed`;
    - for a score, the model's score in the technology's latest assessment for that fabric (`tech_status.latest_assessments()`, the measure's `score` before people's choices). With a technology-scope measure, the first fabric's score, which is the same in every fabric.
    - `tata_entry` has no radar score (`None`).
  - **after:** the record's value, or `None` and `undone: true` when undone since.
  - **who and when:** `by`, and `at` (or `undone_by` and `undone_at`), with their tz.
  - **name, fabric, measure:** from `technologies`, `fabrics` and `measures`, read once each.
  - **pov_before:** `latest_povs.latest([ids], ("composed_at",))` compared with the change's time.
- Switched-off technologies are skipped, as in `live()`.
- Sorted newest first.
- The cache stays as it is: `since()` is worked out at most once a minute, and after any action.

**Tests** (`tests/test_editions.py`):
- A hand score made after an edition is listed with before, after, by and reason.
- One made before the edition isn't listed.
- One undone since is listed as undone.
- A replaced hand score lists only the newer one.
- An override lists its `computed` as before.
- `pov_before` is true when the Point of View is older than the change.
- A switched-off technology isn't listed.

## 2. S2: too early to place

**Setting** (`src/app/api/settings.py`, `seeds/settings.json` → `radar`):
- `frontier_too_early: bool = True` on `RadarSettingsEdit`.
- `radar_settings()` returns `True` when the setting is missing, so older databases behave as the default.

**`editions.live()`** gains `too_early`, worked out only when the setting is on:
- **Who is in the catalog:**
  - every technology with `imported` set or `origin == "imported"`;
  - plus those with an active `catalog` decision `yes`;
  - minus those with `no` (that is `decisions.in_catalog()`, applied to this set).
- Leave out switched-off technologies and any that already have an assessment (`applied`).
- `classify_effective.effective(t, decs, lists)["evidence"]`: keep those whose `verdict` is `thin` or `not_credible`, as `{tech_id, name: display_name(...), verdict, reason}`.
- Sort by name.
- Catalog technologies are a few hundred, so this reads one small query and the decisions for those ids.

**`publish()`**:
- Writes `too_early` rows to `edition_rows` with `kind: "too_early"` and `fabric_id: None`, in the same loop as `placed` and `held` (`for kind in ("placed", "held", "too_early")`).
- `counts.too_early` is added.

**`rows()`** needs no change (it filters by `kind`). `since().now` gains `too_early` for the panel's "Publishing now sends …" sentence.

**`GET /api/frontier`** (`src/app/api/frontier.py`) returns `"too_early": editions.rows(e, "too_early")`, without the fabric filter.

**Tests:**
- A catalog technology with a thin verdict and no assessment is in `too_early`.
- One with an assessment isn't.
- One not in the catalog isn't.
- One a person took out of the catalog isn't.
- One switched off isn't.
- One whose verdict a person changed to enough isn't.
- One not judged yet isn't.
- With the setting off, the list is empty.
- `publish()` freezes the rows, and `/api/frontier` returns them for every fabric.
- An edition from before has `too_early: []`.

## 3. S3: checked figures and the growth rate

**`src/app/services/quotes.py`** (new, small):
- **`norm(s)`:** lowercase; non-breaking spaces and runs of whitespace become one space; curly quotes and dashes become plain ones.
- **`on_page(quote, url=None, doc_id=None) -> bool`:**
  - finds the page: by `doc_id`; or by `page_key = link_key(url)`, the latest visit;
  - reads its full text from `page_texts` when `has_text`, else its `summary_text`;
  - returns whether `norm(quote)` is in `norm(text)`.

  The quote must hold a digit and be at most 300 characters.
- **`usd_bn(quote) -> float | None`:** reads a US-dollar amount ("$312.4 million", "USD 1.2 billion", "US$ 3bn", "$45M") as billions. Any other currency returns `None`.
- **`matches(amount_usd_bn, quote) -> bool`:** `True` when `usd_bn(quote)` is `None`, or within 5% of the amount.

**Scoring** (`src/agent/analyzer/engine.py`):
- `_figure(f, cited)` keeps a figure only when all of these hold:
  - its url is among the cited;
  - `quotes.on_page(f["quote"], url=f["url"])`;
  - either `amount_usd_bn > 0` with `quotes.matches(...)`, or `0 < cagr_pct < 1000` (for growth).
- The stored figure gains `quote`, and `cagr_pct`, `from_year` and `to_year` for a growth rate.
- A dropped figure is recorded on the measure as `figure_dropped: "<why>"` (failures always say why). The measure's score is unaffected, as today.

**Skills and measures (configuration, changed through the API and Setup › Changes, then kept as defaults so the seeds match):**
- **`measure_scoring` prompt:** the `figure` object gains `"quote": "the exact words on the page that state the figure, copied character for character (at most 30 words)"`, and the alternative shape `{"cagr_pct", "from_year", "to_year", "scope", "url", "quote"}` "only when the measure asks for a growth rate".
- **Growth measure `required_evidence`:** add "If a page states this market's growth rate (CAGR), give it as figure, with the page's own words. Never work a rate out from two figures."

**Market** (`src/app/services/market.py`):
- `market_size()` passes `quote` through.
- `growth_rate(measures)` returns the growth measure's figure, `{cagr_pct: None}` when asked and none given, or `None` for assessments from before.

**Use cases** (`src/agent/analyzer/value.py`):
- `size()` requires `quote`.
- `quotes.on_page(quote, doc_id=page)` and `quotes.matches(usd, quote)` must hold, else `none("The size's words weren't found on its page.")`.
- The `value_levers` prompt asks for `quote` on every size.

**Point of View** (`src/agent/analyzer/pov.py`):
- `_size_line` and the market line give the quote too, so the text can quote the page's own words.
- `pov_view()` adds `growth_rate` beside `size`.

**Existing figures without `quote`:** handled as Akshay decides (spec, decision 1).
- **(a):** shown as today until re-assessed.
- **(b):** `market_size()` returns `{band: None, unchecked: true}` for them and the card says "Checked from the next assessment".

**Tests** (`tests/test_quotes.py`, and additions to `tests/test_engine.py` and `tests/test_value.py`):
- The words found in the full text are kept.
- Words found only in the summary are kept.
- Words not on the page are dropped, with a reason.
- A figure from another page is dropped.
- $312 million read as 3.12 billion is dropped (outside 5%).
- An amount in euros is kept (no dollar check).
- A growth rate with its words is kept; one without words is dropped.
- A quote without a digit is dropped.
- Whitespace and curly quotes don't defeat the check.
- A use-case size whose words aren't on its page becomes "none" with why.

## 4. S4: industry on each use case (`src/agent/analyzer/value.py`, `value_levers` prompt)

- **Prompt:** each use case gains `"industry": "one of: <list>"`, with the list from spec decision 3, written in the prompt text so it is edited in Setup › Skills.
- **`check()`:** `industry` is kept when it is a non-empty string of at most 60 characters, else `null`. It is never a reason to ask again. The list isn't enforced in code: the skill text owns it, so Tata can change it in one place.
- **Stored:** on the assessment's `use_cases[]`. Passed through `pov_view()` and `technology_assessment()`.
- **The Point of View's text:** the `value` section may name the industry. No rule change is needed.

**Tests:** an industry is kept; a missing or overlong one becomes `null` without a retry.

## 5. S5: five new Point of View parts (`src/agent/analyzer/pov.py`, `pov` prompt v12)

**Inputs:**
- `Sources.text()` gains each page's `summary_text`, cut to 1,200 characters, under its `[n] source · date · title` line.
- `Sources._add()` reads `summary_text` with the other fields.
- Nothing else is added: the arguments against each score are already in the assessment data.

**Prompt (v12), added to the reply's shape:**
```
"customer_need": ["at most 3: a need that pulls buyers to it, from the pages, ending [n]"],
"alternatives": ["at most 3: another way to solve the same problem and how it differs, as the pages compare them, ending [n]"],
"players": ["at most 5: 'Name: what they do', for companies or groups the pages name as building or offering it, ending [n]"],
"risks": ["at most 3: what could stop it or stop it paying off for Tata, from the arguments against each score and the risks the pages state, ending [n]"],
"whats_new": ["at most 3: 'Mon YYYY: a development', from the newest dated pages, ending [n]"]
```
- **Rules added:** each list may be empty when the pages don't cover it; never fill one from general knowledge; one line per bullet; the existing number rules apply.
- The skill's version goes to 12, through the API, then Setup › Changes "Keep as defaults".

**Checks in code** (`compose_pov`, beside the existing section checks):
- Each of the five keys becomes a list of strings. A non-list becomes `[]`.
- A bullet is kept only if every `[n]` in it is a listed source and it has at least one `[n]`. Dropped bullets are counted in the job's log.
- Each list is trimmed to its maximum (3, or 5 for players).
- `SECTIONS` gains the five keys.

**Stand-in model** (`services/llm/standin.py`): the stand-in reply gains the five keys as `[]`, so tests and dry runs keep working.

**Tests** (`tests/test_pov.py`):
- The five parts are kept with valid citations.
- A bullet without `[n]` is dropped.
- A bullet citing an unlisted number is dropped.
- Six players are trimmed to five.
- A string instead of a list becomes `[]`.
- The sources list carries summaries.
- A Point of View from v11 still renders (keys absent).

## 6. Order of work

Each step is built, tested and shown to Akshay before the next. The client documents are updated as each step lands.

| Step | What | Model calls |
|---|---|---|
| 0 | Pre-build tests (`pre-build-tests.md`), read-only. Akshay decides spec decisions 1–3 | Test 4 only: two Points of View, not saved |
| 1 | S1 hand changes (server + panel) | None |
| 2 | S2 too early (setting, live, publish, frontier, grid, section, pack) | None |
| 3 | S3 checked figures and growth rate (quotes module, scoring, value, market card) | None until a re-assess |
| 4 | S4 industry (skill text, check, label) | None until a re-assess |
| 5 | S5 Point of View parts (skill v12, checks, layout) | None until a rewrite |
| 6 | Full test suite. Deploy with `docker compose up -d --build atlas worker lens`, only after a separate check that nothing is running | None |
| 7 | Bring existing work up to date, per spec decision 2, with the cost shown and Akshay's yes first | Yes |

## 7. Client documents (per `../AGENTS.md`)

| Document | What changes |
|---|---|
| Product Guide | The leaders' view: the "too early to place" line and list. The Point of View: the five parts, Risks under the Recommendation, the page's own words under the market band, and the growth rate. Use cases show their industry |
| Administrator's Training Manual | Publish: the "changed by hand" list and the rewrite prompt. Setup › Sources › Settings: the new switch. Part 4 (skills): `measure_scoring` (quote, growth rate), `value_levers` (industry, quote), `pov` v12 (five parts, page summaries in its sources). Screenshots retaken read-only: Publish panel, leaders' grid and list, Point of View, Market size card |
| Business process (cards and flowchart) | Publish step: "check what was changed by hand, rewrite stale Points of View". Leaders' view: catalog technologies too early to place |
| Technical architecture | No new parts. One line in the data description: an edition also freezes "too early" rows, and figures carry the page's words |
| Deployment Guide | No change: no container, port, setting in `.env` or install step changes |
| Client change log (`docs/2026-10-20/1/make_change_log.py`) | One entry per step, with before and after screenshots |

## 8. Risks and how they are handled

- **The page-words check drops good figures** (the AI paraphrases instead of copying). Pre-build test 1 shows how often the number is on the page. The prompt asks for words copied character for character, and the summary counts as page text. If drops are still high after step 3, we look at the misses before changing anything.
- **Longer Points of View cost more.** Pre-build test 4 measures it on two technologies before step 5 is built.
- **The too-early list grows long** as the catalog grows. It is folded by verdict and lives below the grid, and the grid shows one line only. The setting switches it off.

## 9. As built (6 Nov): results and differences from this plan

**Pre-build tests:**
1. 115 of 116 stored market figures are on their page, so decision 1 is (a): older figures stay shown until re-assessed.
2. No hand changes are active on live, so there was nothing to compare. The Point of View page shows today's scores beside text written earlier, so the "written before this change" note is right.
3. 264 catalog technologies are too early: 250 thin, 14 not credible. Several of the not-credible ones are mature technologies (XDR, Z-Wave, Matter) with no relevant pages, not young ones. The list's wording is about the evidence, not maturity.
4. Two Points of View were written and not saved.
   - Federated learning (38 sources): input 19,452 → 31,649 tokens.
   - Space-based AI computing (5 sources): input 7,906 → 9,626 tokens.
   - Output varies with reasoning (about 9,500 to 22,000 tokens either way).
   - No bullet was dropped, and parts with little evidence said so.

**Differences:**
- The Point of View skill was already at version 12 in the seeds, so this is version 13.
- `figure_checked: true` on every measure scored from now on tells new assessments from old ones. Without it, an old assessment would wrongly say "No page gives a growth rate".
- The dollar check accepts any amount in the words (either end of a range). An amount with no scale ("$5 to 10 billion"'s 5) is ignored.
- The evidence verdict has no person's override in the radar, so "a person's choice included" doesn't apply.
- The edition pack is unchanged: it carries Act now and doesn't show "Not placed yet" either, so it doesn't show "Too early to place".
- The skill and measure texts were changed through the API, then kept as defaults from Setup › Changes (Changes 0).
- Training Manual screenshots aren't retaken yet. The new parts have nothing to show on live until the next Publish (too early to place), a rewrite (the five parts), a re-assessment (page words, growth rate, industry) and a hand change (the Publish list).
