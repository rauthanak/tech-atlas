# Implementation plan 1: signals, wider coverage and one clear process

**App:** tech-atlas (API, agents, data) · **Date:** 2026-10-03 · **Status:** signed off and implemented on 2026-10-03 (see the build notes in §14).
**Companion:** [tech-lens plan](../../../../tech-lens/docs/2026-10-03/1/implementation-plan.md) for the portal. Both apps share the API contract in §7.

---

## 1. Summary

Business feedback asked for three things:

1. **Configurable signals:** signals the radar must never miss, and noise it should always ignore.
2. **More than a few examples:** signals beyond patents, money, papers and backing, read from sources that actually carry them.
3. **A clear process view:** one flow that is easy to follow, not split in two.

This plan delivers them in four phases. Each phase ends with a demo and your sign-off.

| Phase | Workstream | Outcome |
|---|---|---|
| 0 | Foundations | Edits in the app take effect immediately and survive restarts. A Changes tab lists them, and you pick which to write into the seeding data. JSON parsing that copes with wrapped replies. Crawl settings stored in the database. |
| 1 | Signals | A flat, editable signal list applied at the summarizing step. Hits are stored and can be browsed. Stored pages can be re-checked. |
| 2 | Crawler fixes | No page-size cap: large pages are split. Correct start pages and feeds. Subdomains and aggregator links are followed. Editable skip list. |
| 3 | Query sources | Patents, papers, grants, company filings and hiring data from five free APIs. Each saved search keeps its own progress, so nothing is skipped silently. The source register is cleaned up. |
| 4 | Process view, backend part | One endpoint feeds the process strip. Each assessment records which collection runs its evidence came from, so the process view states facts. |

The portal work for each phase is in the tech-lens plan.

## 2. Decisions this plan implements

These come from the 2026-10-03 brainstorm.

1. **Never-miss signals add emphasis; always-ignore rules set qualifying pages aside.** Every page is summarized, tagged and given the scout's take exactly as today. When never-miss signals are present, the reply also names each one with its implication. A page with no signal is summarized exactly as today. It is set aside only when it clearly matches an always-ignore row (decision 5).
2. **One flat list.** A signal is one row: a name, what to look for in plain English (including what counts as significant), *never miss* or *always ignore*, and on/off. There are no categories and no mapping to sources. Every signal applies to every page from every source.
3. **A safety net.** Notable developments that match no row come back as "Other". A recurring one can be promoted to a row with one click in the portal.
4. **Detection happens once, at the summarizing step.** That is the per-page model call that already runs. The signal list is put into its prompt at run time. Scoring does not detect signals; it reads the summaries, which now call signals out.
5. **Never miss beats always ignore.** A page is set aside only when it clearly matches an ignore row and carries no signal. A set-aside page is kept, with the reason, and excluded from technologies and scoring.
6. **Link selection gets the never-miss names.** Every source currently uses up its page budget, so the crawler should prefer links likely to carry signals.
7. **Query sources.** Patents, grants, filings and hiring data come from free official APIs. Their results become documents like crawled pages, so nothing downstream changes. Apify and MCP servers are not used.
8. **No page-size cap.** Pages too big for one call are split, processed in parallel and merged.
9. **The seeding data (the files in `seeds/`) is the configuration in the code; the database holds the live configuration.**
   - An edit in the app takes effect immediately. It doesn't change the seeding data.
   - The Changes tab lists the edits made since the seeding data was loaded. You pick which ones to write into the seeding data ("Update seeding data"), and the next deployment ships with them.
   - The seeding data is loaded into a fresh database, or when it has changed. A plain restart loads nothing, so live edits survive it.
   - Each run records the signal list and crawl settings it used.

These were added after GPT's review on 2026-10-03:

10. **Nothing is skipped silently.** Each saved search remembers how far it actually got, and continues from there in the next run. Any source that runs out of budget says so ("incomplete: 25 still to collect", "page budget reached: 120 links not visited").
11. **Re-check never overlaps with collection or scoring.** A re-check rewrites stored summaries, so nothing that reads or writes them may run at the same time. Collection and scoring may still overlap, as today.
12. **The process view states recorded facts only.** Each assessment records which collection runs its evidence came from. Anything based only on timing is labelled "Latest workspace activity" and never presented as usage.

## 3. Scope

The numbers below match the list agreed on 2026-10-03.

| # | Change | Section |
|---|---|---|
| 1–6 | Signal list, summarizing step, link selection, storage, re-check, signal API | §5.1 |
| 7 | Remove the 12,000-character page cap (split large pages) and the 8,000-character cut in the fabric step | §5.2 C1–C2 |
| 8 | Several start pages per source; RSS feeds as start pages; fix 11 sources | §5.2 C3 |
| 9 | Subdomains count as the same site | §5.2 C4 |
| 10 | Aggregators (Hacker News, Reddit) follow story links one hop | §5.2 C5 |
| 11 | Skip list moves to editable settings, without "careers" | §5.2 C6 |
| 11a | Obey robots.txt wildcard rules. Found while checking the feeds: today's robots.txt reader ignores them. | §5.2 C7 |
| 12–15 | Query sources, five adapters, new sources, register clean-up | §5.3 |
| 16–20 | Process view, backend support: strip endpoint, evidence links | §5.4 and the tech-lens plan |
| 21 | Edits take effect immediately and survive restarts; a Changes tab lists them, and "Update seeding data" writes the ones you pick into the seeding data (to-do #1) | §5.0 F1 |
| 22 | JSON parsing that tolerates ``` wrappers (to-do #2) | §5.0 F2 |
| 24 | Per-search progress and "incomplete" flags, for data sources and for page budgets | §5.3 Q2, §5.2 C8 |
| 25 | Re-check never overlaps with collection or scoring | §5.1 S7 |
| 26 | Evidence recorded per assessment; timing-only information labelled as such | §5.4 P2 |

Out of scope: see §11.

**Ground rules kept:**
- No new agents.
- Adapters live in the scout agent's folder.
- Model calls go only through `app/services/llm`, and database code only through `app/services/db`.
- New settings go into the database. `.env` gains only API keys.
- Nothing this plan touches stays hard-coded.

**Keep it simple** (the user's standing rule):
- Build the simplest thing that works.
- Reuse existing patterns: background jobs like `pov_compose_jobs`, polling like today's pages, one helper per concern.
- Add no abstraction beyond the adapter contract, no options nobody asked for, and no code for hypothetical cases.
- If something here turns out more complex than it looks, stop and ask before building it.

---

## 4. Data model

All changes are additive. Existing fields keep their meaning, and old documents stay valid.

### 4.1 New collections

| Collection | Holds | Seeded from |
|---|---|---|
| `signals` | The signal list, one row per signal | `seeds/signals.json` |
| `settings` | Named settings documents; this plan adds `crawl` | `seeds/settings.json` |
| `recheck_jobs` | Progress of "re-check stored pages" jobs | none |
| `seeding` | One document: when the seeding data was last loaded (`loaded_at`) and a fingerprint of its files (F1) | none |

A `signals` row:

```json
{ "_id": "funding-round", "signal_id": "funding-round", "name": "Funding round",
  "look_for": "A company raises money …", "mode": "never_miss", "enabled": true }
```

- `mode` is `never_miss` or `always_ignore`.
- `_id` is the slug of the name at creation and never changes, so renaming keeps the id.
- The name "Other" is reserved.
- Saving a row sets `updated_at`, as every save in the app does (F1).
- Deleting a row removes it. Past hits keep their stored name.

The `settings` document with `_id: "crawl"`:

```json
{ "_id": "crawl", "name": "crawl",
  "skip_url_patterns": ["login", "signin", "signup", "register", "privacy", "terms", "cookie",
    "mailto:", "javascript:", "/tag/", "/tags/", "/category/", "/author/",
    "facebook.com", "twitter.com", "x.com/", "linkedin.com", "youtube.com", "instagram.com"],
  "page_part_chars": 120000, "page_part_concurrency": 4, "lookback_days": 30 }
```

The skip list is today's hard-coded `SKIP_SUBSTRINGS` (`crawl.py:34`) without `careers`.

### 4.2 Changed collections

| Collection | New fields | Notes |
|---|---|---|
| `sources` | `access` (`crawl` \| `query` \| `none`), `entry_urls`, `follow_outbound`, `adapter`, `searches`, `note`, `progress` | `access: none` means never collected, because the site's terms forbid it or there is no usable access. Such a source cannot be enabled. `progress` is per saved search (§5.3 Q2). It is the app's own note, never part of the seeding data. |
| `documents` | `signals`, `ignored_by`, `signals_hash`, `parts`, `partial` | See below. |
| `runs` | `signal_list`, `signals_hash`, `crawl_settings`, `totals.signals`, `totals.other_signals`, `totals.set_aside`; per source in `sources[]`: `incomplete`, `incomplete_note` | The snapshot the run used, its counts, and which sources didn't finish (§5.2 C8, §5.3 Q2). |
| `assessments` | `evidence_runs` | The collection runs whose pages were actually in the evidence the scorer read (§5.4 P2). |

`prompts`, `fabrics`, `measures` and `scoring_config` need no new fields. Their saves already set `updated_at`, which the Changes tab uses (F1).

A signal hit, stored in `documents.signals`:

```json
{ "signal_id": "funding-round", "name": "Funding round", "label": null,
  "what": "Acme raised a $40M Series B to build …", "who": "Acme; led by Sequoia",
  "when": "2026-09-28", "quote": "the exact sentence from the page",
  "implication": "Capital is moving into … ahead of commercial adoption." }
```

- An "Other" hit has `signal_id: "other"`, and `label` holds the model's short name for the development.
- `documents.ignored_by` is the `signal_id` of the always-ignore row that set the page aside; otherwise null.
- `signals_hash` is the version of the list the page was checked against. Null means never checked.
- `parts` is the number of parts the page was split into, when it was split.
- `partial` is true when one or more parts of a split page failed. Such a page keeps a null `signals_hash`, so the next re-check retries it (C1).

### 4.3 Indexes and registry

- New indexes: `documents.signals.signal_id`, `documents.ignored_by`, `documents.signals_hash`, `sources.access`, `assessments.evidence_runs`. They are created in `bootstrap.ensure_database`.
- Add `signals`, `settings`, `recheck_jobs` and `seeding` to `COLLECTIONS` in `src/app/services/db/mongo.py`.

---

## 5. Changes

### 5.0 Foundations (Phase 0)

**F1. Configuration edits: live at once, listed in Changes, written into the seeding data when you choose (closes to-do #1)**

The seeding data, the files in `seeds/`, is the configuration in the code. The database holds the live configuration. This covers every seeded list: `sources`, `prompts`, `signals`, `settings`, `fabrics`, `measures` and `scoring_config`.

- **Loading the seeding data.** At start, the API loads the seeding data when the database is fresh, or when the seeding data has changed since this database last loaded or wrote it.
  - The time is recorded as `loaded_at` in the `seeding` document, with a fingerprint (SHA-256) of the files.
  - A load makes the configuration exactly match the seeding data. Missing items are added, the seeded fields of existing items are replaced, and items not in the seeding data are removed.
  - Fields the seeding data doesn't have, such as a source's `progress`, are left alone.
  - A plain restart loads nothing, so live edits survive it. The same goes for a deployment that doesn't change the seeding data: edits stay live and stay listed.
- **An edit in the app takes effect immediately.**
  - Every save already sets the item's `updated_at`: sources, prompts and scoring today. The new signal and settings saves do the same.
  - The seeding data is not touched.
- **The Changes tab** (`GET /api/changes`) compares the live configuration with the seeding data:
  - **edited:** the item's `updated_at` is after `loaded_at`, and at least one field the seeding data has differs from it. Each such field is shown with its seeding value and its live value;
  - **added:** the item isn't in the seeding data;
  - **deleted:** the item is in the seeding data but no longer in the database.
  - Only fields the seeding data has are compared, so the app's own notes (progress, counts, `updated_at`) never appear.
  - The `version` counter is the app's own as well, and isn't compared. So an edit changed back to the seeding value drops off the list.
- **Update seeding data** (`POST /api/changes/update-seeding-data`, for the items you tick):
  - **What it writes:**
    - their live values into the `seeds/` files: updated, added or removed;
    - only fields the seeding data has. An added item gets the fields its list uses;
    - `version` along with the item, so the seeding data keeps the current number.
  - **How it writes:**
    - each file keeps its layout (same order, 2-space indent), so git shows only the real change;
    - each file is written to a temporary file and then renamed, so a failed write leaves the file as it was and its changes stay listed;
    - the new fingerprint is recorded, but not a new `loaded_at`, so the next restart doesn't reload.
  - **Afterwards:** the written items match the seeding data and drop off the list. The ones you didn't tick stay live and stay listed.
- **The next deployment** ships with the updated seeding data. Where it loads, edits that weren't written into the seeding data are replaced, as intended.
- **Where the files are written:**
  - In development the API runs from the project folder, so it writes `seeds/` directly.
  - In Docker, `docker-compose.yml` mounts `./seeds` at `/app/seeds` in the `atlas` container, so the files land in the project folder.
  - Pushing to GitHub stays a normal git step.
- **Edits outside the app:**
  - An edit made directly in MongoDB isn't listed; use the app.
  - If the `seeds/` files change outside the app while it runs, for example after a git pull, restart the app to load them.
- **Resetting to the seeding data**, which `seed_scoring.py --replace` did for scoring: delete the `seeding` document and restart.

Implementation:
- New file `src/app/services/db/seeding.py`:
  - `load_if_new()`: the start-up rule above;
  - `changes()`: the comparison for the Changes tab;
  - `update_seeding_data(items)`: writes the ticked items.
- `bootstrap.run()` calls `load_if_new()` instead of today's `seed_if_empty` loop. `signals` and `settings` are added to `ID_FIELDS`.
- New `api/changes.py`, with the two endpoints in §7.
- The API now loads the seeding data itself at start, so `seed_sources.py`, `seed_prompts.py` and `seed_scoring.py` are removed. Their calls go too, from `start.sh`, `start-prod.sh`, `start.ps1` and `docker-entrypoint.sh`. `create_db.py` stays.

**F2. JSON replies tolerant of wrappers, plus shared backoff (closes to-do #2)**

Add two helpers to `src/app/services/llm/llm.py`:

- **`parse_json(reply)`:**
  1. Strip whitespace and ``` or ```json fences.
  2. If parsing still fails, parse from the first `{` or `[` to its matching last `}` or `]`.
  3. Raise `ValueError` if nothing parses.
- **`call_with_backoff(fn, cancelled=None)`:** the retry schedule now inside `engine._ask_json` (5, 15, 30, 60 and 120 s), moved here so it can be shared.

Who uses them:
- `parse_json`: the summarizing step, `resolver._llm_groups`, `engine._ask_json` and `pov.compose_pov`.
- `call_with_backoff`: `engine._ask_json` and the summarizing step.

**F3. Crawl settings in the database**

- The `settings` document `crawl` (fields in §4.1) is read once per run and recorded on the run.
- `GET` and `PUT /api/settings/crawl` read and edit it.
- Validation:
  - `page_part_chars` is at least 20,000;
  - `page_part_concurrency` is 1–16;
  - `lookback_days` is 1–365;
  - patterns are non-empty strings.
- The other `.env` crawl numbers stay in `.env` for now (§11).

### 5.1 Signals (Phase 1)

**S1. The signal list**

`seeds/signals.json` holds the 33 starter rows below, all enabled. The model reads `look_for`.

*Never miss (26)*

| id | Name | Look for |
|---|---|---|
| funding-round | Funding round | A company raises money. Note the stage, the amount and the investors, including corporate venture arms and sovereign or pension funds. Significant: a disclosed amount, or a named top-tier, corporate or sovereign investor. |
| new-fund-or-theme | New fund or investment theme | An investor launches a fund, or publishes a thesis, aimed at an area of technology. |
| acquisition | Acquisition or merger | A company buys or merges with another. Note who, whom, the price if given, and why. |
| ipo | IPO or listing | A technology company lists publicly, or files to. |
| shutdown-or-failed-raise | Shutdown or failed raise | A company closes, cuts back sharply, cancels a product or project, or fails to raise money. |
| government-programme-or-grant | Government programme or grant | Public money for an area or a project: a national mission, a research programme, a grant or an award. Note the funder and the amount. |
| regulation-or-mandate | Regulation or mandate | A law, rule, required standard, deadline or ban that forces or blocks adoption. |
| security-advisory | Security advisory | An official warning, directive or vulnerability notice from a security agency (for example CISA, ENISA or CERT-In) that affects a technology. |
| public-tender | Public tender | A government or public body buying a technology, or inviting bids for it. |
| patent-filing-or-grant | Patent filing or grant | A patent filed or granted in a relevant area, especially by a competitor, a big technology company or a surprising new player, or filed in many countries. |
| research-breakthrough | Research breakthrough | A measurable step forward: a new record, a beaten benchmark, a first demonstration or an independent replication. Incremental results don't count. |
| top-conference-recognition | Top-conference recognition | A paper accepted at, or an award from, a leading venue such as NeurIPS, SIGCOMM, NSDI, USENIX Security, MobiCom or OFC. |
| prototype-or-field-trial | Prototype or field trial | The technology working outside the lab: a demo, pilot or field trial, with the parties named. |
| spin-out | Spin-out | A university or corporate lab spins out a company. |
| standard-milestone | Standard milestone | A standards body starts a work item or working group, adopts a draft, or ratifies or publishes a specification (for example 3GPP, IETF, ETSI, ITU, ISO or NIST). |
| open-source-milestone | Open-source milestone | A project launches, joins a foundation, graduates (for example at CNCF or Apache), or reaches a 1.0 release. |
| alliance-formed | Alliance formed | Companies form a consortium, alliance or industry group around a technology. |
| product-launch | Product launch | A vendor or hyperscaler launches a product or makes it generally available. A preview counts only if customers can use it. |
| competitor-move | Competitor move | A carrier or direct competitor (for example Verizon, AT&T, Cisco or Juniper) launches, prices or invests in a technology, including in earnings calls or filings. |
| named-deployment | Named deployment | A named customer runs the technology in production. |
| partnership | Partnership | Companies team up to build, integrate or sell a technology. |
| price-change | Price change | A price cut or a new pricing model, a sign the technology is becoming a commodity or being pushed to market. |
| market-figure | Market figure | An analyst market size, forecast or survey figure, with its scope and date. |
| hiring-surge-or-new-team | Hiring surge or new team | Many open roles for a skill at a named employer, a sharp rise in such roles, a new team or lab, or a notable hire or departure. |
| employment-trend | Employment trend | Official or reputable data showing that jobs or skills in a field are growing or shrinking. |
| developer-adoption-jump | Developer adoption jump | A sharp rise in downloads, stars, contributors or usage of a technology's tools. |

*Always ignore (7)*

| id | Name | Look for |
|---|---|---|
| single-job-ad | Single job ad | A page that is just one job posting. A hiring surge is still caught as a signal. |
| event-promotion | Event or webinar promotion | Registration pages, agendas, speaker lists and webinar invitations with no new facts. |
| marketing-echo | Marketing echo | A page restating an already-known product or announcement with nothing new. |
| opinion-without-news | Opinion without news | Commentary or thought leadership that reports no new facts. |
| routine-update | Routine update | Patch notes, bug fixes and minor version releases. |
| award-marketing | Award marketing | Companies promoting awards, rankings or badges they received. |
| non-tech-corporate-news | Non-technology corporate news | Culture, CSR, office openings, or executive appointments unrelated to technology. |

**S2. Summarizing step**

- New file `src/agent/scout/tools/summarize.py` replaces the `summarize` closure in `crawl.py`.
- `summarize_page(llm, url, text, snapshot, settings)` returns a dict: `summary`, `technologies`, `scout_take`, `signals`, `ignored_by`, `signals_hash`, `parts` and `partial`.
- **The prompt:** `article_summary` v4, full text in Appendix A.
  - It keeps v3's summary, technologies and scout's-take instructions unchanged.
  - It adds the signal instructions and two placeholders, `{never_miss}` and `{always_ignore}`.
  - The placeholders are filled from the run's snapshot, one line per row: `- Name: look_for`.
- **No text cap** (see C1).
- **The call:** runs through `call_with_backoff`, and its reply is read with `parse_json`. A bad reply gets one retry.

The reply is then normalized by plain code:
- A hit whose name matches an enabled never-miss row (ignoring case) gets that row's `signal_id` and current `name`.
- A hit naming an unknown row becomes "Other", with that name as its `label`. An "Other" hit with no label is dropped.
- A hit with no `quote` is dropped.
- `ignore` must match an always-ignore row; otherwise it is null.
- **If any hit remains, `ignored_by` is null.** Never miss beats ignore.

If the call fails or the reply can't be parsed, the page is kept exactly as today, with "(summary unavailable …)". Its `signals_hash` stays null, so the next re-check retries it.

**S3. Link selection**

- The `link_selection` prompt becomes v2 (Appendix A).
- It gets `{never_miss_names}`, the names only, one per line.
- "careers" is dropped from its skip guidance.
- It still runs only when a level has more links than the remaining budget.

**S4. Run snapshot**

- When a run is created, `store.create_run` reads the enabled signals and the `crawl` settings (`services/signals/snapshot.build`). It stores `signal_list`, `signals_hash` and `crawl_settings` on the run.
- The collect tool reads them once from the run. Edits made during a run apply from the next run.
- `signals_hash` is the first 12 hex characters of SHA-256 over those rows, sorted by id, written as `id|name|look_for|mode`.

**S5. Storage** (`src/app/services/runs/store.py`)

- `save_document` stores the new fields.
- The path for unchanged pages, which saves a "stub" pointing to the earlier copy, also copies `signals`, `ignored_by`, `signals_hash` and `partial` from the previous document. An unchanged page is never paid for twice but still shows its signals.
- `bump_source` counts only new or changed pages. It increments `totals.signals` (never-miss hits), `totals.other_signals` and `totals.set_aside` on the run, so "signals in this run" means signals that are new in this run.
- Query items skip the 200-character minimum that crawled pages have (`MIN_TEXT_CHARS`).

**S6. Set-aside pages leave technologies and scoring** (`src/agent/resolver/resolver.py`)

- When gathering raw technology strings, the resolver skips documents with `ignored_by` set. A missing field counts as null, so old documents are unaffected.
- `_stamp_documents` gives those documents `technologies_resolved: []`. The evidence for scoring, the counts and the Technologies page then never include them. Their own `technologies` field is kept, so the decision can be audited.
- `restamp_all` follows the same rule.

**S7. Re-check stored pages**

New file `src/app/services/signals/recheck.py`. It re-runs the summarizing step on stored pages so they match the current list. This is also how existing pages get their signals.

- **Targets:** documents that are not stubs, still have their text and have a `signals_hash` different from the current one. Older versions whose text was pruned are skipped; the newest version of every page always keeps its text.
- **How it runs:** as a background job tracked in `recheck_jobs` (status, total, done, failed, heartbeat), `scout_concurrency` pages at a time.
- **Each page:** replace `summary_text`, `technologies`, `scout_take`, `signals`, `ignored_by`, `signals_hash`, `parts` and `partial`. Then copy the same fields onto the stubs that point to it (`ref_doc_id`).
- **A page whose new analysis fails** keeps its stored summary and stays stale, so the next re-check retries it.
- **At the end:** run an incremental resolve (`run_resolve_sync`), so technologies and set-aside exclusions are up to date.
- **Never at the same time as collection or scoring:** a re-check rewrites stored summaries, so:
  - a re-check can't start while a collection run or a scoring run is active;
  - a collection run, a scoring run and a scoring resume can't start while a re-check is active.

  Each refusal is a 409 whose message names what is running, and the portal disables the button with that reason. Collection and scoring may still overlap, as today, because collecting only adds pages. No revision system is needed.
- **Restarts:** at boot, jobs that were running are marked `interrupted` (`recheck.reconcile_stale()`, called from the `main.py` lifespan). Pages already done keep the new hash, so the next re-check does only the rest.
- **Cost:** one model call per page; a split page costs one per part plus one to merge. The portal shows the page count before you start.

**S8. Prompt safety**

- Today the Skills editor can save a prompt that drops a `{placeholder}` or adds an unknown one, and the stage then breaks at run time.
- After this change, `PUT /api/prompts/{name}` returns 422 when a prompt's placeholders differ from the expected set for that prompt.
- The expected sets live in `EXPECTED_VARIABLES` in `api/prompts.py`. For example, `article_summary` expects `url`, `text`, `never_miss` and `always_ignore`.
- The error message names what is missing or unknown.

**S9. Signal API:** see §7.

### 5.2 Crawler fixes (Phase 2)

**C1. No page-size cap; large pages are split**

- Remove `text[:12000]` (`crawl.py:179`).
- Pages up to `page_part_chars` are handled exactly as today, with one call.
- **Longer pages** are split on paragraph boundaries into parts of at most that size. The parts are summarized in parallel, `page_part_concurrency` at a time, with the same prompt. Then:
  - **Summary and scout's take:** one more call with the same prompt over the joined part summaries. If it fails, use the joined part summaries and the first part's take.
  - **Technologies:** the union of all parts.
  - **Signals:** the union of all parts' hits, with duplicates (same signal and quote) removed. Quotes stay exact.
  - **Set aside:** only when no part has a hit and every part names the same ignore row.
  - **A part that fails,** after its one retry:
    - the page keeps what the other parts produced and is marked `partial: true` ("partly analysed");
    - its `signals_hash` stays null, so the next re-check retries the whole page;
    - it is never set aside, because the missing part might hold a signal.
  - **If every part fails,** the page is stored as today, with "(summary unavailable …)".
- The document records `parts`.

**C2. The fabric step reads the whole evidence**

- `engine._relevant_fabrics` passes the full evidence file instead of `dossier[:8000]` (`engine.py:205`).
- The evidence file is already bounded by the `evidence` setting.

**C3. Several start pages per source; feeds as start pages**

- The crawl starts from `entry_urls` when they are set, otherwise from `url`.
- At depth 0, a start page that is an RSS or Atom feed is read as a feed. It is recognised by its content type, or by `<rss`, `<feed` or `<rdf` at the top. Its item links join the next level. The feed itself is not stored and does not use the page budget.
- Seed the 11 sources whose start pages were dropped from the original register. The exact values come from `artifacts/Sources/tcl_radar_sources.json`; all are https.

| source_id | entry_urls |
|---|---|
| arxiv | arxiv.org/list/cs.NI/recent · arxiv.org/list/cs.CR/recent · arxiv.org/list/cs.DC/recent · arxiv.org/list/eess.SP/recent |
| ietf | datatracker.ietf.org/doc/recent |
| 3gpp | www.3gpp.org/dynareport/WI-List · www.3gpp.org/ftp/Specs |
| apache | incubator.apache.org/projects |
| google_research | research.google/blog/rss |
| rcr_wireless | www.rcrwireless.com/feed |
| a16z | a16z.com/feed |
| nature | www.nature.com/nature.rss |
| science | www.science.org/rss/news_current.xml |
| pnas | www.pnas.org/rss/current.xml |
| berkeley_bair | bair.berkeley.edu/blog/feed.xml |

**C4. Subdomains count as the same site**

- A source's sites are the host of its `url` and the hosts of its `entry_urls`, each with a leading `www.` removed.
- A link is on the same site when its host, without `www.`, equals one of those sites or ends with `.` plus the site.
- So `www.ietf.org` now covers `datatracker.ietf.org`, while `blogs.cisco.com` still doesn't wander into `www.cisco.com`.
- robots.txt is fetched per host and cached for the crawl.

**C5. Aggregators follow story links one hop**

- New source flag: `follow_outbound`.
- When it is true, links to other sites join the next level as *leaf* pages: they are fetched, summarized and stored, but their own links are not followed.
- These links still go through the skip patterns, the file-type filter and that host's robots.txt. They share the source's page budget.
- Seeded true for `hacker_news`, `reddit_ml`, `reddit_networking`, `reddit_netsec` and `reddit_cloud`.

**C6. Skip list in settings**

- `_crawlable` reads `skip_url_patterns` from the run's crawl settings instead of `SKIP_SUBSTRINGS`.
- File-type filtering (`SKIP_EXTENSIONS`) stays in code; it is technical, not a choice.
- "careers" is no longer skipped. A single job-ad page is set aside by the "Single job ad" row, while hiring surges are still caught.

**C7. Obey robots.txt wildcard rules**

- **The problem:** Python's `urllib.robotparser` doesn't understand `*` or `$` inside a rule. A rule like Inc42's `Disallow: /*?*` is effectively ignored, so today the crawler may fetch pages a site forbids.
- **The fix:** parse robots.txt with `protego`, the small, well-tested parser Scrapy uses.
  - Keep today's behaviour of fetching robots.txt with our own User-Agent.
  - Keep failing open when robots.txt is unreachable.
- **Dependency:** add `protego` to `requirements.txt` and `pyproject.toml`.

**C8. Say when the page budget runs out**

- A crawl leaves links unvisited for lack of budget in two ways:
  - link selection keeps at most 15 links per level (`LINK_SELECTION_WIDTH`), fewer when less budget remains, and drops the rest;
  - the budget runs out while links are still queued.
- Both are counted, each URL once. When the total is above zero, the source's row in the run gets `incomplete: true` and `incomplete_note: "page budget reached: 120 links not visited"`, or just "120 links not visited" when the page budget itself was not reached.
- Links left out by the skip patterns, the file-type filter or robots.txt are deliberate and not counted.
- Nothing else changes. You decide whether to raise `MAX_PAGES_PER_SOURCE`, add start pages or tighten the skip patterns.

### 5.3 Query sources (Phase 3)

**Q1. Three ways to treat a source**

| `access` | Meaning |
|---|---|
| `crawl` | Default; today's behaviour. |
| `query` | An API answers the source's saved searches. |
| `none` | Never collected. The record stays for reference, with a `note` explaining why. |

- Query sources also have `adapter` (which API) and `searches` (saved searches, one string each).
- Each adapter has its own search format, documented in §5.3 Q3 and returned by `GET /api/sources/adapters` so the portal can show help.

**Q2. One collect tool**

- The scout tool `crawl_source(url)` becomes `collect_source(source_id)`, in the new file `src/agent/scout/tools/collect.py`.
- It takes the source *id* instead of the URL, so two sources sharing a URL can no longer collide. Today `cbinsights` and `cbinsights_research` share one.
- It looks up the source and acts on its `access`:
  - `crawl`: runs the crawler (`crawl.py`).
  - `query`: runs the adapter.
  - `none`: returns an error string. Supervisors already filter these sources out.
- The `scout` prompt becomes v2 (Appendix A): it lists `source_id: name (url)` and names the new tool.
- The scout's sweep for skipped sources calls `collect_source(source_id)`.
- Every result follows the same path as a crawled page: `store.save_document`, then `summarize_page`, then signals. Duplicates are handled as today: the same URL with the same content becomes a stub, with no model call.

The adapter contract. Each adapter is one module in `src/agent/scout/tools/adapters/`, registered by name in `__init__.py`; shared pieces live in `base.py`.

```python
@dataclass
class Item:
    url: str                    # stable and unique per item (the dedupe key)
    title: str
    text: str                   # what the summarizing step reads
    published_date: str | None
    kind: str                   # patent | paper | grant | filing | jobs-digest

class NotConfigured(Exception): ...   # a key is missing

def search(source: dict, query: str, since: date, limit: int) -> list[Item]: ...
```

- **`limit` per search:** the run's page budget divided by the number of searches, and at least 1. Digest adapters return one item per search.
- **Progress is kept per saved search, so nothing is skipped silently.** Each search has its own entry in the source's `progress` list:
  ```json
  [ { "search": "post-quantum cryptography", "through": "2026-09-14", "remaining": 25, "too_broad": false, "checked_at": "…", "last_count": null } ]
  ```
  - **The window** for a search runs from its `through` date to today, or from today minus `lookback_days` the first time. Both ends are included.
  - **Each run reads the window's results,** page by page, and skips those already collected (the usual duplicate check by URL).
    - Results already collected don't count toward `limit`.
    - Of the new ones, it takes up to `limit`, oldest first.
    - So however many results share a date, none can hold a search back.
  - **`remaining`** is the number of new results in the window that weren't taken. When it is above zero, the source's row in the run gets `incomplete: true` and a note such as "25 still to collect (post-quantum cryptography: 25)". The Sources page shows it too.
  - **`through` moves to today only when nothing is left to collect in the window.** Until then, the next run reads the same window again and skips what it already has.
  - **At most 2,000 results are read per search and run,** which is EPO's limit per query. A window holding more is marked `too_broad`, and the note says "too broad: narrow the search". The run still takes what it can.
  - **Digest adapters** (job boards, USAJOBS) take a fresh snapshot each run, so they have no backlog. They keep only `checked_at` and `last_count`, the previous count used for the comparison.
  - **An error** leaves `through` unchanged, so the window is read again next run.
- **Example:** the EPO search "post-quantum cryptography" has 30 new patents in its window, and the cap is 5.
  - This run takes 5, and the source shows "25 still to collect".
  - Each later run skips the patents it already has and takes the next 5.
  - Once all 30 are in, `through` moves to that day.
  - If the backlog keeps growing, raise the budget or narrow the search.
- **A missing key:** the adapter raises `NotConfigured`. The source row then shows, for example, "not configured: set EPO_OPS_KEY and EPO_OPS_SECRET in .env", and the run continues.
- **Errors and rate limits:** these use `call_with_backoff`. A failing source never fails the run.

**Q3. Five adapters**

| Adapter | Source | Search format | Each item | Key |
|---|---|---|---|---|
| `epo_ops` | `espacenet`, renamed "EPO Open Patent Services" | CQL over title and abstract, e.g. `ta="quantum key distribution"`. The adapter adds the publication-date window. | One patent: title, abstract, applicants, CPC classes, dates. Links to Espacenet. | `EPO_OPS_KEY` + `EPO_OPS_SECRET` (free registration, no ID check) |
| `openalex_works` | `openalex_works` (new) | Plain words matched in title and abstract, e.g. `quantum networking` | One paper: title, abstract, venue, authors and institutions, date. DOI link. | `OPENALEX_API_KEY` (free; recommended, because without it the daily budget is a tenth) |
| `openalex_awards` | `openalex_grants` (new) | Plain words | One grant: title, description, funder, amount, dates | Same |
| `sec_edgar` | `sec_edgar_filings` (new) | `CIK Name`, e.g. `0000732712 Verizon` | One filing as text: an 8-K with its EX-99 press-release exhibit, a 10-Q or a 10-K. Also a Form D, for companies that file one. Links to the filing index. | None; `CONTACT_EMAIL` goes in the User-Agent, as SEC requires |
| `job_boards` | `job_boards` (new) | `greenhouse:<board>`, `lever:<company>` or `ashby:<board>` | One digest per company: open roles now against the last run, roles by department, all titles | None |
| `usajobs` | `usajobs` (new) | A keyword, e.g. `post-quantum cryptography` | One digest per keyword: open federal postings now against the last run, top agencies, titles | `USAJOBS_API_KEY` + `CONTACT_EMAIL` |

The job adapters produce digests because a single posting is a job ad, which is set aside by design. The signal is the count and how it changes, so each produces one summary page per company or keyword per run, including the previous run's count (kept in `progress[search].last_count`). The digest URL is stable, so an unchanged digest becomes a stub and costs no model call.

Endpoint details, checked live on 2026-10-03, are in Appendix C.

**Build order:**
1. `openalex_works` goes first, end to end, because it needs no key. It proves the shared path: the collect tool, the adapter contract, progress, documents, summaries and signals.
2. The other four adapters follow on that same path.

**Q4. Register changes (`seeds/sources.json`)**

*New sources.* All are seeded **disabled**; you switch them on.

| source_id | Name | Horizon · cluster | Access | Starter searches or feed |
|---|---|---|---|---|
| openalex_works | OpenAlex: papers | H3 · preprints_journals | query · `openalex_works` | The 8 topics below |
| openalex_grants | OpenAlex: grants | H3 · government_funding | query · `openalex_awards` | The 8 topics below |
| sec_edgar_filings | SEC EDGAR: company filings | H1 · company_filings | query · `sec_edgar` | Verizon, AT&T, Cisco, Lumen (CIKs in Appendix C) |
| job_boards | Company job boards | H2 · talent | query · `job_boards` | 13 verified boards (Appendix C.5) |
| usajobs | USAJOBS | H2 · talent | query · `usajobs` | quantum · post-quantum cryptography · 5G · optical networking · artificial intelligence · zero trust · satellite communications |
| nsf_news | NSF news | H3 · government_funding | crawl (feed) | Appendix C.1 |
| techcrunch_venture | TechCrunch: venture | H2 · vc_startup_developer | crawl (feed) | Appendix C.1 |
| inc42 | Inc42: funding round-up | H2 · vc_startup_developer | crawl (feed) | Appendix C.1 |
| entrackr | Entrackr | H2 · vc_startup_developer | crawl (feed) | Appendix C.1 |

- **Funding-news feeds:** the last three are free, and two are Indian. They are an addition, to close the "no free funding database" gap; drop them if you prefer.
- **PIB India:** agreed earlier, but dropped after checking (Appendix C.1).

*The 8 starter topics*, shared by EPO and OpenAlex and editable:
1. quantum key distribution
2. post-quantum cryptography
3. coherent optical networks
4. network slicing
5. LEO satellite broadband
6. zero trust network access
7. edge AI inference
8. network digital twin

EPO gets each topic as a title-and-abstract CQL search.

*Changed sources:*

| source_id | Change |
|---|---|
| espacenet | `access: query`, `adapter: epo_ops`, name "EPO Open Patent Services", 8 searches |
| uspto_ppubs | `access: none`. Note: "Web search only; sign-in required from 7 Nov 2026; automated use is blocked." |
| uspto_odp | `access: none`. Note: "Free API, but the key needs an ID.me identity check; adapter not built yet. EPO covers US patents." |
| wipo_patentscope | `access: none`. Note: "Terms ban automated queries; the API is paid." |
| crunchbase | `access: none`. Note: "Terms ban scraping; no free API." |
| nsf_awards | `access: none`. Note: "Search tool; NSF grants arrive through OpenAlex grants." |
| cordis | `access: none`. Note: "Bulk files only; EU grants arrive through OpenAlex grants." |
| darpa, ukri, jst, dfg | `entry_urls` set to their official feeds (Appendix C.1). JST and DFG are partly in Japanese or German; the summarizing step already translates. |
| the 11 sources in C3 | `entry_urls` as listed |
| hacker_news, reddit_ml, reddit_networking, reddit_netsec, reddit_cloud | `follow_outbound: true` |
| every other source | `access: crawl` |

Paid sources (PitchBook, Dealroom, Tracxn, CB Insights, Gartner and so on) are unchanged. They are still skipped while `INCLUDE_PAID_SOURCES=false`.

**Q5. Keys**

- `.env.example` gains:
  - `CONTACT_EMAIL`: sent in the User-Agent to SEC, and as the USAJOBS user (the email its key was registered with). The crawler's own User-Agent stays without an email (Appendix C.7).
  - `EPO_OPS_KEY` and `EPO_OPS_SECRET`;
  - `OPENALEX_API_KEY` (optional);
  - `USAJOBS_API_KEY`.
- `settings.py` reads them.
- The README gets one short section on how to get each key. All are free.

### 5.4 Process view, backend part (Phase 4)

**P1. One endpoint for the process strip:** `GET /api/pipeline` (§7) returns the state of all five steps in one call.

**P2. Evidence links: recorded facts, not timing**

A scoring run uses a collection run's pages only if they mention a technology it actually assessed. So timing proves nothing, and the link is recorded where it happens.

- **Recorded at assessment time:**
  - `engine.build_dossier` also returns the `run_id`s of the pages it actually put into the evidence, after removing duplicates and applying the size guard.
  - `assess_technology` stores them, distinct and sorted, on each assessment as `evidence_runs`.
  - This is a fact: those runs' pages were in the evidence the scorer read.
- **`GET /api/runs/{id}` adds:**
  - **`used_in`:** the assessments whose `evidence_runs` contain this run, grouped by scoring run (its id, status, start time and number of technologies), plus the number of Points of View built from them. A Point of View already stores its `assessment_ids`.
  - **`latest_activity`:** the latest scoring run and its start time. This is timing only, and the portal must label it "Latest workspace activity".
  - **this run's signal totals.**
- **`GET /api/pipeline`** reports `assess.new_evidence`: a collection run completed after the latest scoring run started. It is a statement about timing ("new evidence since the last assessment"), not about use.
- **Older data:** assessments made before this change have no `evidence_runs`, so the portal says "not recorded for assessments before this upgrade".
- No new collection and no revision system: one field on assessments, and one index.

---

## 6. Prompts

The full texts are in Appendix A.

| Prompt | Version | Change |
|---|---|---|
| article_summary | v3 → v4 | Adds the signal instructions, `{never_miss}` and `{always_ignore}`. The output gains `signals` and `ignore`. |
| link_selection | v1 → v2 | Adds `{never_miss_names}`; drops "careers" from the skip guidance. |
| scout | v1 → v2 | The tool becomes `collect_source(source_id)`; covers data sources. |

All other prompts are unchanged. These three roll out when the seeding data loads at the upgrade (F1). Neither database has edited prompts today.

---

## 7. API contract (shared with tech-lens)

**New endpoints**

| Method and path | Purpose | Input | Returns |
|---|---|---|---|
| GET /api/signals | The list, with counts | none | `{signals: [row + hits_total + hits_last_run], current_hash, stale_pages, recheck: job \| null}` |
| POST /api/signals | Add a row | `{name, look_for, mode, enabled}` | 201 with the row. 409 if a row with that name already exists. 422 for the name "Other". |
| PUT /api/signals/{id} | Edit a row | Same as POST | The row |
| DELETE /api/signals/{id} | Delete a row | none | `{deleted}`. The row is removed, and Changes lists it as deleted until the seeding data is updated. Past hits keep their name. |
| GET /api/signals/found | Feed of hits | `signal_id, tech, source_id, run_id, since, limit (≤100), skip` | `{hits: [{doc_id, url, title, source_id, run_id, scraped_at, technologies, …hit}], total}` |
| GET /api/signals/other | "Other" hits grouped by label | `limit` | `{groups: [{label, count, examples: [{what, url, doc_id, scraped_at}]}]}` |
| GET /api/signals/set-aside | Set-aside pages | `run_id, limit, skip` | `{pages: [{doc_id, url, title, source_id, ignored_by, rule_name, summary_text, scraped_at}], total}` |
| POST /api/signals/recheck | Start a re-check | none | 202 `{job_id, total}`. 409 while a collection run, a scoring run or another re-check is active, or when there is nothing to re-check. The message names the reason. |
| GET /api/settings/crawl | Crawl settings | none | The document |
| PUT /api/settings/crawl | Edit crawl settings | `{skip_url_patterns, page_part_chars, page_part_concurrency, lookback_days}` | The document |
| GET /api/sources/adapters | Adapter help | none | `[{name, label, search_help, example, keys: [..], configured: bool}]` |
| GET /api/changes | Edits that aren't in the seeding data (F1) | none | `{count, loaded_at, items: [{collection, id, label, kind: added\|edited\|deleted, updated_at, fields: [{field, seeding_value, live_value}]}]}`. `updated_at` is null for deleted items. |
| POST /api/changes/update-seeding-data | Write the ticked edits into the seeding data | `{items: [{collection, id}]}` | `{written: n, files: [..]}`. Items that no longer differ are skipped. If a file can't be written: 500 naming it. That file is unchanged, and its edits stay listed. |
| GET /api/pipeline | The process strip | none | See below |

**Rules for the hit lists**
- The hit feed and counts exclude stubs, so each page appears once. Newest first.
- Names are joined from the current list by `signal_id`, falling back to the stored name if the row was deleted.
- "Other" groups are keyed by label, ignoring case.

**Changed endpoints**

| Endpoint | Change |
|---|---|
| GET /api/sources, GET /api/sources/{id} | Include `access`, `entry_urls`, `follow_outbound`, `adapter`, `searches`, `note` and `progress` (per saved search: `through`, `remaining`, `too_broad`, `checked_at`) |
| PUT /api/sources/{id} | Also accepts `entry_urls` and `follow_outbound` (website sources only) and `searches` (data sources only); 422 otherwise. 422 when enabling an `access: none` source. `access` and `adapter` are read-only. Removing a saved search also removes its `progress`. An empty list or an off switch is stored as absent, as the seeding data writes it, so saving a form unchanged never shows up in Changes. |
| PUT /api/prompts/{name} | 422 when the placeholders differ from the expected set |
| POST /api/runs | 409 while a re-check is running |
| POST /api/scoring/runs, POST /api/scoring/runs/{id}/resume | 409 while a re-check is running |
| GET /api/runs and /api/runs/{id} | `totals` include `signals`, `other_signals` and `set_aside`. Each entry in `sources[]` includes `incomplete` and `incomplete_note`. `/{id}` adds `used_in`, `latest_activity` and `assessments_before_upgrade` (the count of assessments without `evidence_runs`) (§5.4 P2). |
| GET /api/runs/{id}/documents | Documents include `signals`, `ignored_by`, `parts` and `partial` |
| GET /api/scoring/runs/{id}, …/assessments/{aid} | Assessments include `evidence_runs` |

**`GET /api/pipeline` response**

```json
{
  "collect":      {"status": "none|running|terminating|completed|terminated", "run_id": "…", "stage": "crawling",
                   "started_at": "…", "finished_at": "…", "sources": 6, "pages": 240, "documents": 240, "new_documents": 37,
                   "incomplete": 2},
  "signals":      {"never_miss": 12, "other": 4, "set_aside": 9, "stale_pages": 0,
                   "recheck": {"status": "running", "done": 120, "total": 240}},
  "technologies": {"count": 1151, "resolve_status": "completed", "resolved_at": "…"},
  "assess":       {"status": "none|running|terminating|completed|failed|terminated", "new_evidence": true,
                   "scoring_run_id": "…", "techs_done": 60, "techs_total": 60},
  "pov":          {"composed": 0, "pending": 60, "job": {"status": "running", "done": 12, "total": 60}}
}
```

- `signals.recheck` and `pov.job` are null when no job exists. Otherwise they hold the latest job, including when it has finished or was interrupted.

- The `signals` counts are the latest run's totals.
- `assess.new_evidence` is true when a collection run completed after the latest scoring run started, or when there is evidence but no scoring run yet. It is a statement about timing ("new evidence since the last assessment"), not a claim that the evidence was used.
- `collect.incomplete` is the number of sources in the latest run marked incomplete, shown as a hint on the Collect step.

---

## 8. Migration (both MongoDB instances)

This happens automatically on the first start of the new version, in both the Docker MongoDB and the Homebrew one. For Docker, start it with `docker compose up --build`.

1. **The seeding data loads (F1),** because neither database has a `seeding` document yet. The load:
   - adds the 33 signals and the crawl settings;
   - adds the new source fields and the new sources, all disabled;
   - sets each source's access and notes;
   - rolls out the three prompts.
2. **Like every load, it makes the configuration match the seeding data,** including which sources are switched on. On 2026-10-03 both databases already matched it:
   - the same 6 sources switched on;
   - no edited prompts or sources;
   - the Homebrew database's four edited scoring items (Network fabric, TORA, priority grid, evidence) have the same content as the seeding data, which was synced from that database on 10 Sep.
3. **Existing pages are marked as needing a re-check.** They have no `signals_hash`, so the Signals page shows them as checked against an older list and offers Re-check: about 240 pages in Docker and 216 in Homebrew, so that many model calls.
4. **Old data shows what isn't known.** Old runs have no signal totals or incomplete flags, so the portal shows "—". Old assessments have no `evidence_runs`, so the portal shows "not recorded for assessments before this upgrade" and never guesses.
5. **Rollback:** revert the code and the seeding data.
   - The new fields are additive, and the old code ignores them.
   - The old start scripts reload the old prompts and sources, as they do at every start.

---

## 9. Verification and acceptance

**Phase 0**
- **Edits are live and listed:**
  - Edit a prompt, a source and a scoring measure in the app. Each takes effect at once and appears in Changes with its seeding value and live value.
  - Change one back by hand: it drops off the list.
- **Restarts keep edits:** restart the API. The edits survive and stay listed.
- **Update seeding data:**
  - Tick two of the three and update. Their `seeds/` files change in the project folder, also from Docker, and git shows only those changes.
  - The third stays live and listed.
  - A restart reloads nothing.
- **A failed write:** make a seed file read-only, then update an edit that belongs in it. The error names the file, the file is unchanged, and the edit stays listed.
- **A deployment with new seeding data:** change a value in a seed file by hand and restart.
  - The value lands.
  - Edits that weren't written into the seeding data are replaced.
  - Changes is empty.
- Unit tests pass (new `tests/` folder; `pytest` as a dev dependency). They cover:
  - `parse_json`: plain, fenced, wrapped in prose, and invalid replies;
  - the load rule: a fresh database, changed seeding data and unchanged seeding data;
  - the Changes comparison (edited, added, deleted, changed back, with `version` and progress ignored) and Update seeding data;
  - signal normalization, including never miss beating ignore;
  - hash stability;
  - text splitting and merging, including a failed part;
  - the same-site rule;
  - the saved-search window: skipping collected results, `remaining`, and too broad.

**Phase 1**
- **Pilot run:** enable only IETF, arXiv and Hacker News, then `POST /api/runs {"max_pages_per_source": 10}`. Check that:
  - every page has a summary, technologies and a scout's take, as before;
  - pages with signals show hits with quotes and implications, and their summary mentions them;
  - any set-aside page shows its rule and is absent from Technologies.
- **Re-check on the existing data:**
  - progress is visible and the stale count reaches 0;
  - stubs show the same signals as their pages;
  - Technologies is refreshed.
- **Restart during a re-check:** the job shows "interrupted", and a new re-check does only the remaining pages.
- **Re-check exclusions:** a re-check is refused while a scoring run is active, and a scoring run or resume is refused while a re-check is active. Both messages name the reason.
- **Deleted signals:** delete a starter signal.
  - It stops applying from the next run, and Changes lists it as deleted.
  - A restart doesn't bring it back.
  - After Update seeding data, it is gone from `seeds/signals.json`.
  - Its past hits still show its name.
- **Prompt safety:** the Skills editor rejects a prompt without `{never_miss}`, with a clear message.

**Phase 2**
- arXiv pages come from the four lists.
- IETF pages include `datatracker.ietf.org`.
- Hacker News stores linked articles from other sites.
- A feed start page, for example a16z's, yields its articles.
- A long PDF, over 120,000 characters, is stored with `parts` above 1, one merged summary, and signals with exact quotes.
- When one part of a long page fails (forced in a test), the page keeps the other parts' results, shows "partly analysed" and is not set aside. The next re-check retries it.
- A careers page is collected, and a single job ad on it is set aside as "Single job ad".
- With Inc42 enabled, no URL containing `?` is fetched from inc42.com, because its robots.txt wildcard rule is obeyed (C7).
- A source that uses up its page budget shows "page budget reached: N links not visited". N counts the links dropped by link selection as well as those still queued (C8).

**Phase 3**
- **OpenAlex first:** `openalex_works` works end to end before the other four adapters are built (Q3).
- Each adapter, enabled alone with a 5-item budget, produces documents with summaries and signals.
- A missing key shows "not configured" without failing the run.
- Running twice creates no duplicates.
- **No silent skipping:** with a search capped at 5 and 30 results in its window:
  - the source shows "incomplete: 25 still to collect";
  - each later run skips what it has and takes the next 5;
  - once all 30 are in, `through` moves to that day;
  - there are no duplicates and no gaps across runs;
  - an adapter error leaves `through` unchanged.
- **Many results on one date:** 30 results sharing one date, capped at 5 per run, are all collected in 6 runs.
- **Too broad:** an EPO search with more than 2,000 results in its window shows "too broad: narrow the search".
- **Progress isn't configuration:** after these runs, the sources don't appear in Changes.
- `access: none` sources cannot be enabled.

**Phase 4**
- The strip shows the right state during a run, after it ("New evidence since the last assessment"), during scoring and while composing.
- **The run page shows recorded facts only:**
  - "Used in assessments of N technologies" appears only for assessments whose `evidence_runs` include the run.
  - A run whose pages fed no assessed technology says "Not used in any assessment yet", even when a scoring run started later.
  - The latest scoring run appears only under "Latest workspace activity".

## 10. Rollout and sign-off

1. Phase 0 and Phase 1, together with the tech-lens Signals page → demo on the pilot run → **sign-off**.
2. Phase 2 → pilot run → **sign-off**.
3. Phase 3: OpenAlex end to end first, then the other four adapters → keys added, adapter smoke tests → **sign-off**.
4. Phase 4, together with the tech-lens process view → full walkthrough → **sign-off**.
5. Afterwards:
   - re-check existing pages;
   - switch sources on in stages, watching cost and page budget;
   - run `docker compose up --build` and refresh the README for the packaged version.

## 11. Not in this iteration

- **Switching all sources on:** staged, after this iteration.
- **Alerts** by email or Teams.
- **A "Run full cycle" button.**
- **Remaining crawl numbers:** moving the `.env` ones into the `crawl` settings document.
- **USPTO API adapter:** needs an ID.me-verified key.
- **Direct NSF, NIH, UKRI and EU portal adapters:** OpenAlex grants covers them for now.
- **Employment-statistics adapters** (Indeed Hiring Lab, O*NET, Eurostat, MoSPI). Until they exist, "Employment trend" shows zero hits, and the Signals page makes that visible.
- **Paid sources.**
- **Form D fundraises for watched startups:** add their SEC CIKs to `sec_edgar_filings` when there is a list.
- **PIB India press releases:** there is no usable feed (Appendix C.1).
- **APAC and China coverage.**
- **Grouping hits** that describe the same event across sources.
- **Momentum charts** per signal over time.

## 12. Open questions for the business

1. Are alerts wanted, and for which signals?
2. Please confirm that set-aside pages are kept and visible, not deleted.
3. Who maintains the signal list and the saved searches: business users or admins?
4. Who can complete the USPTO ID.me check, when we add that adapter?
5. Which competitors' filings should we track? Seeded: Verizon, AT&T, Cisco, Lumen. And which companies' job boards should we watch? Seeded with 13 verified boards, mostly AI, quantum, cloud and security companies (Appendix C.5).
6. Which of the two MongoDB datasets is the real one? This has been open since 3 Oct.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Signal quality: missed or false hits | Every hit carries a quote, the feed shows everything, "Other" catches what isn't listed, rows are editable, and the pilot runs before re-checking everything. |
| Higher cost | Signals ride on existing calls (about +1K tokens per page). Splitting happens only for very long pages. You start re-checks and new sources yourself, and see the counts first. |
| Careers pages and outbound links use up the page budget | The source shows "page budget reached" (C8). Watch the pilot, and tune the skip patterns in settings. |
| A saved search finds more each run than its cap allows | Nothing is skipped: progress is kept per search, and the source shows "incomplete: N still to collect" or "too broad" (Q2). Raise the budget or narrow the search. |
| An item is indexed late, with a date before its search's `through` date (OpenAlex sometimes indexes papers days late) | It would be missed. The OpenAlex proof in Phase 3 checks for this. If it happens, each window starts a few days before `through`, with the number in the crawl settings; duplicates are skipped anyway. |
| Edits not written into the seeding data are replaced when a deployment loads it | By design. The Changes menu item shows how many there are; update the seeding data before deploying. |
| A re-check changes evidence while it is being scored | They can't run at the same time (S7). |
| The process view implies links that never happened | Links are recorded per assessment (`evidence_runs`), and timing-only information is labelled "Latest workspace activity" (P2). |
| External APIs change or throttle | Each adapter fails per source with a visible error, and backs off on rate limits. A failed window is retried next run. |
| Site terms | Never-crawl list; robots.txt obeyed, wildcards included (C7); SEC and USAJOBS receive the contact email they require. |
| Prompt edits break a stage | Placeholder validation (S8). |

---

## Appendix A: prompt texts

The prompts are stored as Python format strings, so literal braces are doubled (`{{ }}`).

### article_summary v4

**System** (unchanged): You are a scout for an emerging-technology radar. Be concrete and faithful to the text — downstream agents rely on your read as a reference point.

**Prompt:**

```
Analyze the following page. Reply with ONLY a JSON object (no code fences, no other text) of this shape:
{{"summary": "5-10 lines that condense the page WITHOUT losing its gist, context or focus — keep the concrete claims, figures, dates, named parties and caveats; when signals are present, name them and say why they matter; if the page carries no technology content, one line saying what it is instead", "technologies": ["the granular technologies this page is actually written about — the specific level, not the umbrella: 'quantum computing' or 'quantum security' rather than 'quantum', 'sparse attention' rather than 'ai'; several are fine, but only those the text is genuinely about, not every term it name-drops; lowercase english — translate a non-english technology name to its standard english equivalent; empty array if none"], "scout_take": "your read as the scout, 2-5 sentences: the flavor and sentiment of the writing, the message the writer wants to convey, and the direction this is heading — not a rising/falling flag, but where and how the trend leads: gaining traction, setting up a next discovery, settling into maturity or standardization, narrowing to a niche, stalling, or whatever the text actually implies, and by what path — what a downstream analyst should take from this page, knowing another agent may refute it", "signals": [{{"signal": "the exact name of an entry from the Never miss list, or Other", "label": "for Other only: a short name for this kind of development; otherwise null", "what": "what happened, in one sentence", "who": "the organisations or people involved", "when": "when it happened or was announced, as YYYY-MM-DD or YYYY-MM, or null", "quote": "the exact sentence from the page that shows it", "implication": "one sentence: what it means for the technology"}}], "ignore": "the exact name of an Always ignore entry if the whole page is that kind of content, otherwise null"}}

Signals add emphasis; they never replace the analysis. Always write the summary, technologies and scout_take in full, whatever the page contains.
- Report a signal only when the page itself states it, and quote the sentence that shows it. Do not infer what the text does not support.
- Report any other notable development a technology radar should not miss as signal "Other", with a short label.
- If there are no signals, return an empty list.
- Use "ignore" only when the whole page is clearly that kind of content and carries no signal.

Never miss:
{never_miss}

Always ignore:
{always_ignore}

URL: {url}

{text}
```

### link_selection v2

**System** (unchanged): You are an analyst for an emerging-technology radar. Be concrete and brief.

**Prompt:**

```
From the candidate links below, pick up to {budget} that most likely lead to technology updates, articles, news, research, filings or product announcements (skip navigation, tags, login, legal and social pages). Prefer links likely to lead to pages carrying these signals:
{never_miss_names}

Reply with only the chosen URLs, one per line.

{links}
```

### scout v2

**System** (unchanged): You are a scout for an emerging-technology radar. You scrape assigned sources and collect every technology update they carry.

**Prompt:**

```
You are assigned these sources (category {category}), listed as source_id: name (url):
{sources}

For EACH source above, call collect_source with its exact source_id, once per source. For a website, the tool crawls up to {max_depth} link levels deep within a budget of {max_pages} pages, following links inside articles, news and blog posts; for a data source, it runs the source's saved searches. Either way it extracts every update related directly or indirectly to technology, records each item's reference URL, and stores the extracted text with a summary. When every source has been collected, finish with a short report: one line per source stating items visited and documents collected. If a tool ever returns RUN CANCELLED, stop immediately.
```

### Expected placeholders (S8)

| Prompt | Placeholders |
|---|---|
| article_summary | url, text, never_miss, always_ignore |
| link_selection | budget, links, never_miss_names |
| scout | category, sources, max_depth, max_pages |
| orchestrator, analyzer | none |
| supervisor | category |
| technology_resolve | known_list, tech_list |
| measure_scoring | measure_name, definition, anchors, required_evidence, technology, fabric_name, fabric_definition, evidence |
| watch_metrics | technology, evidence |
| fabric_relevance | technology, fabrics, evidence |
| pov | technology, assessment_data |

---

## Appendix B: files touched (tech-atlas)

**New**
- `src/app/services/db/seeding.py`: the start-up load, the Changes comparison and Update seeding data (F1)
- `src/app/services/busy.py`: the no-overlap rule (S7) — a re-check never runs alongside collection or scoring
- `src/agent/scout/tools/context.py`: what collecting one source needs, and the one path every item takes (Q2)
- `src/app/api/changes.py` (F1)
- `src/app/services/signals/__init__.py`, `snapshot.py` (loads the list, hashes it, renders the prompt lines) and `recheck.py` (S4, S7)
- `src/app/api/signals.py`, `settings.py`, `pipeline.py` (§7)
- `src/agent/scout/tools/summarize.py` (S2, C1) and `collect.py` (Q2)
- `src/agent/scout/tools/adapters/__init__.py`, `base.py` (the `Item` contract, `NotConfigured`, per-search progress), `epo_ops.py`, `openalex.py` (works and awards), `sec_edgar.py`, `job_boards.py`, `usajobs.py` (Q3)
- `seeds/signals.json`, `seeds/settings.json`
- `tests/`: unit tests (§9) — `test_seeding`, `test_parse_json`, `test_signals`, `test_crawl_rules`, `test_saved_search`, `test_adapters` — plus `pytest` under `[project.optional-dependencies] dev` in `pyproject.toml`

**Changed**
- `src/app/main.py`: new routers; `recheck.reconcile_stale()` in lifespan
- `src/app/settings.py`: new keys (Q5)
- `src/app/services/db/mongo.py`, `bootstrap.py`: registry, indexes; `bootstrap.run()` calls `load_if_new()` (F1)
- `src/app/services/llm/llm.py`: `parse_json`, `call_with_backoff` (F2)
- `src/app/services/runs/runner.py`: snapshot; refuses to start while a re-check runs
- `src/app/services/runs/store.py`: new fields, stubs, totals, per-source `incomplete` and `incomplete_note`
- `src/app/api/sources.py` (new fields) and `prompts.py` (placeholder check). `scoring.py` needs no change, because its saves already set `updated_at`.
- `src/app/api/runs.py`: `used_in` and `latest_activity` (P2)
- `src/app/api/scoring_runs.py`: refuses to start or resume while a re-check runs (S7)
- `src/agent/scout/agent.py`: collect tool, source ids, sweep
- `src/agent/scout/tools/crawl.py`: start pages, feeds, same-site rule, outbound links, skip settings, no cap, robots.txt via `protego`, page-budget flag (C8)
- `requirements.txt`, `pyproject.toml`: add `protego`
- `src/agent/supervisor/tools/sources.py`: excludes `access: none`
- `src/agent/resolver/resolver.py`: set-aside rule
- `src/agent/analyzer/engine.py`: full evidence for the fabric step; `build_dossier` returns the run ids it used, and assessments store them as `evidence_runs`; shared helpers
- `src/agent/analyzer/pov.py`: `parse_json`
- `seeds/sources.json`, `seeds/prompts.json`
- `start.sh`, `start-prod.sh`, `start.ps1`, `docker-entrypoint.sh`: the three seed-script calls removed (F1)
- `docker-compose.yml`: mount `./seeds` at `/app/seeds` in the `atlas` container, so Update seeding data writes into the project folder (F1)
- `.env.example`, `README.md`

**Removed**
- `scripts/seed_sources.py`, `scripts/seed_prompts.py`, `scripts/seed_scoring.py`, replaced by the load at API start (F1)

---

## Appendix C: endpoints, feeds and IDs (checked live on 2026-10-03)

### C.1 Feeds used as start pages

| source_id | entry_urls | Notes |
|---|---|---|
| darpa | https://www.darpa.mil/rss.xml · https://www.darpa.mil/rss/opportunities.xml | News; opportunities |
| nsf_news (new) | https://www.nsf.gov/rss/rss_www_news.xml · https://www.nsf.gov/rss/rss_www_funding_upcoming.xml | News; upcoming funding |
| ukri | https://www.ukri.org/news/feed/ · https://www.ukri.org/opportunity/feed/ | News; funding opportunities. The site-root `/feed/` is empty. |
| jst | https://sj.jst.go.jp/feed/rss.xml · https://www.jst.go.jp/rss/press.xml · https://www.jst.go.jp/rss/bosyu.xml | English news (Science Japan); Japanese press releases and calls. The summarizing step already translates. |
| dfg | https://www.dfg.de/service/rss/de/324312/feed.rss · https://www.dfg.de/service/rss/de/323556/feed.rss | German press releases and calls. The English press feed lags about a month, and there is no English calls feed. |
| techcrunch_venture (new) | https://techcrunch.com/category/venture/feed/ | Funding news |
| inc42 (new) | https://inc42.com/tag/funding-galore/feed/ | Weekly Indian funding round-up. Its robots.txt forbids query-string URLs (see C7). |
| entrackr (new) | https://entrackr.com/rss | Indian startup and funding news |

**Dropped after checking: PIB India.** Its only English feed is the latest 20 press releases from every ministry, titles only; there is no MeitY or DST feed. MeitY and DST stay as crawled sources (`meity`, `dst_india`).

### C.2 EPO OPS (`epo_ops`)

- **Token:** `POST https://ops.epo.org/3.2/auth/accesstoken`
  - headers: `Authorization: Basic base64(KEY:SECRET)` and `Content-Type: application/x-www-form-urlencoded`;
  - body: `grant_type=client_credentials`;
  - returns a bearer token valid for about 20 minutes. Refresh it on 401.
- **Search:** `GET https://ops.epo.org/3.2/rest-services/published-data/search/abstract,biblio?q=<CQL>` with header `X-OPS-Range: 1-100`.
  - Limits: 100 results per request and 2,000 per query.
  - The total is in `total-result-count`.
- **Query:** the saved search plus the date window, for example `ta="quantum key distribution" and pd within "20260901 20261003"`.
- **Selection** (§5.3 Q2): the adapter reads the whole window, `pd within "<since> <today>"`.
  - It reads 100 results per request (`X-OPS-Range: 1-100`, then `101-200` and so on), up to OPS's limit of 2,000 per query.
  - OPS can't sort by date, so the new results are sorted by date in code, and the oldest are taken until `limit`.
  - A window whose `total-result-count` is above 2,000 is marked too broad.
- **Fair use:**
  - Free up to 4 GB a week, about 450 MB an hour.
  - Obey `X-Throttling-Control`; search is limited per minute.
  - On a black light, or a 403 with `X-Rejection-Reason`, wait for `Retry-After` or back off.

### C.3 OpenAlex (`openalex_works`, `openalex_awards`)

- **Papers:** `GET https://api.openalex.org/works?filter=title_and_abstract.search:"<words>",from_publication_date:<since>&sort=publication_date:asc&per_page=100&cursor=*`, paged with `meta.next_cursor` as in §5.3 Q2. This goes oldest first. The plain `search=` parameter also matches full text and is noisy.
- **Grants:** `GET https://api.openalex.org/awards?filter=default.search:"<words>",start_year:><since year − 1>&sort=start_year:asc&per_page=100&cursor=*`, paged the same way.
  - There is no start-date filter, so the adapter drops awards whose `start_date` is before `since`. The usual duplicate check handles the rest.
  - `/grants` no longer exists.
- **Key:** `api_key=<OPENALEX_API_KEY>`.
  - Free, with a $1 daily budget, against $0.10 without a key.
  - A filtered list call costs $0.0001.
  - `mailto` has been ignored since February 2026.

### C.4 SEC EDGAR (`sec_edgar`)

- **Seeded searches:** `0000732712 Verizon` · `0000732717 AT&T` · `0000858877 Cisco` · `0000018926 Lumen`.
- **Filings:** `GET https://data.sec.gov/submissions/CIK##########.json`.
  - `filings.recent` holds parallel arrays: `form`, `accessionNumber`, `filingDate`, `primaryDocument`, `items`.
  - Forms and `filingDate ≥ since` are filtered in code, and the filings are taken oldest first.
- **Document:** `https://www.sec.gov/Archives/edgar/data/<cik without leading zeros>/<accession without dashes>/<primaryDocument>`.
- **8-K exhibits:** read `…/<accession>-index.htm` and take documents whose type starts with `EX-99`. Verizon labels its exhibit `EX-99`, not `EX-99.1`.
- **Form D:** none of the four seeded companies file it. It matters only if startup CIKs are added later (§11).
- **Access:** a `User-Agent` of `TechAtlas <CONTACT_EMAIL>` is required; a request without one gets 403. At most 10 requests per second.

### C.5 Job boards (`job_boards`)

| Platform | Endpoint | Search format |
|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true` | `greenhouse:<board>` |
| Lever | `https://api.lever.co/v0/postings/<company>?mode=json` | `lever:<company>` |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/<board>` | `ashby:<board>` |

**Verified starter boards** (open roles on 3 Oct):

| Platform | Boards |
|---|---|
| Greenhouse | cloudflare (405), databricks (886), anthropic (640), zscaler (364), astranis (173), netskope (151), ionq (119), psiquantum (74), fastly (43) |
| Lever | rigetti (16) |
| Ashby | openai (829), cohere (137), sandboxaq (27) |

Not found on these platforms: Xanadu, Quantinuum, Aalyria.

### C.6 USAJOBS (`usajobs`)

- **Request:** `GET https://data.usajobs.gov/api/search?Keyword=<kw>&DatePosted=<days, at most 60>&ResultsPerPage=500`.
- **Headers:**
  - `Host: data.usajobs.gov`;
  - `User-Agent: <CONTACT_EMAIL>`, which must be the email the key was registered with;
  - `Authorization-Key: <USAJOBS_API_KEY>`.
- **Response:** the total is in `SearchResult.SearchResultCountAll`, and the titles are in `SearchResult.SearchResultItems`.

### C.7 User-Agents

- **Crawler:** keep today's `TechAtlas/0.1 (emerging-technology radar; research use)`. Some sites block agents containing "@", "bot" or "http"; PIB's firewall does.
- **SEC and USAJOBS adapters only:** include `CONTACT_EMAIL`, as both require.

### C.8 Not yet tested with real keys

The EPO OPS and USAJOBS calls were checked only against their docs and unauthenticated responses (401 or 403, which show the endpoints are up). The first adapter test in Phase 3 confirms them.

---

## 14. Build notes (2026-10-03)

Implemented as planned, with these details settled while building:
- **Progress** is stored as a list of per-search entries (`search`, `through`, `remaining`, `too_broad`, `checked_at`, `last_count`, `error`), so a search containing a dot can't break a database field name.
- **Edit timestamps:** every save already set `updated_at`; F1 uses it, so `api/scoring.py` needed no change.
- **The no-overlap rule** (`services/busy.py`) checks the recorded status of runs, scoring runs and re-check jobs, and starts each under one lock.
- **Tests:** 34 unit tests (`pytest`), against a throwaway `tech_atlas_test` database.
- **Live checks, on a copy of the Homebrew database (`tech_atlas_dev`):**
  - the configuration cycle: edit, restart, Update seeding data, deployment;
  - the Phase 1 pilot: IETF, arXiv and Hacker News, 10 pages each;
  - a data-source run: OpenAlex and the job boards with no key; EPO, SEC and USAJOBS showing "not configured".
- **Backups** of both real databases, taken before any change: `Tech-Radar/backups/2026-10-03/`.
