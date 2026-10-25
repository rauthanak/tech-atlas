# Implementation plan: the radar at 10 million pages, 24 Oct 2026

How the [specification](specification.md) gets built: in what order, which files, how each step is checked, and
the hours. The hours are my working time. Clock time for the long test runs is given separately.

**Status:** signed off on 24 Oct, with all four decisions in specification §14 as recommended (the live upgrade
after the re-test, with a backup). Simplified the same day, at your request: no dual-read fallbacks, no progress or
problem rows, no time estimates; the one-off upgrade runs at start-up.

**Progress (24 Oct):** phases 1–9 built. 311 API tests pass; the portal's type check and lint are clean. Phase 10
(the 10-million re-test) is under way. Notes:
- Phase 4: `restamp_all` had no callers left, so it's gone. Start over re-links every page itself.
- Phase 7: a technology's page total is counted from the index, not taken from `page_count`. That is simpler, and
  never stale.
- Phase 3: the portal has no Start over button (it's an API option only), so there was no confirm to change. The
  run page and the Technologies line now say how many new pages an Organize worked on.
- Phase 9, on a copy of live:
  - 5,719 visits became 5,022 pages, in 4.4 s;
  - an average visit record is 4.6 KB (26.6 KB before);
  - 333 of 10,514 technologies lose a page or more from their count (the most: large language models, by 13);
  - 163 pages were joined by the title rule. Each join is the same site, the same title and identical text. The
    list is kept for review before the live upgrade.
- Phase 9 also showed:
  - a lookup with no index, which slowed the upgrade as it went: fixed;
  - a text write that couldn't be repeated if stopped part-way: fixed.

**Where the work happens.**
- Code is tested on the test database (`TEST_MONGO_DB=tech_atlas_test_ux1 uv run pytest -q`; 294 pass today).
- Each phase also gets a short check on a 1-million-page copy in the scale profile (`mongo-scale`, `atlas-scale`,
  `worker-scale`, stand-in model).
- Then the full 10-million re-test.
- Nothing runs on the live database or containers until the live upgrade (phase 11), which waits for your yes.

**After each phase:**
- the API tests pass;
- `ruff` is clean;
- new indexes are in `seeds/indexes.json`;
- new collections are in `services/db/mongo.COLLECTIONS`;
- new settings are in `.env.example`;
- a client change-log entry is added in `docs/2026-10-20/1/make_change_log.py`.

---

## Order and hours

| # | Phase | Spec | Hours |
|---|---|---|---|
| 1 | Page key and newest-visit mark | §3, §4 | 3 |
| 2 | Full text kept apart | §5 | 3 |
| 3 | Organize on new pages only | §6 | 3 |
| 4 | Re-linking only what changed | §7 | 1 |
| 5 | Stored answers: changed only, rolling check, lighter recount | §8 | 1.5 |
| 6 | Assessment pack stops when full | §9 | 1 |
| 7 | Screens: a technology's pages, Points of View | §10 | 1.5 |
| 8 | Indexes built by the worker; API starts at once | §11 | 1 |
| 9 | The upgrade step | §11 | 1 |
| 10 | New test copy, test script, and the 10-million re-test | §12 | 3 (plus about 6–8 h of clock time, mostly waiting) |
| 11 | Live upgrade, after your yes | §11 | 0.5 |
| 12 | Diagrams, sizing in the deployment note, client docx | §13 | 4 |
| | **Total** | | **23.5** |

**Why this is more than the 10–11 hours I gave this morning:**
- the page key and newest-visit mark (phase 1, your point on fix 2);
- the upgrade step for existing data (phase 9);
- rebuilding the test copy (phase 10);
- the diagrams and sizing (phase 12).

The running name tally I proposed this morning is not needed. With page keys, Organize can find new names from the
new pages alone (spec §6), which is simpler.

Phases 1 and 2 come first because every later phase reads what they add. Phases 3–8 can be checked one at a time.
Phase 9 has to wait until the shape is final.

---

## Phase 1: page key and newest-visit mark (3 h)

**New file `src/app/services/pages.py`:**
- `link_key(url) -> str`: the tidied link (spec §3, rule 1). `TRACKING` is the fixed list of parameters dropped.
- `key_for(end_url, title, content_hash, site) -> str`:
  - the link key, if a visit with it exists;
  - else the key of an earlier version with the same site, title and text, found through
    `{content_hash: 1}`;
  - else the new link key;
  - a visit with no link gets its own id.
- `mark_newest(doc)`: after an insert, unsets `latest` on older visits of the same key
  (`{page_key, scraped_at: {$lt}}`).

**`services/runs/store.save_document`:**
- the previous version is looked up by `page_key` instead of `end_url`;
- the new visit gets `page_key`, `latest: true` and `visits` (the previous count plus 1); then `pages.mark_newest`;
- a stub also copies `technologies_resolved`, and the findings keep their own `technologies_resolved` (they're already
  copied with `signals`).

**`services/evidence.page_key`:** returns `d["page_key"]` (a visit with no link already has its own id as its key).

**`evidence.newest_visits`:** adds `latest: True` to its query and keeps its one-per-key loop.

**`resolver._recompute_stats`:** `page_count` counts distinct `page_key`.

**`seeds/indexes.json` gains three indexes on `documents`:**
- `{page_key: 1, scraped_at: -1}`;
- `{content_hash: 1}`;
- `{technologies_resolved: 1, latest: 1, scraped_at: -1}`, partial on `latest: true`.

**Tests (new `tests/test_pages.py`):**
- tidied links: `www.`, `#…`, trailing `/`, tracking parameters, parameter order;
- the title rule:
  - same site, title and text → one page;
  - same title, different text → two pages (the "Press Releases" case);
  - same text on another site → two pages;
- no link → its own page;
- stored twice → one `latest`, `visits` 2;
- a stub arrives linked.
- Existing tests that store pages still pass.

**Check:** on a copy of live in the test database, page counts match the read-only figures in spec §3 (5,207 by
link, 5,023 with titles).

## Phase 2: full text kept apart (3 h)

**New file `src/app/services/page_texts.py`:**
- `put(visit_id, text, page_key, run_id)`;
- `get(ids) -> {id: text}`;
- `supersede(page_key, newer_than)`;
- `prune(recent_runs) -> int`.

**The readers, each moved to the helper:**

| File | Change |
|---|---|
| `services/runs/store.save_document` | writes the text with `page_texts.put`; the visit gets `has_text: true` and no `extracted_text`; the older version's text is marked superseded |
| `services/runs/store.prune_old_text` | becomes `page_texts.prune(recent)` plus `text_pruned: true` on those visits, in one bulk write |
| `api/runs.py` (page viewer) | the text comes from the helper, for itself or the version a stub repeats |
| `services/signals/recheck.py` | `CHECKABLE` uses `has_text: True`; the text from the helper |
| `agent/tagger/tagger.candidates` | reads the visits' small fields, then their texts in batches of 500 |
| `services/prompts/preview.py` | three places; the text from the helper |

**`services/db/mongo.COLLECTIONS`** gains `page_texts`. **`seeds/indexes.json`** gains
`page_texts {superseded: 1, run_id: 1}`, partial on `superseded: true`, and `page_texts {page_key: 1}`.

**Tests:**
- `test_run_page`, `test_signals` and `test_page_reading_reuse`: storing, the viewer, Check again and retention,
  all against the new collection;

**Check:** on the 1-million copy, the average visit record size before and after.

## Phase 3: Organize on new pages only (3 h)

**`services/runs/store.save_document`:** a new version gets `to_organize: true`. A stub does not.

**`agent/resolver/resolver._resolve`**, written as the steps in spec §6:
- gather from `{to_organize: true, ignored_by: None}`;
- tidied forms of the claimed names, from `_alias_map()`;
- unclaimed names counted by pages: `distinct("page_key", {technologies: name})`, one query per name;
- the model passes are unchanged;
- register writes only for touched names;
- stamp with `_stamp_documents(alias_map, {"$or": [{to_organize: true}, {technologies: {$in: newly_claimed}}]})`,
  then clear `to_organize`;
- `_recompute_stats(names)` for the before and after names.

`replace=True` keeps today's full path.

**Writers that change a page's names or set it aside also set `to_organize: true` on that visit:**
- Check again (`recheck.record`);
- Find evidence's filing;
- linking known names (`tagger.file`).

**Operations' Organize button:** the API answer and the run row say "No new pages since the last Organize" when there
were none. Start over's confirm states how many pages it reads.

**`seeds/indexes.json`** gains `documents {to_organize: 1}`, partial on `to_organize: true`.

**Tests (`test_resolver`):**
- a second Organize with no new pages reads nothing and changes nothing;
- a new page with a new spelling of a known name joins it with no model call;
- a name that reaches the floor stamps its older pages too;
- set-aside pages are left out;
- **parity:** on a fixture of several collections, organizing collection by collection gives the same register,
  links and counts as one full Organize at the end.

**Check:** on the 1-million copy, Organize after a 300-page stand-in collection takes minutes, not hours.

## Phase 4: re-linking only what changed (1 h)

| Caller | Change |
|---|---|
| `api/imports.py:208`, `services/imports.py:516`, `services/imports.py:626` | `restamp(names)` with the names the import added, renamed or claimed (from the rows it saved) |
| `agent/find_evidence/job.py:208` | `restamp([tech["name"], *names on set-aside pages])` |
| `agent/tagger/tagger.py:318` | `restamp(names of technologies filed)` |

`restamp_all` stays only for Start over.

**Tests:** for each caller, a parity test runs it, saves the links and counts, runs `restamp_all`, and expects no
difference.

## Phase 5: stored answers: changed only, rolling check, lighter recount (1.5 h)

**`services/tech_status`:**
- `SWEEP_S` and its `touch_all` go;
- when no technology waits, `step()` takes the 500 records with the oldest `at` (a new index on
  `tech_status {at: 1}`) and works them out again;
- `touch_all` stays for settings changes and `VERSION`;
- `_classify_waiting` matches `latest: true` and compares the newest versions only (`evidence.version`).

**`resolver._recompute_stats()`** with no names (Start over) is the only path that still calls `touch_all`.

**`tech_status._record`** gains `f.new_since_pov`, the pages new since the newest Point of View's assessment, using
`evidence.new_pages` with the visits already read for the batch. `VERSION` goes up to 3, so start-up rebuilds the
records in the background.

**Tests (`test_tech_status`):**
- after a collection, only the touched technologies are marked;
- the rolling check refreshes the oldest first;
- `new_since_pov` matches the PoV list's old calculation on the fixture.

## Phase 6: assessment pack stops when full (1 h)

**`agent/analyzer/engine.build_dossier`:**
- a generator over `find({technologies_resolved: name, latest: true}).sort(scraped_at: -1)`;
- with findings first, first over `signals.technologies_resolved: name`, then over the rest, skipping keys already
  taken;
- it stops at the budget;
- the "omitted" count is the technology's `page_count` minus the pages taken;
- what it returns (`text`, `pages`, `runs`, `from`) is unchanged.

**`seeds/indexes.json`** gains `documents {signals.technologies_resolved: 1, latest: 1, scraped_at: -1}`, partial on
`latest: true`.

**Tests:**
- the new pack equals the old one (kept in the test as the reference) on every fixture technology, with and
  without findings first;
- with a tiny budget, the same cut and the same `dossier_from`.

## Phase 7: screens: a technology's pages, Points of View (1.5 h)

| File | Change |
|---|---|
| `api/technologies.technology_documents` | find, sort, skip and limit on `latest: true` through the phase 1 index; `total` from `page_count`; `copies` from `visits` (the portal's "collected N times" is unchanged) |
| `api/scoring_runs.all_povs` | `new_since_written` from `tech_status.f.new_since_pov`; `newest_visits` and the per-PoV `new_pages` go |
| `api/technologies.technology_summary` | `since_pov` from the same stored answer |

`tech_status.fresh()` still makes small changes show at once.

**Tests:** `test_technology_list`, `test_pov_view` and `test_tech_summary` give the same answers as before on their
fixtures. The order of a technology's pages is unchanged.

**Portal:** none expected. The API answers keep their shape. The walk `checks/tour.py` runs read-only to confirm.

## Phase 8: indexes built by the worker; API starts at once (1 h)

**`db/bootstrap`:**
- `ensure_database()` creates collections only;
- `ensure_indexes(db)` is called by `jobs.upkeep()`, which runs in the worker, or in the API without one, in a
  background thread;
- each index built, or failed with its reason, is logged, as today.

**Fresh install:** `scripts/create_db.py` still builds every index before loading the seeding data, since the
collections are empty and it takes seconds.

**Tests:**
- the API answers `/api/health` before indexes exist;
- the upkeep builds them.

**Check:** a fresh install on a throwaway database: bootstrap, seeding load, Changes 0, and every seeded index
present live.

## Phase 9: the upgrade step (1 h)

**New `services/db/upgrade_pages.py`, run by `bootstrap.run()` before the API answers, when visits without
`page_key` exist:**
- first makes the `page_key` and `content_hash` indexes it needs;
- then goes through those visits oldest first, in batches of 2,000. For each one it calls the same functions as
  storing does:
  - `pages.key_for`;
  - `pages.mark_newest`, which sets `latest` and `visits`;
  - `page_texts.put`, which moves the text and marks the older version superseded;
- it logs progress;
- a restart carries on with the visits still without a key.

**`README.md`:** an "Upgrading" section: back up with `mongodump` first; the API does the rest at its next start.

**Tests:**
- a fixture in the old shape is upgraded;
- a run stopped part-way finishes on the next start;
- after the upgrade, every API answer equals the answer of the same data stored in the new shape.

## Phase 10: new test copy, test script, and the 10-million re-test (3 h, plus clock time)

**`checks/scale_copy.py`:**
- each clone gets its own path (`…/copy-{n}`) and text fingerprint (`content_hash` plus the clone number);
- clone groups keep live's revisits and versions, so about 10.8 million visit records hold 10 million pages;
- still written in the old shape, so the upgrade is measured.

**`checks/e2e_scale.py`** gains steps:
- `start`: time to the API's first answer with no indexes; the worker's index build time;
- `upgrade`;
- `upkeep`;
- `recount`: a settings change, then the time until `pending()` is 0;
- the existing steps;
- screens through `perf.py` after `upkeep`, `collection` and `recount`.

**Run on the scale profile, in this order:**

| Step | Clock time (my estimate) |
|---|---|
| Drop the old copy (frees about 84 GB) | |
| Generate | about 25 min |
| Start the API | |
| Build indexes (background) | about 75 min |
| Upgrade | 1–2 h |
| Upkeep | |
| Collection | about 20 min |
| Assessment (50) | |
| Points of View (50) | |
| Publish | |
| Import | |
| Rename | |
| Check again sample | 10 min |
| Full recount | |

Total about 6–8 hours. The disk is checked before generating.

**Results:** `checks/e2e-10m-results.md`, rewritten with before-and-after columns and each spec target met or missed,
with the reason.

## Phase 11: live upgrade, after your yes (0.5 h)

1. Check that nothing is running.
2. `mongodump` of `tech_atlas` to `backup/2026-10-…/`.
3. `docker compose up -d --build atlas worker lens frontier`.
4. The worker runs the upgrade, in seconds at 5,719 visits.
5. Check live:
   - page counts match spec §3;
   - every screen loads;
   - Changes 0;
   - every seeded index is present;
   - `checks/perf.py` against live, read-only.

## Phase 12: diagrams, sizing, client docx (4 h)

| Picture | File | Hours |
|---|---|---|
| Business process | `artifacts/Business Architecture/Radar Business Architecture (standalone).html` | 1 |
| Technical architecture | `artifacts/System Architecture/Radar Architecture v0.10 (standalone).html` | 1.5 |
| Process flow | `artifacts/Radar Process Flow (standalone).html` | 0.5 |
| The docx process picture | `docs/2026-10-20/1/make_diagrams.py` | 0.5 |

What each one shows is in spec §13.

**Deployment note (client docx):** database sizing for 100,000, 1 million and 10 million pages, from the re-test's
sizes (0.5 h).

**Client docx:** new entries for the phases built, and a regenerated version.

The old diagram files are kept in each folder's `backup/` before they're replaced.

---

## Risks

| Risk | What I'll do |
|---|---|
| The full recount (spec §8) is still over 2 hours at 10 million | report the number; propose the page-and-technology record (spec §14, decision 4) |
| The upgrade needs more disk than expected | free disk is checked before it starts on the copy; a restart carries on where it stopped |
| The title rule joins two pages that a person sees as different | it needs the same site, the same title and the same text; the phase 1 check lists every join on live data for review before the live upgrade |
| Index builds slow the copy's screens while they run | recorded as they happen; not a pass or fail item |

## Not in this plan

- Sign-in, which is still the biggest open gap from the 21 Oct sync.
- Splitting `documents` into a page table and a visit table: the page key and newest-visit mark give the same
  reads with far less change.
- Anything that changes what a skill or prompt says.

---

## Progress, 25 Oct

- The **10-million re-test is done.** Its results are in `Tech-Radar/final_deliverable/load-test/load-test-report.pdf`, with the data in `data/`.
- **Fixes added after sign-off,** at your request and each approved: 1–4, A–E, plus:
  - the Classify chunking;
  - fixed signal places;
  - publish reading the Briefing's kept counts.
- **Tests:** 317 pass. The portal's type check and lint are clean.
- **Still to do:**
  - phase 11, the live upgrade: back up first, then rebuild atlas, worker and lens;
  - phase 12: fill the diagrams' sizing table from report §8, add docx change 50 and regenerate.
- The 10-million copy's containers are removed. Its data volume `tech-radar_mongo-scale-data`, about 145 GB, is kept until you decide whether to delete it.
