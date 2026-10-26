# Code review fixes: implementation plan (v1)

Builds `specification.md` in this folder. The work runs in eight phases, each ending at a check that must pass before
the next starts. Nothing touches the live database or the live containers until phase 8, and phase 8 needs the user's
go-ahead.

## Ground rules for every phase

- **Tests** run on a `tech_atlas_test_<name>` database, e.g.
  `TEST_MONGO_DB=tech_atlas_test_fixes .venv/bin/pytest -q`. Never on `tech_atlas`.
- **Anything that reads live data reads a copy.** Make it once in phase 0 and drop it at the end.
- **Docker** commands always name their services. Never a bare `--profile` command.
- **Walks of the live portal are read-only.** Never press a button that changes data. On the leaders' address, block
  `*/seen` in DevTools, because opening a Point of View counts a view.
- **Commits** only when the user asks. A push needs its own yes.
- **Documents** are updated in the phase that changes the behaviour (AGENTS.md table), and re-rendered in phase 7.

## Phase 0: baseline and a copy to check against (about 1 h)

1. Record the baseline:
   - pytest: 318 pass;
   - lens `tsc --noEmit`, `npm run lint` and `npm run build`;
   - `final_deliverable/load-test/data/perf.py` against the live API (read-only).
2. Leaders' "before" check: on :3200, with `*/seen` blocked, open every Point of View in the latest edition.
   - Confirm there are no requests to `/api/technologies/*/assessment` or `/api/scoring/runs/*`.
   - Screenshot the value fold of three Points of View.
3. **Copy the live data** into `tech_atlas_test_copy`:
   - `mongodump --archive --db tech_atlas | mongorestore --archive --nsFrom 'tech_atlas.*' --nsTo 'tech_atlas_test_copy.*'`,
     run inside the mongo container.
   - The dump only reads `tech_atlas`.
4. On the copy, run the read-only release checks. Record each count in `checks/baseline.md`:
   - duplicate active choices (CR03);
   - moves pointing at values not in their list (CR12);
   - queued jobs belonging to terminated runs (CR01);
   - the live `priority_grid` (CR11);
   - choices stranded by earlier merges (CR04, for information only);
   - the image's `pip freeze` against `uv.lock` (CR19).

**Check:** baseline numbers recorded. Nothing written to `tech_atlas`.

## Phase 1: scoring and runs (about 13 h)

Order: CR09, CR01, CR02, CR06, CR05. Shared files: `agent.py` (CR01, CR02), `stacked.py` (CR02, CR05), `engine.py`
(CR01, CR05, CR06), `find_evidence/job.py` (CR05, CR06).

| Step | Work | Files | New tests |
|---|---|---|---|
| 1.1 | CR09: `transient()`, `Transient`; re-raise permanent errors; `_Retry(Transient)` | `services/llm/llm.py`, `agent/scout/tools/adapters/base.py` | `tests/test_llm_retries.py` |
| 1.2 | CR01: `jobs.waiting()`; `keep` through recover and shutdown; start-of-job status check | `services/jobs.py`, `runs/store.py`, `runs/runner.py`, `analyzer/engine.py`, `analyzer/agent.py` | 3 in `tests/test_jobs.py` |
| 1.3 | CR02: failures collected; run fails with reasons; resume clears; per-fabric errors kept | `analyzer/agent.py`, `analyzer/stacked.py` | 4 in `tests/test_engine_stacked.py` |
| 1.4 | CR06: per-measure waiting results; API 422; job guard; estimate | `analyzer/engine.py`, `api/find_evidence.py`, `find_evidence/job.py`, `estimate.py` | 3 tests; adjust `test_the_estimate_follows_the_engine` |
| 1.5 | CR05: `build_dossier` returns `urls`; `cited_keys()`; strict `measure_result(data, cite)`; `_measure_check(cite)` factory; stand-in cites its evidence | `analyzer/engine.py`, `analyzer/stacked.py`, `find_evidence/job.py`, `llm/standin.py`, `tests/test_recipe.py` | `tests/test_measure_rules.py` (7); 1 in `test_engine_stacked.py` |
| 1.6 | **Dry-run CR05 on the copy:** apply the new rule read-only to `tech_atlas_test_copy.assessments` and count how many stored scores it would have emptied, and why | script in `checks/` | the count goes in `checks/baseline.md` |

**Check:** the full suite passes. 1.6's count is explained. If more than a handful of scores would empty, look at the
examples and adjust the matching rule before going on.

**Docs:**
- Training Manual: ch. 28 rows (CR02, CR09); Part 4 rules line (CR05).
- Product Guide: scoring lines (CR02, CR05).
- Deployment Guide: ch. 16 line (CR01).

## Phase 2: choices and configuration (about 17 h)

Order: CR03, then CR12 and CR13 together (both edit `changes.py`), then CR04, then CR11.

| Step | Work | Files | New tests |
|---|---|---|---|
| 2.1 | CR03: insert-then-retire in `create`; `dedupe_decisions()` in `backfill()` | `services/decisions.py`, `services/db/bootstrap.py` | 4 in `tests/test_decisions.py` |
| 2.2 | CR12: `_check` validates move values; `lists.repair()` before delete; nascent fallback | `services/decisions.py`, `api/lists.py`, `api/decisions.py` | 4 in `tests/test_classify.py` |
| 2.3 | CR12 + CR13 in `revert()`: repair app-added classification values; `touch_all()` for answer-bearing collections | `api/changes.py`, comment in `main.py` | 1 in `tests/test_seeding.py`; 2 in `tests/test_tech_status.py` |
| 2.4 | CR04: re-point choices with conflicts, carry catalog membership, `merge` summary in the response | `api/technologies.py` | `tests/test_merge.py` (5) |
| 2.5 | CR11: `_reasons()` per config name; 422 before saving | `api/scoring.py` | `tests/test_scoring_config.py` (7) |
| 2.6 | Lens text and notices: merge confirmation and notice; list-removal confirmation; whole-number token box | `app/admin/technologies/[id]/page.tsx`, `components/ListItems.tsx`, `app/admin/(setup)/scoring/config/page.tsx` | tsc, lint |

**Check:**
- The full suite passes.
- Run 2.1's start-up repair and 2.2's repair logic on the copy. The counts match phase 0's baseline numbers, and
  nothing else changes.

**Docs:**
- Training Manual: ch. 7 and ch. 29 (merge); ch. 17 (lists); ch. 18 (scoring checks); ch. 20 (put back).
- Product Guide: "Corrections", "Classification lists", "The scoring method".
- Deployment Guide: ch. 16 line (CR03).
- Retake a Training Manual crop only if it shows the changed confirmation text (`take_screens.py`, read-only).

## Phase 3: seeding (about 4–5 h)

| Step | Work | Files | New tests |
|---|---|---|---|
| 3.1 | `seeded_at` on items made equal to the files (load, export, revert); "edited in the app" rule | `services/db/seeding.py` | |
| 3.2 | State `ids` and `kept`; `load(keep, old_ids)`; deletions limited to items removed from the code; proposals never deleted; pre-version databases delete nothing | `seeding.py` | |
| 3.3 | `changes()` lists `kept` items; plain-words log line; lock around export and load | `seeding.py` | |
| 3.4 | Tests | `tests/test_seeding.py`: rewrite the two load tests; about 10 new | as in the spec |
| 3.5 | Check on the copy: point a test API at `tech_atlas_test_copy` with a tweaked copy of one seed file (in a temporary seeds folder). The code's change loads, live edits are kept and listed, and nothing is deleted | none committed | manual |

**Check:**
- The full suite passes.
- On the copy, after a restart with unchanged seeds, Changes shows exactly what it showed before (it is 0 on live).

**Docs:** Training Manual ch. 20; Product Guide (configuration); Deployment Guide ch. 13; README.

## Phase 4: security, uploads, async (about 7–8 h)

Order: CR21, CR14, CR08. All three touch `api/find_evidence.py`.

| Step | Work | Files | New tests |
|---|---|---|---|
| 4.1 | CR21: both upload handlers become plain `def` reading `UploadFile.file`; the middleware runs `touch_all` in the threadpool | `api/find_evidence.py`, `api/imports.py`, `main.py` | 1 in `tests/test_tech_status.py` |
| 4.2 | CR14: 8, 16 and 12 MB limits, checked while reading, with 413/422 reasons | `api/find_evidence.py` | 4 in `tests/test_find_evidence.py` |
| 4.3 | CR08: `addresses.py`; hooks on both httpx clients; `NotPublic` handling in `why_failed`, `visit` and `fetch_page`; the browser route and redirect-chain check; `_bad_link` | `agent/scout/tools/addresses.py`, `crawl.py`, `browser.py`, `api/find_evidence.py` | `tests/test_public_address.py` (7) |
| 4.4 | CR08 check: one small collection of a few JS-heavy public sources on the **scale** services only (`atlas-scale`, `worker-scale`, named). Compare page counts and time with a run of the same sources before the change, then stop those services by name | none | manual |

**Check:** the full suite passes. 4.4 shows the same pages in about the same time.

**Docs:**
- Deployment Guide: IMDSv2 with hop limit 1; private addresses refused; the front door accepts 20 MB bodies.
- Training Manual: Add evidence limits, and the internal-links line.

## Phase 5: the portal (about 9 h)

Order: CR07 (lens part), CR16, CR17, CR14 (lens part), CR19 (lens part). CR19 goes last, so one final offline build
checks everything.

| Step | Work | Files |
|---|---|---|
| 5.1 | CR07: remove the two live reads; add `/api/:path*` to the matcher; `PovValue` never fetches live on the leaders' side | `proxy.ts`, `components/PovValue.tsx` |
| 5.2 | CR16: `live` flag on the two leaders' pages; request counter and latest-`load` ref in FabricAssessment | `app/frontier/page.tsx`, `app/frontier/pov/[id]/[tech]/page.tsx`, `components/FabricAssessment.tsx` |
| 5.3 | CR17: Classify in `anyLive`; one queued refresh; failure state and pill; `explain()` with three cases and a development-only suffix; labels retry | `lib/pipeline.ts`, `components/StatusPill.tsx`, `lib/api.ts`, `lib/tech-labels.ts` |
| 5.4 | CR14: limit constants and pre-send check; `proxyClientMaxBodySize: "20mb"` | `components/AddEvidence.tsx`, `next.config.ts` |
| 5.5 | CR19: start scripts run `npm ci` when the lock changed; vendored Montserrat (10 woff2 files and `OFL.txt` in `app/fonts/`), `next/font/local` for latin plus a CSS file for the other scripts | `start.sh`, `start-prod.sh`, `start.ps1`, `app/layout.tsx`, `app/fonts/*`, `README.md` |

**Checks**, all read-only against the live API:
- tsc, lint and build. One build with the network off.
- The review's frontend harness, adjusted to resolve each fetch: expects two fetches.
- Serve the build on :3300 (admin) and :3301 (leaders, `APP_SIDE=frontier`).
  - **Leaders' address:** repeat phase 0's PoV walk, with the same folds and no live requests.
  - **403 and 200 checks:** a live PoV read, a live assessment read and `/api/technologies/x.png` return 403;
    `/api/frontier` and `/api/technologies/labels` return 200.
  - **Throttled tab switching** on the admin technology page and the leaders' grid.
  - **DevTools blocking** of `/api/pipeline` (pill shows "Not updated since …") and `/api/technologies/labels`
    (retry).
  - **Error wording:** a build pointed at a closed port shows the new 5xx wording. Rebuild normally afterwards.
- Fonts:
  - the CSS diff shows the same unicode ranges, family and fallback;
  - Rendered Fonts shows Montserrat;
  - before-and-after screenshots of the Briefing, a technology, the leaders' grid and a PoV match.

**Docs:**
- Training Manual: ch. 28 rows (new messages); ch. 13 (upload limits).
- Deployment Guide: ch. 17 wording; ch. 13 (the portal build needs only npm).
- tech-lens README.

## Phase 6: build and compose (about 3 h)

| Step | Work | Files |
|---|---|---|
| 6.1 | CR19: `requirements.txt` exported from `uv.lock` with hashes; Dockerfile `--require-hashes` and `--no-deps -e .`; README line | `requirements.txt`, `Dockerfile`, `README.md`, `tests/test_dependency_lock.py` |
| 6.2 | Image check on a separate tag (`docker build -t tech-atlas:lockcheck tech-atlas`, never compose): `pip freeze` equals the lock, and Chromium launches. Then remove the tag | none |
| 6.3 | CR07: bind the four ports to 127.0.0.1; header comment | `docker-compose.yml` |
| 6.4 | `docker compose config` (read-only) shows `host_ip: 127.0.0.1` | none |

**Check:** if phase 0 showed the live image runs newer packages than the lock, decide per package: keep the lock, or
`uv lock --upgrade-package` and rerun the suite.

**Docs:** Deployment Guide ch. 13 (ports bound to the server, Docker Engine 28 or later, repeatable builds).

## Phase 7: whole-piece regression and documents (about 4 h)

1. Run the full backend suite on a fresh test database.
2. Run `final_deliverables/code-review/checks/reproduce_review.py` on a test database. Every reproduced defect must now
   show the expected result. Run it from a copy, so the review's recorded observations stay as they were.
3. Lens: tsc, lint and a production build.
4. Re-render every changed document:
   - Product Guide, Training Manual and Deployment Guide with `build_pdf.py`;
   - the change log, a new version with one line per item, with `make_change_log.py`;
   - the business process and architecture only if a step or part changed. **None is expected:** these fixes change
     no workflow step and no container.
5. Drop `tech_atlas_test_copy` and the other test databases.

**Check:** everything green. Write the "what changed" summary for the user.

## Phase 8: release to live (needs the user's go-ahead; about 1 h)

1. Choose a quiet time: the Operations page shows nothing running.
2. Back up: `mongodump --archive --gzip` to `docs/2026-10-25/backup/`, and test it with a dry-run restore.
3. Rebuild and restart **by name**: `docker compose up -d --build atlas worker lens frontier`, then
   `docker compose up -d mongo` for the port binding. Data stays in the volume.
4. Watch the start-up log:
   - the dedupe count (should match phase 0);
   - the seeding line ("loaded nothing", since this release changes no seed file);
   - indexes.
5. Run the checks:
   - `/api/health`;
   - all screens return 200 (read-only);
   - Setup › Changes shows 0;
   - perf: no call over 0.5 s;
   - the leaders' PoV walk (with `*/seen` blocked);
   - the ports listen on 127.0.0.1 only (`lsof`).
6. Report to the user. Commit and push only when asked.

**Rollback:** check out the previous commits, `docker compose up -d --build atlas worker lens frontier`, and restore
step 2's backup only if data was harmed. No migration in this release needs undoing:
- `seeded_at`, `ids`, `kept`, `failed` and `merged_from` are additive fields;
- the CR03 dedupe only marks extra rows as replaced.

## Effort

| Phase | Hours |
|---|---|
| 0 Baseline and copy | 1 |
| 1 Scoring and runs | 13 |
| 2 Choices and configuration | 17 |
| 3 Seeding | 4–5 |
| 4 Security, uploads, async | 7–8 |
| 5 Portal | 9 |
| 6 Build and compose | 3 |
| 7 Regression and documents | 4 |
| 8 Release | 1 |
| **Total** | **about 60 hours of work content** |

## Progress

| Phase | Status |
|---|---|
| 0 | done 25 Oct: baseline clean (checks/baseline.md) |
| 1 | done: CR09, CR01, CR02, CR06, CR05; dry-run 3 of 14,614 scores |
| 2 | done: CR03, CR12, CR13, CR04, CR11, portal text |
| 3 | done: seeding, plus two refinements from the copy check (keep only items that differ; stamp equal items on first start) |
| 4 | done: CR21, CR14, CR08; real public pages still read, the browser refuses private addresses |
| 5 | done: portal (CR07, CR16, CR17, CR14, CR19); tsc, lint, offline build |
| 6 | done: requirements from uv.lock with hashes; image = lock; MongoDB not published, other ports on 127.0.0.1 |
| 7 | done: 441 tests pass; the review's reproductions all fixed; documents re-rendered; change log v30 (change 52) |
| 8 | done 25 Oct: live released after a backup; all checks pass |
