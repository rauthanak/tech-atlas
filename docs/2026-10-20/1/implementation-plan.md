# Plan 9: implementation plan for the backend (tech-atlas)

**Date:** 2026-10-20 · **Folder:** 2026-10-20/1 · **Status:** written 20 Oct; building waits for your go.

- **What to build:** [specification.md](specification.md). Item numbers and sections refer to it.
- **The portal half:** [tech-lens plan](../../../../tech-lens/docs/2026-10-20/1/implementation-plan.md).
- **Paths:** all relative to `tech-atlas/`.

## 0. How every item is built

1. **Before code:** confirm Changes = 0 and `live_vs_seeds.py` = 0 (`docs/2026-10-04/4/`).
   - If the item adds or edits seed files, also take a `mongodump` into `docs/2026-10-20/1/replaced/`.
2. **Code and tests,** in the throwaway `tech_atlas_test` database. Run `.venv/bin/python -m pytest -q`. There are 99 tests today, and the count only goes up.
3. **Rebuild and restart the API container,** which loads the seeds when their fingerprint changes.
4. **Check on live data:**
   - the item's "Done when" from the specification;
   - Changes = 0;
   - tokens before and after, once item 4 is in.
5. **The portal half,** then a browser walk as a first-time reader, then screenshots into the client document.
6. **Build notes** go in §15 of this file. Then show you the item.

**Code conventions, as today:**
- small modules;
- plain-language docstrings;
- every failure stored with its reason;
- no new deep agent without its own folder under `src/agent/`;
- every edit endpoint sets `updated_at` (Changes depends on it).

**New dependency:** `openpyxl` in `pyproject.toml` (item 11).

---

## Item 0. Quick fixes

**Backend:** nothing. Q1–Q5 are portal-only (see the tech-lens plan).
- For Q2, the skills' display names come from item 3's `title` field.
- Until then, the portal keeps its own names.

## Item 1. Switch a technology off from the list

**New: `src/app/services/timezone.py`.** Used by every write from now on.
- `request_tz(request) -> str` reads `X-Time-Zone`.
- It's validated with `zoneinfo.ZoneInfo`, falling back to `settings.radar.default_time_zone`.
- `now_utc()` returns an ISO string.

**`seeds/settings.json`:** add the `{"name": "radar", ...}` document with the keys in spec §4.1.
- `snapshot.py`-style merge helper `radar_settings()` in `services/settings_store.py`. It's new, but follows the pattern of `crawl_settings()`.

**`src/app/api/technologies.py`:**
- **`update_technology`:**
  - when `enabled` goes from true to false, `$set` `switched_off_at` and `switched_off_tz`;
  - when it goes from false to true, `$unset` both.
- **New `POST /technologies/bulk`:**
  - `BulkEdit{ids: list[str] (1..500), action: Literal["switch_off","switch_on"]}`;
  - one `update_many`, then `restamp_all()` isn't needed (names don't change).
- **`list_technologies`:**
  - add `switched_off_at`, `switched_off_tz` and `pages_since_off` to the rows;
  - `pages_since_off` is one aggregate over documents for the switched-off names only: distinct `end_url` with `scraped_at > switched_off_at`.

**The engine** already skips `enabled: false` (`engine.py:72-73`). There's no change there.

**Tests:** `tests/test_switch_off.py`.
- **Switching:** a switch-off records the time and zone; a switch-on clears them; bulk works.
- **The estimate:** `scoring_preview` excludes switched-off technologies.
- **The count:** pages after the time are counted.

## Item 2. The written time, in the writer's zone

**`src/agent/analyzer/pov.py`:**
- `compose_pov(scoring_run_id, tech_id, tz=None)` stores `composed_tz=tz or default`.
- The batch job takes `tz` and passes it to each compose.

**`src/app/api/scoring_runs.py`:**
- `POST /scoring/runs/{id}/pov/{tech}` and `POST /scoring/povs/compose_all` take `tz = Depends(request_tz)`.
- The responses include `composed_tz`.

**Tests:** add to `tests/test_pov*.py` (or a new `test_written_time.py`). The zone is stored; a missing zone uses the default; an invalid header uses the default.

## Item 3. Where each skill is used

**`seeds/prompts.json`:** each skill gains:
- `title`, such as "Measure scoring" or "Page reading" (article_summary);
- `stage`, one of `collect` · `organise` · `classify` · `assess` · `pov`.

**`api/prompts.py`:** `PUT` keeps `title` and `stage`; they aren't editable in the portal.

**New: `src/app/api/skills.py`.** `GET /skills/map`:
- skills are grouped by stage, with recipes from `recipes` once item 5 has seeded them;
- `calls_last_run` comes from `llm_calls` once item 4 is in, and from today's derivations in `services/prompts/preview.py` (`_last_run*`) before then;
- `tokens_last_run` comes from `llm_calls`.
- Registered in `main.py`.

**Tests:** `tests/test_skills_map.py`. Every prompt appears once, and a disabled one is marked.

## Item 4. Record tokens, and reuse the fixed opening

**New: `src/app/services/llm/context.py`.**
- `call_context: ContextVar[dict]`, holding run_kind, run_id, tech_id, recipe and skills.
- A `with_context(**kw)` context manager.

**New: `src/app/services/llm/usage.py`.**
- `record(provider_response, ok, ms, error=None)` reads usage per provider and inserts into `llm_calls` with the current context.
- `from_langchain(message)` reads `usage_metadata`.

**`src/app/services/llm/llm.py`:**
- **`ask(prompt, system=None, *, blocks=None)`.**
  - **Anthropic:** `system = [{"type":"text","text":b,"cache_control":{"type":"ephemeral"}} for the last fixed block, plain for earlier ones]`. The cache marker also goes on the fabric block when there is one; the fixed blocks are passed as `blocks`.
  - **OpenAI:** `instructions = "\n\n".join(blocks + [system])`.
  - **Both:** time the call, then `usage.record(...)` on success or failure.
  - **Signature:** callers that pass only `prompt` and `system` behave exactly as today.
- **`chat_model()`:** attach a LangChain callback handler that calls `usage.from_langchain` on each LLM end, for the deep agents.

**Set the context at each call site:**
- `engine._ask_json`: scoring, run, tech, skill;
- `summarize._analyse`: collection, run, article_summary;
- `select_links`: link_selection;
- `resolver._llm_groups` and `label_missing`: resolve;
- `pov.compose_pov`: pov;
- the deep agents: the agent's name.

**`src/app/services/db/mongo.py`:** add `llm_calls` to `COLLECTIONS`. In `bootstrap.py`, add indexes on `run_id` and `at`.

**New: `src/app/api/usage.py`.**
- `GET /usage?run_id=` returns totals by skill: calls, in, out, cache read, cache write, failed.
- `GET /usage/recent?limit=` returns per-run totals, newest first.

**Tests:** `tests/test_usage.py`.
- Fake Anthropic and OpenAI response objects are recorded with the right fields.
- A failure is recorded with `ok:false`.
- The context reaches the record.
- `blocks` give the right Anthropic `system` list, with the cache marker on the last fixed block.

## Item 5. Stacked calls; assessment as technology call + fabric calls

**Seeds:**
- `seeds/recipes.json`:
  - **`technology`:** skills `fabric_relevance`, `measure_scoring` × the technology-scope measures, `watch_metrics`. Shared blanks: technology, evidence.
  - **`fabric`:** `measure_scoring` × the fabric-scope measures. Shared blanks: technology, fabric_name, fabric_definition, tcl_today, evidence.
  - **`classify`:** filled in by item 8.
- **The measure list is resolved at run time,** from each measure's `scope`.
- `seeds/measures.json`: add `scope` (M1, M2, M3, A1, A2 → technology; S1, S2, S3, A3, X3 → fabric; X1, X2 → tata).
- `services/db/seeding.py`: add `recipes` to `ID_FIELDS`. Also add it to `COLLECTIONS`, and give it a Changes label (portal).

**New: `src/app/services/prompts/recipe.py`.**
- **`build(recipe_id, shared: dict, per_skill: dict[str, dict], fabric_part: str | None) -> Built`.**
  - The preamble, then one block per skill. Each block is `### <key>: <title>`, the skill's `system`, then its `prompt` rendered with the non-shared blanks, with each shared blank replaced by `(given once below, under <NAME>)`.
  - `measure_scoring` repeats once per measure, with key `measure:<id>`.
  - It returns `blocks` (the fixed part), `fabric_block`, `user_text` (shared values once) and `keys`.
- **`parse(reply, built) -> dict[key, value | Failure]`.**
  - It calls `parse_json`, then validates each key with that skill's validator (registry in `recipe_validators.py`).
  - It reuses the existing rules: clamp 0–10; no evidence_urls means unscorable.
- **`retry_missing(failures, ...)`** calls each failed key alone, using the normal single-skill `Prompt.render`.

**`src/agent/analyzer/engine.py`:**
- **`build_dossier`:**
  - `signals_first`: order documents that have a kept signal for this technology before the others, both groups newest first;
  - the ceiling comes from `scoring_config.evidence.max_dossier_tokens`, re-seeded at 40,000. Confirm the number with item 4's measurements first.
- **New `assess_technology_stacked(run_id, tech_id, llm, ...)`:**
  1. dossier;
  2. the technology call, giving relevance (gates), the technology measures and watch metrics;
  3. one fabric call per gated fabric, in the shared executor;
  4. Tata-scope measures are filled from active `tata_entry` decisions, or left unscored with `missing: "waiting for Tata"`. Before item 6 exists, they're always waiting;
  5. assemble each fabric's `measures`, copying in the technology-scope results with `scope`;
  6. `rollup_tora`, then `compute_placement`;
  7. `insert_one`, as today, with `calls`.
- **The switch:** `scoring_config.engine.mode` = `per_measure` | `stacked`, seeded as `per_measure` until you sign off the comparison. `assess_technology` dispatches on it.
- **`progress.llm_calls`** still counts every call, retries included.

**`src/agent/analyzer/estimate.py`:** in stacked mode, `calls = 1 + gated∩enabled fabrics` per technology. `calls_max` uses every enabled fabric.

**`src/app/services/prompts/preview.py`:** add a `recipe` view. With `?recipe=technology|fabric` (or the skill's own page, with "as stacked" switched on), it builds the stacked call with `recipe.build` from the same fill functions. The parts are labelled by block.

**`src/app/api/scoring.py`:** `PUT /scoring/measures/{id}` accepts `scope`.

**The comparison** (`docs/2026-10-20/1/compare_engines.py`, run inside the container):
- pick 20 technologies from run `6d0c41a2d13d`: P1–P6, held, and many-fabric;
- run a stacked scoring run on them (`params.engine="stacked"` overrides the setting for that run);
- compare each measure's score (mean absolute difference, unscored share), each priority and horizon, calls and tokens;
- write `docs/2026-10-20/1/engine-comparison.md`.

**After your sign-off:** set `mode` to `stacked`, re-seed, and in the same item remove `_score_measure`'s per-measure loop and `mode`.

**Tests:**
- **`tests/test_recipe.py`:**
  - the blocks don't contain technology text, so they're cacheable;
  - shared blanks appear once;
  - keys are complete;
  - a missing key retries alone;
  - a bad score is clamped;
  - no evidence means unscorable.
- **`tests/test_engine_stacked.py`,** with the `Recorder` stand-in from `test_skill_preview.py`:
  - calls = 1 + gated;
  - technology measures are copied to each fabric;
  - Tata measures wait;
  - placement equals the per-measure path when given the same scores;
  - the preview equals what was sent.

## Item 6. Gate 2: overrides and unscored measures

**New: `src/app/services/decisions.py`.**
- `create(kind, tech_id, fabric_id=None, measure_id=None, field=None, key=None, value, reason=None, tz)`:
  - checks the kind's rules (spec §4.2): required reasons; value ranges; P1–P6; whether the measure's scope fits the kind;
  - deactivates the previous active decision with the same key;
  - for `override`, stores `computed` = the current computed priority.
- `active(tech_id) -> list`.
- `deactivate(id)`.

**New: `src/app/services/effective.py`.**
- `apply(assessment, decisions, config) -> dict`. It takes the stored measures and:
  - replaces unscored with `hand_score`;
  - fills tata-scope with `tata_entry`;
  - marks `accept_gap`;
  - recomputes `rollup_tora` and `compute_placement` with no model;
  - sets `effective.priority` from an override, or the computed one;
  - flags `override_moved` when `computed` ≠ the current computed.
- It returns the measures with their state: `scored | unscored | scored_by_person | gap_accepted | waiting_for_tata`.

**Where it's used:**
- `GET /technologies/{id}/assessment?fabric=`, which is new in `api/technologies.py`;
- the scoring run detail rows (effective priority);
- `evidence.py` (placed or held);
- `pov.pov_inputs` (item 12);
- `/frontier` (item 13).

**New: `src/app/api/decisions.py`.** `POST` (tz from `request_tz`), `DELETE /{id}`, and `GET ?tech_id=`. The add-ons to `mongo.py` and `bootstrap.py` are:
- `decisions` in `COLLECTIONS`;
- an index on `(tech_id, kind, active)`.

**`src/app/api/pipeline.py`:** `_gate2(...)` returns these items, each with `count_technologies` and a link target:
- `unscored`;
- `waiting_for_tata`;
- `override_moved`;
- `maturity_mismatch`;
- `suggested_use_cases`, which arrives with item 12;
- `finance_missing`, which arrives with item 12.

**How the items are ordered:**
- technologies whose missing measures block a placement (an axis with 0 scored) come first;
- then by priority.
- `for_analyst` stays until the portal moves over.

**Tests:** `tests/test_decisions.py`.
- reasons are required;
- a new decision replaces the old one;
- a hand score turns a held pair into a placed one;
- an override sets the effective priority and its moved flag;
- deactivating restores the computed state;
- the gate2 counts and order are right.

## Item 7. Organise the technologies

**New: `src/app/services/radar_status.py`.**
- `status(tech, state, effective, classification, settings) -> {status, reason, notes}`, following the table in spec item 7.
- `list_statuses(ids)` is built on `evidence.list_states` and adds `effective.apply` only for assessed technologies, in one query per batch.

**`src/app/api/technologies.py`, `GET /technologies`:**
- `view` (`tracked|not_assessed|emerging|emerging_new|mature_not_on_tata|nascent|imported_thin|off`) and the filters (`availability, domain, trl_min, trl_max, evidence, fabric, q`) are applied before paging;
- `view_counts` reflect the current search;
- each row carries `status`, `status_reason`, `notes`, the `classification` (effective, with sources), `origin` and `imported`.
- Effective availability, domain and TRL come from `services/classify_effective.py` (item 8). Before item 8 they're "not known yet".

**`src/app/api/pipeline.py`:** `_gate1(...)` returns these items, each with its cost where there's one:
- `nascent`, which arrives with item 9;
- `import_matches`, which arrives with item 11;
- `ready_to_assess`;
- `switched_off_with_pages`.

**Tests:** `tests/test_radar_status.py`.
- every rule from the table;
- each technology gets exactly one status;
- view counts add up;
- the floor applies until a technology is classified.

## Item 8. Classify every technology

**Seeds:** generated once by `docs/2026-10-20/1/make_lists.py` from Tata's xlsx and the agreed values, then checked by hand. The files:
- `seeds/availability.json`;
- `seeds/domains.json`;
- `seeds/subdomains.json` (545);
- `seeds/trl_levels.json`;
- `seeds/path_steps.json`;
- `seeds/mechanisms.json`.

Then add each to `ID_FIELDS` and `COLLECTIONS`. In `recipes.json`, fill in `classify` and add the three classification skills to `technology`.

**Skills** (`seeds/prompts.json`, with first texts in §14):
- `evidence_strength`;
- `domain_subdomain`;
- `commercial_availability`;
- `trl_level`.

Add them to `EXPECTED_VARIABLES` in `api/prompts.py` (spec §5) and give each a preview view in `preview.py`.

**New folder: `src/agent/classifier/`.** It holds a step, not a deep agent; the folder keeps the agent layout.
- **`evidence.py`:** `pack(tech, cap, since_pages=None) -> {text, pages[], facts, read, of}`.
  - Pages are numbered.
  - Each page appears as `[n] {source name} ({cluster label}) · {date} · {title}`, then its summary, then this technology's signals with their quotes.
  - Signal pages come first, then the newest.
  - Facts: total pages, independent sources, and the clusters.
- **`classify.py`:**
  - `run_classify(tech_ids|pending, budget)` runs the classify recipe one technology at a time, in an executor of SCORING_CONCURRENCY. It goes through the parse, validate and retry steps, then writes `technologies.classification`, `pages_seen` and `list_versions`, with `source: pages`.
  - A proposed sub-domain is inserted into `subdomains` with `status: new` and `updated_at`.
  - The run stops when the budget is reached, recording why and what's left.
- **`pending() -> ids`:** switched on, has pages, and pages not in `pages_seen`, or lists newer than `list_versions`.

**New: `src/app/services/classify_effective.py`.** `effective(tech, decisions) -> {availability, domain, subdomain, trl, evidence, nascent}`, each with a source. The order:
1. a person's decision (move, import, nascent yes);
2. the assessment;
3. pages;
4. the catch-all.

**Engine:** the technology call writes `classification.domain`, `trl` and `availability` with `source: assessment`. The TRL/Maturity mismatch check goes in `effective.py`.

**Runner** (`src/app/services/runs/runner.py`, `_execute`): after `run_resolve_sync()`, when `settings.radar.classify_after_collection` (seeded true) is set, it runs `run_classify(pending)` as stage "classifying". The busy kinds gain `classify` (`services/busy.py`).

**New: `src/app/api/classify.py`.**
- `GET /classify/preview?ids|pending` returns n, calls and tokens.
- `POST /classify` (202).
- `GET /classify/runs`.

The runs are stored in a new `classify_runs` collection, shaped like `resolves`, with indexes.

**New: `src/app/api/lists.py`.**
- **Endpoints:** `GET`, `POST`, `PUT`, `DELETE` on `/lists/{name}` for the six lists, plus `POST /lists/subdomains/{id}/merge`.
- **Every write** sets `updated_at` and increments `version`.
- **A definition change** makes `pending()` mark the technologies classified under it.
- **A remove** moves its technologies to the catch-all with a `review` flag.

**Tests:**
- **`tests/test_classify.py`:**
  - the pack is bounded and orders signal pages first;
  - incremental runs send only new pages and the current answers;
  - validation: unknown ids, an out-of-range TRL, a new sub-domain;
  - the budget stop records its reason;
  - the effective order;
  - switched-off technologies are skipped.
- **`tests/test_lists.py`:** edits mark the right technologies; a remove moves them to the catch-all.

**Sample before switching on** (`docs/2026-10-20/1/classify_sample.py`):
- 50 technologies, including the 52 exact matches to Tata's file;
- the agreement on domain, availability and TRL, and the tokens, written to `classify-sample.md`.

## Item 9. Possible nascent

- **The skill:** `possible_nascent` (§14), added to `recipes.classify`.
- **Its validator:** `{flag:false}` or `{flag, reason, quote, page}`.
- **Classify** writes `classification.nascent`.
- **The `nascent` decision** (from item 6's service): "yes" adds a person `move` of availability (Research, or Pilot when the flag's page carries a trial or deployment signal) and allows assessment despite the floor (`radar_status`). "No" stores the `pages_seen` at that time, and the flag comes back only for pages not in it.
- **Views and gates:** `view=nascent` and `gate1.nascent`.
- **Tests:** in `test_classify.py`, the flag, yes and no; in `test_radar_status.py`, nascent yes makes the technology ready.

## Item 10. Find evidence

**New: `src/app/services/websearch.py`.**
- `search(query, n) -> list[{url,title,snippet}]` dispatches on `WEB_SEARCH_PROVIDER`.
- Until a provider is chosen, the only adapter is `none`, which raises `NotConfigured("Find evidence needs a web search key")`.
- `.env.example` gains `WEB_SEARCH_PROVIDER` and `WEB_SEARCH_API_KEY`, and `settings.py` reads them.

**New folder: `src/agent/find_evidence/`** (`job.py`):
1. Build the query from the gap.
2. Search.
3. Skip known URLs (`documents.end_url`).
4. Create a small run `{params:{kind:"find_evidence", job_id}}` in `runs`.
5. For each new URL, fetch it with the crawler's single-page fetch (`scout/tools/crawl.py`), then `store.save_document` and `summarize_page`.
6. `run_resolve_sync()`, if it brought new raw names; otherwise `restamp_all()`.
7. The re-run:
   - **technology:** `run_classify([tech])`;
   - **measure:** the engine's single-skill measure call for that technology, fabric and measure, which updates that measure in the latest assessment with `found_by_job`;
   - **use case:** the fabric call for that pair.
8. Write `results` and `rerun.outcome`.

**"Add a link"** starts at step 4 with the given URL.

**New: `src/app/api/find_evidence.py`.**
- `GET /find-evidence/preview` (cost, and whether a key is set).
- `POST /find-evidence` (202). It checks the daily budget, counted in the default zone, and refuses with the reason.
- `GET /find-evidence/{id}`.

The jobs are stored in a new `find_evidence_jobs` collection, with indexes.

**Tests:** `tests/test_find_evidence.py`, with a fake search, a fake fetch and the Recorder.
- known URLs are skipped;
- the re-run targets only the gap;
- the budget refusal;
- the not-configured message;
- "Add a link" works without a key.

## Item 11. Import a list of emerging technologies

**Dependency:** add `openpyxl` to `pyproject.toml`, and rebuild the image.

**New: `src/app/services/imports.py`.**
- **`read(file) -> {sheet, rows, unknown_values}`:** finds the sheet whose header row has "Technology Name", case-insensitive and trimmed. Without one: "No 'Technology Name' column in any sheet", and any file that isn't .xlsx is refused.
- **`clean(rows)`:** trim, drop blanks, and merge repeats by lowercase name.
- **`exact(rows)`:** match on name or alias.
- **`propose(rows)`:** calls `resolver._llm_groups` with the whole register as `known_list`, in chunks of `RESOLVE_BATCH_SIZE`, under context `import`.
- **`apply(import)`, on confirm:**
  - **matches:** add the alias (`$addToSet`), set `imported`, and create `move` decisions for the row's values;
  - **new ones:** insert the technology with `origin: imported`, 0 pages, `aliases:[name]` and `enabled: true`, plus its decisions;
  - finally `restamp_all()`.
- **`template() -> bytes`:** an xlsx with the six headers.

**New: `src/app/api/imports.py`.** The endpoints in spec item 11. The import record goes in a new `imports` collection.

**`src/agent/resolver/resolver.py`:** `known_register(limit)` returns the union of the top `limit` names by doc_count and every name with `origin` in (imported, added), so imported names are never cut.

**`POST /technologies`** (add by hand) goes through the same path with one row.

**Tests:** `tests/test_imports.py`, with an xlsx built in the test with openpyxl.
- the header sheet is found;
- a wrong file gets its reason;
- exact, proposed and new groups;
- rejecting a match makes the row new;
- confirming applies the aliases and decisions;
- re-importing changes nothing;
- `known_register` includes imported names.

## Item 12. The Point of View: use cases, levers, path to scale, finance, maturity with sources

**Seeds:**
- `seeds/fabrics.json` gains `levers` (Nick's two per fabric), `key_metrics`, `bottlenecks` (Nick's blockers), `cautions` and `finance_defaults` (all nulls).
- `seeds/prompts.json` gains `value_levers` (§14), and the `pov` text gets the `value` and `maturity` sections and `[n]` citation. That's a version bump.
- `recipes.fabric` gains `value_levers`, after the measures.

**Engine:**
- the fabric call's fabric part carries the levers, mechanisms and cautions;
- the `value_levers` validator checks: at most 2 use cases, lever ids from the fabric, mechanism ids that exist, pages from the numbered dossier, and no digits that look like money or percentages in the chains (those are rejected and retried);
- results are written to `assessments.use_cases` / `no_use_case`;
- suggested use cases go to `gate2.suggested_use_cases`.

**New: `src/app/services/finance.py`.**
- `figures(tech_id, fabric_id) -> {margin:{value, source}, contribution, payback, break_even, missing:[...]}`. It uses the fabric defaults and the `finance` decision, and does the arithmetic only when the inputs exist.

**New: `src/app/api/finance.py`.**
- `GET /finance?missing=true` returns the table rows: pairs with inputs, or at Proof of concept or later, judged by `path_steps.order` against the "proof_of_concept" step.

**`src/agent/analyzer/pov.py`:**
- `pov_inputs` adds:
  - the effective classification, with reasons and numbered pages;
  - use cases and levers;
  - the `path_step`;
  - the finance figures;
  - overrides, hand scores and Tata entries, with reasons;
  - the numbered SOURCES built from every cited URL (measures' `evidence_urls`, use-case pages and classification pages), deduplicated and in first-cited order.
- `SECTIONS` gains `value` and `maturity`.
- The Point of View stores `sources`.
- **Check after writing:** every `[n]` in the text must exist in `sources`. Otherwise retry once, then store the Point of View with a `citation_problems` note.

**Rewrite:** after this item, run `compose_all(recompose=True)` once. That's 147 calls, with the cost shown first.

**Tests:**
- **`tests/test_finance.py`:** the arithmetic, the sources, and the missing inputs.
- **Value levers:** validator tests, including figures rejected.
- **The Point of View:** inputs include the sources, and `[n]` is checked.

## Item 13. Frontier at its own address

**New: `src/app/api/frontier.py`.** `GET /frontier?fabric=` is read-only. It returns:
- the effective placements, with overrides marked;
- how soon and how big;
- the not-yet-placed list with reasons;
- the path step per pair;
- for each technology, the latest Point of View's id.

**The allow-list** of GET paths the frontier side may call is kept in tech-lens `proxy.ts` (see that plan). The API itself needs no change for the sides.

**`docker-compose.yml`:** a `frontier` service, built from the same `../tech-lens` context, with environment `APP_SIDE=frontier` and ports `3200:3100`.

**Tests:** `tests/test_frontier.py` covers the shape, overrides applied, and the not-yet-placed reasons.

---

## 14. First texts of the new skills

These are written in plain words, cite pages or abstain, and use names, not codes. In a stacked call, the shared blanks are replaced by pointers (spec §5). Literal braces are doubled.

**evidence_strength**
- **system:** "You judge how solid the evidence about one technology is. Precision over generosity: thin evidence called thin is a success."
- **prompt:**
  ```
  Judge how solid the evidence about {technology} is, from the numbered pages below and these facts:
  {facts}

  Weigh:
  - independent sources: several pages from one site are one voice;
  - the kind of source: standards body, preprint or journal, trade press, startup or venture press, job ads, government;
  - whether a page is independent or the vendor's own announcement;
  - the kind of signal: a named deployment, trial, funding round, standard milestone or research result counts more than marketing, opinion or event promotion.

  Verdicts:
  - strong: several independent, credible sources show real activity;
  - enough: enough credible evidence to score it fairly;
  - thin: too little, or one voice;
  - not_credible: only marketing, vendor claims or noise.

  Reply with JSON: {{"verdict": "strong|enough|thin|not_credible", "reason": "at most 20 plain words", "pages": [page numbers that carry the weight]}}

  EVIDENCE:
  {evidence}
  ```

**domain_subdomain**
- **system:** "You file a technology under Tata's own subject areas."
- **prompt:**
  ```
  Place {technology} in one of these domains:
  {domains}

  Sub-domains, by domain:
  {subdomains}

  Pick the single best domain, by its id. Pick a sub-domain under it if one fits. If none fits, propose a short new sub-domain name instead. Use "other" only when no domain fits.

  Reply with JSON: {{"domain_id": "...", "subdomain_id": "... or null", "subdomain_new": "name or null", "reason": "at most 20 words", "pages": [n]}}

  EVIDENCE:
  {evidence}
  ```

**commercial_availability**
- **system:** "You judge how available a technology is to buy today."
- **prompt:**
  ```
  How available is {technology} to buy today, judged from the pages? Use one of:
  {availability_values}

  Judge the technology as a whole, not one vendor's product. The most advanced value the pages show with a dated, named example wins. A vendor's claim alone doesn't. If the pages don't show it, answer the catch-all value.

  Reply with JSON: {{"value_id": "...", "reason": "at most 20 words", "pages": [n]}}

  EVIDENCE:
  {evidence}
  ```

**trl_level**
- **system:** "You judge technology readiness on the TRL scale, from dated evidence only."
- **prompt:**
  ```
  The technology readiness of {technology}, on this scale:
  {trl_levels}

  Use dated evidence of demonstrations, trials, deployments or ratified standards. A vendor's claim alone doesn't raise it. If the pages can't support a level, answer null and say what's missing.

  Reply with JSON: {{"level": 1-9 or null, "reason": "at most 20 words", "missing": "only if null", "pages": [n]}}

  EVIDENCE:
  {evidence}
  ```

**possible_nascent**
- **system:** "You spot technologies that may be just starting, for a person to confirm."
- **prompt:**
  ```
  Flag {technology} as possibly nascent ONLY if both hold:
  1. The technology itself looks new: research, prototype or first deployments, not an established product category under a new name.
  2. At least one page shows a strong early sign: a large funding round, a solid research result (peer-reviewed, a top venue or a benchmark), a first named deployment or field trial, a spin-out, or a new standard effort.

  If it doesn't qualify, reply {{"flag": false}}.
  If it does, reply {{"flag": true, "reason": "at most 25 words", "quote": "word for word from the page", "page": n}}.

  EVIDENCE:
  {evidence}
  ```

**value_levers**
- **system:** "You map where a technology could create value for Tata, from cited evidence. You never write a financial figure."
- **prompt:**
  ```
  Where could {technology} create value for Tata in the {fabric_name} fabric?
  FABRIC: {fabric_definition}
  TATA TODAY: {tcl_today}
  THIS FABRIC'S LEVERS: {fabric_levers}
  MECHANISMS: {mechanisms}
  CAUTIONS: {fabric_cautions}

  1. Name up to 2 use cases the pages support, highest impact first, citing pages. Don't invent.
  2. For each, pick up to 2 levers from this fabric's list. Write each as a chain: operating change → metric → financial effect → evidence needed → next step when. Cite pages for each link you can. Where you can't, say what evidence is needed.
  3. Give the capital direction: light, moderate or heavy, and why.

  Rules:
  - compare equivalent outcomes at comparable quality;
  - include implementation, integration, monitoring, exceptions and support costs;
  - count customer savings as Tata value only through a fee, more demand or retention;
  - keep retained contribution separate from new wins;
  - never write a figure: no revenue, margin, price, percentage or payback.

  If the pages show no use case: give "no_use_case", with what evidence would show one. You may then suggest up to 2 use cases from your own knowledge in "suggested", without citations.

  Reply with JSON: {{"use_cases": [{{"title": "", "rank": 1, "pages": [n], "levers": [{{"lever_id": "", "mechanism_id": "", "operating_change": "", "metric": "", "financial_effect": "", "evidence_needed": "", "next_step_when": "", "pages": [n]}}], "capital": {{"direction": "light|moderate|heavy", "why": ""}}}}], "no_use_case": null, "suggested": [{{"title": "", "why": ""}}]}}

  EVIDENCE:
  {evidence}
  ```

## 15. Build notes

These are filled in as each item is built: what changed, the checks, tokens before and after, and anything that differed from this plan.

### Item 0: built 20 Oct 2026 (live, not saved as a version)

- **`services/evidence.py`:**
  - `states()` reads assessments with an aggregation that adds `measures_scored` and `measures_of`. A measure counts as scored when its score is a number; the measures themselves are still not fetched;
  - `_assessment()` returns `measures` ({scored, of}) for the assessment and for each fabric;
  - `list_states()` adds `measures` and `priorities` (fabric and priority).
- **`api/technologies.py`:** list rows carry `measures` and `priorities`; `no_priority_counts` per state (assessed, but placed in no fabric); the summary passes `measures`.
- **Tests:** `test_the_register_says_what_each_assessment_came_to`, with the factory option `assessment(scores=, priority=)`; 100 passed.
- **Deploy:**
  - no seed changes; Changes 0; the fingerprint was unchanged, so the redeploy loaded nothing;
  - backup taken first: `docs/2026-10-20/1/backup/tech_atlas-before-item0.archive.gz`.
- **Model:** on 20 Oct you switched `.env` to Anthropic `claude-haiku-5-5`, and the redeploy picked it up. A test call through `LLM.ask` worked. Two things to check before the first collection or assessment on it:
  - `max_dossier_tokens` (300,000) against Haiku's context window; item 5 proposes 40,000;
  - `RESOLVE_BATCH_SIZE=4000` names per call against the 16,000-token reply cap (`MAX_TOKENS` in `llm.py`).
- **For item 5:** `measure_scoring` (and the stacked recipe that replaces it) gets the plain-words rule the Point of View skill has. Today's justifications say "unscorable".

### Items 1–13: built 20–21 Oct 2026 (live, not saved as a version)

You asked to finish every item without waiting between them, so they were built in one pass. Tests: **148 pass** (from 99). Backups before each deploy are in `docs/2026-10-20/1/backup/`.

**Items 1–2:**
- **Time zone:** `services/timezone.py` (`request_tz`, `valid_tz`) and `services/settings_store.radar_settings()`; the seeded `settings.radar` holds the radar's settings.
- **Switching off:** it records `switched_off_at` and `_tz`; `POST /technologies/bulk`; `pages_since_off` and `wake` on the list and the summary.
- **Points of View:** they store `composed_tz`. The 147 older ones were backfilled at boot with the default, America/Chicago (`bootstrap.backfill`).

**Item 3:**
- **Skills:** each has a seeded `title`, `stage`, `agent` and `reasoning`.
- **Map:** `GET /skills/map` gives the stages, skills and recipes, with each one's last run from `llm_calls`.

**Item 4:**
- **New modules:** `services/llm/context.py` (`with_context`, `carry`) and `services/llm/usage.py`.
- **`LLM.ask(prompt, system, *, blocks, reasoning)`:**
  - Anthropic calls are streamed, so replies of up to 64,000 tokens work;
  - a reply cut off at the limit raises with that reason;
  - `blocks` are marked for reuse.
- **Deep agents:** recorded through a LangChain callback.
- **Endpoints:** `GET /usage` and `GET /usage/recent`.
- **Different from the plan:**
  - **Reasoning is a per-skill switch** (seeded `reasoning: on|off`, editable on the skill page). Haiku reasons by default on hard prompts, and that reasoning is billed but never shown: a Point of View cost about 10,700 written tokens with it and 1,358 without. It's on for `measure_scoring`, `pov` and `value_levers`, and off elsewhere, including for the deep agents.
  - **`parse_json` gains a repair fallback** (`json-repair`). Haiku sometimes writes nearly-valid JSON (2 of the first 127 pages). A repair counts only if it keeps its type and carries real values.

**Item 5:**
- **New code:** `services/prompts/recipe.py` (`build`, `parse`), `agent/analyzer/stacked.py` (`technology_call`, `fabric_call`, `assess`), and the seeded `recipes`.
- **Engine and estimate:** the engine dispatches on `scoring_config.engine.mode`, overridden by `params.engine`. The estimate follows the mode.
- **Evidence:** evidence is chosen findings-first and numbered on the stacked path, so answers can cite pages.
- **Different from the plan:**
  - **Evidence goes first in the call, not the instructions,** so a technology's fabric calls reuse its technology call's evidence, which is the biggest part. In the 12-technology run, 1.0M of 1.65M tokens sent were reused.
  - **Commercial adoption and use-case breadth are scored per fabric,** not per technology. Judged for the technology as a whole they ran +3.25 and +2.92 above per-measure, and lifted priorities. See `engine-comparison.md`.
  - **The per-measure path is kept as the other setting,** not removed, until you've read the comparison.
- **Comparison:** `engine-comparison.md`. With the same model and pages: 19 calls instead of 204, about 12 times fewer full-price tokens, 93% of measures scored against 78%, scores about 1 point apart, and the same priority in 6 of 13 pairs.

**Item 6:**
- **New modules:** `services/decisions.py` (with its kinds and rules), `services/effective.py` and `services/gates.py`.
- **Endpoints:** `/decisions`, `/gates` and `GET /technologies/{id}/assessment`.
- **People's choices on the PoV list and run grid:** overrides show there, with the computed priority kept.
- **Different from the plan:**
  - **The gates have their own endpoint** (`/api/gates`), not fields on `/pipeline`, which every page polls every few seconds.
  - **Placement is recomputed only when a person's score changed a measure;** otherwise the run's own placement stands.

**Item 7:**
- **Statuses:** `services/radar_status.py` sets one status per technology: placed, held, ready, thin, no evidence or off.
- **Views and filters:** the views, the filters and their counts are on `GET /technologies`.
- **The Before-scoring list:** nascent, import matches, classify, ready to assess, and switched off with new pages.

**Item 8:**
- **Lists:** seeded by `make_lists.py` from Tata's file and Nick's note: availability (5), domains (10), sub-domains (555 domain and sub-domain pairs; the 545 counted earlier was distinct names), TRL levels (9), path steps (7) and mechanisms (4).
- **Code:** `agent/classifier/` (`evidence.pack`, `classify.*`), `services/classify_effective.py`, and `/classify` and `/lists`.
- **The technology call:** it also judges domain, TRL and availability, kept as `assessed_classification`. They win over Classify and lose to a person.
- **Runs:** Classify runs after each collection, as the "classifying" stage.
- **Sample:** `classify-sample.md`.
  - **Domain:** 88% agree with Tata.
  - **Availability:** 58% exact where it gave a value, 79% within one step.
  - **TRL:** 9 of 11 within one level.
  - **Tokens:** about 10,800 sent per technology (69% reused) and 344 written.
- **Different from the plan:**
  - **The budget is 8,000,000 per run,** not 2,000,000, so the first pass fits.
  - **A technology is pending when it has a page version it hasn't seen,** compared by version, not by date.
  - **A sub-domain is answered by name,** and code maps it to its id.

**Item 9:**
- **The skill:** `possible_nascent`, in the Classify call.
- **"Yes":** adds a person's move to Pilot when the flagging page shows a trial or deployment, and to Research otherwise.
- **"No":** keeps the pages known at the time; a new page flags it again.

**Item 10:**
- **Search:** `services/websearch.py` uses Anthropic's own web search on the same key, so nothing new is needed.
- **The job:** `agent/find_evidence/job.py` searches, skips known pages, then fetches, reads and saves new ones. Pages are filed under the technology and marked `found_by`. Only the gap's call runs again: Classify, the one measure, or the fabric's value levers.
- **Endpoints and budget:** `/find-evidence`, with a daily budget counted in the default zone.
- **Source:** the seeded "Web search" source, which is never collected by a run.

**Item 11:**
- **Code:** `services/imports.py`, `api/imports.py` and `POST /technologies` (add by hand).
- **The register:** `known_register` always keeps imported and added names.
- **Tata's file:** 1,000 rows, of which 88 matched exactly and, in one call, 138 were proposed and 774 are new. It waits at the review step for a person.

**Item 12:**
- **The skill:** `value_levers` (reasoning on), in the fabric call.
  - Its check refuses figures in the chains: money, percentages and amounts.
  - It runs alone on a retry, and from Find use cases.
- **Finance:** `services/finance.py` and `/finance`; the fabric edit takes levers, metrics, blockers, cautions and finance defaults.
- **The Point of View (`pov` v5):**
  - new sections `maturity` and `value`;
  - its inputs are the assessment with people's choices applied, plus the classification, value, path to scale, finance, people's choices, and numbered sources built by code;
  - every [n] is checked, with one retry, then `citation_problems`.
- **Gate 2:** gains suggested use cases, finance missing, and TRL against Maturity.

**Item 13:**
- **Endpoint:** `GET /frontier`, read-only, with overrides applied and switched-off technologies left out.
- **Executive address:** a compose `frontier` service (portal).
- **After the build (21 Oct):** each placement carries its `stage` (the effective commercial availability: id, name, `emerging`, and `known`, false for the catch-all), and the response lists `stages` in order, so Frontier can show Tata's buckets and leave Mature off its default view. Test added (149 pass).

### 21 Oct: the full run, the review for simplicity, and the single adapter

- **Full run** `c1d0d08c9f43`: 248 technologies, 772 calls (about 3 each, against about 30 on 6 Oct), 0 failed; 25% of tokens sent were reused. Measures the evidence could answer (the two Tata enters left out): 84%, against 50% on 6 Oct. All 249 Points of View rewritten with numbered sources (9 on average, 0 citation problems). The 4 pages that failed to read before the JSON repair read cleanly on a check-again.
- **Cut-points stay at 4 and 7:** `cutpoint-check.md`. The stacked engine didn't shift the spread; "how big" puts 89% of placements in its middle band in both runs, a question for calibration with Tata's past cases.
- **Every model call goes through the `LLM` adapter.** `websearch.py` built its own Anthropic client; the search is now `LLM.web_search`, recorded like any call, and `websearch.py` only says whether search is set up (an Anthropic key and an Anthropic model).
- **Simplified after a read-only review** (15 findings, all fixed; 128 lines fewer across 38 files): one stacked `ask()`/`alone()` rule in `prompts/recipe.py` for classify, stacked and value levers; `engine._load`, `assessment_doc`, `fabric_values`, `rollup`; `decisions.pick`; `now_utc` everywhere but seeding (an import cycle); `imports.new_technology`/`propose`; `classify.FIELD_OF`; one `_why_not` for Find evidence; dead code removed; states computed once per request.
  - **Bug:** the run page and the Points of View list applied overrides only, so a hand score that moved a placement didn't show there; they use `effective.apply` now.
  - **Bug:** removing a list item moved its technologies to the hard-coded "unclassified"/"other" ids, not the item flagged catch-all.
  - **One rule's small changes:** a task asked alone gets one try; classify asks a no-JSON reply once more as a whole first; a provider error on the fabric choice now stops that technology with its reason instead of quietly assessing every fabric. The technology call still doesn't ask a failed classification answer alone (Classify answers it from the pages).
- **Source names:** pages and Points of View were labelled by the source's id ("cx_today"); `evidence.source_names()` labels them by name, at write time and when an older Point of View is read. Test added (154 pass).
- **Smoke test on the deployed code:** 2 technologies assessed (6 calls) and their Points of View written; Classify on 52 pending, none failed; one Find evidence search (4 new pages, 1 refused with "too little text on the page", re-classified).

### 21 Oct, later: the gaps you found, and the line-by-line audit

**What happened.** Items were marked built when my own checks passed, but those checks tested what I'd built, not each line of the agreed spec. You found two ("movement between tech buckets" and Nick's note); four read-only audits, item by item against build-list.md, review-notes.md, ux-map.md and Nick's docx, found the rest. All were fixed the same day by seven engineers in parallel, each owning its files, then integrated, tested (211 pass) and deployed.

**Decided by you (21 Oct):** undo the 27 accepted import matches and review them again; build Frontier's six settled pieces in their simplest form; refresh all lever chains and Points of View; restamp the rewritten Points of View to US Central; keep commercial adoption and use-case breadth per fabric (signed off).

**Backend changes, by area:**
- **Lists and buckets:** `radar_status` counts "on Tata's list" by the `imported` record (92 matched technologies were counted as found by the radar only); views and filters return counts; Emerging and Mature sort least mature first; Setup counts use the effective classification.
- **Classification:** an import's value is named as Tata's ("from Tata's list (file, date)") with what the radar judged beside it; a moved domain drops a sub-domain of the old one; an undecided nascent flag survives an incremental Classify.
- **Gates:** one-click actions on to-do rows; switched-off technologies leave Gate 2; Gate 2 gains "ready for the next step".
- **Import:** the review shows each row's values and the target's pages and classification, and warns when several rows join one technology; the match skill (technology_resolve v2) and a code guard keep a narrower technology apart; several rows joining one technology no longer write their values; import decisions carry the import id; `reopen` (POST /imports/{id}/reopen) undid the 27 and put them back to review; Add technology takes values and shows its cost.
- **Nick's note:** value_levers v2 (two levers per use case, lever 1 contribution and lever 2 delivery cost, capital required, metrics from the fabric's key metrics); a `bottlenecks` decision; rungs list what they need; finance uses loss rates for protection levers, volume × price, displaced revenue, sources with dates. Nick's PQC example gives his $2.8m a year and about 21 months.
- **Point of View (pov v6):** one source numbering, overrides and bottlenecks stated, every figure cited or called a guesstimate; calls recorded under their own job; Rewrite all skips switched-off technologies.
- **Find evidence:** each found page counts as its own site; past jobs and an honest summary (filed, set aside, not read); queries from what's missing; not counted as a collection anywhere (`runs.store.COLLECTIONS`).
- **Operations:** a row for every kind of run with tokens in, out and reused, by skill; page reading reuses its fixed opening (about 1.4M of 5.3M tokens a collection).
- **Frontier:** editions (`services/editions.py`), Growth/Defence lens, the frontier line, assumptions, evidence this edition, and a `commitment` decision (Undefined → Defined → Aligned → Integrated).
- **Tests run side by side:** `TEST_MONGO_DB` gives each run its own throwaway database.

**Left for you:** the alias clean-up (earlier collections folded Quantum Error Correction and Quantum Machine Learning into Quantum computing, vRAN into Open RAN, "RL for Robotics" into Reinforcement learning, Software-Defined Edge into Edge computing); whether the narrower-name guard should also apply to collections; the two seeded assumptions (the deck's examples, dated 26 Sep).
