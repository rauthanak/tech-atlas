# Code review fixes: specification (v1)

Source: `final_deliverables/code-review/review_v1.md` (21 findings). Each finding was checked against the code on
25 Oct. This specification covers the 18 items agreed for the hardening work, plus the seeding risk the review raised
in prose. It says what each fix does, what stays exactly as it is, how it is tested, and which client documents change.
The order of work is in `implementation-plan.md`.

## 1. Rules for this work

1. **Nothing that works today stops working.** Each fix changes only the defect. Wherever a person could notice a
   difference, Section 3 lists it.
2. **Keep it simple.** No new dependencies, frameworks, services or queues. Reuse the patterns the code already has:
   the sub-domain merge's re-pointing, the stacked engine's waiting-for-Tata result, and `watch_result`'s URL check.
3. **Failures say why**, in plain words, everywhere.
4. **Tests first-class.** Every fix gets a test that fails today and passes after. The 318 existing tests stay green.
5. **No sign-in.** The access fixes rely on the network rules and the front door.
6. **Documents stay in step.** Business process, architecture, Product Guide, Training Manual, Deployment Guide and the
   change log are updated per item (AGENTS.md).
7. **Never test on live.** Tests run on `tech_atlas_test*` databases only. Anything that reads live data reads a
   restored copy.

## 2. Scope

| ID | Fix | App | Size |
|---|---|---|---|
| SEED | A deploy keeps edits made in the app instead of overwriting or deleting them | atlas (+ docs) | M |
| CR02 | A run with failed technologies ends "failed", says which and why, and can be resumed | atlas | S–M |
| CR05 | A measure's score counts only if it is a real number, not abstained, and cites pages it was given | atlas | M |
| CR06 | Tata-only measures are never sent to the model, in any path | atlas | S |
| CR01 | A restart or update no longer terminates runs still waiting to start | atlas | S |
| CR09 | Model calls retry only errors that can recover | atlas | S |
| CR03 | Saving a choice can't lose the old one or leave two in force | atlas | M |
| CR04 | Merging technologies carries over people's choices and catalog membership | atlas + lens | M |
| CR12 | Removing a list value repairs the choices and assessments that used it | atlas + lens | M |
| CR13 | "Put back the default" refreshes the stored answers, like an edit | atlas | S |
| CR11 | Scoring settings are checked before they are saved | atlas + lens (1 line) | S–M |
| CR07 | Ports open on this computer only; the leaders' address reads only published data | compose + lens | S |
| CR08 | The radar never fetches private-network addresses, including through redirects | atlas | M |
| CR14 | Upload limits match what can be stored and what the portal passes on | atlas + lens | S |
| CR21 | Uploads and the Setup refresh no longer hold up other requests | atlas | S |
| CR19 | Builds install the locked versions; the brand font is in the code | atlas + lens | S |
| CR16 | A late answer can't replace the fabric or technology now selected | lens | S |
| CR17 | Errors and stale status are shown truthfully; actions always refresh | lens | M |

Not in scope:
- CR10 (freeze every assessment input on resume): the drift is small. Later.
- CR15 (edition id in leaders' links): the leaders' address is already limited to published data by CR07. Later.
- CR18 (code structure): no defect. Do it only while touching those areas.
- CR20 (frontier algorithm): irrelevant at today's size.
- From CR09, job caps, leases and multi-worker support: one worker is the supported setup.

## 3. Everything a person could notice

These are the intended differences. Nothing else should look or behave differently.

| Where | Today | After |
|---|---|---|
| Assessment run with a failed technology | "Completed", no Resume | "Failed: 1 of 3 technologies failed: QUIC: <reason>", with Resume, which redoes only what's missing |
| Add evidence, "through to the PoV", when the assessment fails | Writes a PoV on the old scores | Says the assessment didn't finish, and why |
| A measure scored with invented links or after abstaining | Counts as scored | "Not scored", with the reason; invented links are removed |
| Per-measure engine (not the default) | Model scores Tata's own measures | "Waiting for your figure", as the stacked engine already shows |
| Find evidence on a Tata measure (direct API call only) | Model scores it | Refused, with the reason |
| Model error that can't recover (bad key, refused request) | Retries about 4 minutes, then fails | Fails at once, with the provider's reason |
| Merge technologies | Pages and names move; choices and catalog membership are lost | Choices and catalog membership move too; where both have one, the survivor's is kept and the notice names it |
| Remove a list value in use | Technologies show "Unclassified"; counts disagree | Choices pointing at it are withdrawn (History keeps them) and the technologies are classified again |
| Save a move to a value not in its list (API only) | Accepted | Refused, with the reason |
| Put back the default (Setup › Changes) | Lists and gates refresh only after up to 30 min | Refresh at once, as after an edit |
| Invalid scoring settings (API only; the portal already blocks them) | Saved, then placement crashes | Refused with the reason; nothing saved |
| Deploy that changes the seed files | Overwrites app edits; deletes app-added items and proposals awaiting review | Keeps app edits and app-added items and lists them in Setup › Changes; never deletes proposals |
| Ports on the server or Mac | Open on every network address | This computer only |
| Leaders' address | Can read live, unpublished assessments and PoV drafts | Published data only (the leaders' screens show exactly what they show today) |
| A pasted link to an internal or private address | Fetched | Refused: "the radar reads only public websites" |
| Add evidence files | "Up to 25 MB each", but anything over 10 MB is cut off silently | Up to 8 MB each and 16 MB together, refused with the reason if over |
| Error box | "tech-atlas is not running · start it in another terminal" for every server error | Says what happened (no answer / the server couldn't answer / the radar refused, with its reason); the terminal advice shows only in development |
| Top bar when the status can't be checked | Shows the old status as if current | "Not updated since 14:05" |
| After pressing an action | Status can lag up to 30 s | Status reflects the action |
| Fast tab switching | A late answer can show the wrong fabric | Always ends on the selected one |

## 4. The fixes

Line numbers refer to tech-atlas `621f91e` and tech-lens `9ec0ded`.

### SEED: a deploy keeps edits made in the app

**Problem.** At start-up, `load_if_new()` (`src/app/services/db/seeding.py:93-104`) compares one fingerprint over all
seed files. When any file changed, it runs `load()` (`:107-126`) on every list. That load:
- overwrites the seeded fields of every item, which undoes edits made in the app;
- deletes every item the files don't have (`:125`), including sources, signals and measures added in the app and the
  model's proposed sub-domains awaiting review.

With Tata deploying from its own GitHub, any commit touching a seed file, a fresh clone, or a line-ending change would
do this silently.

**After.**
- **Fresh database:** loads everything, as today.
- **Restart without a seed change:** loads nothing, as today.
- **A seed change:** the code's changes load into everything **not edited in the app** since it was last loaded,
  kept as default or put back. Items edited in the app keep their live values.
- **Deletions:** an item removed from the code is removed live, unless it was edited in the app. Items added in the
  app are never deleted. Proposals awaiting review are never deleted. An item deleted in the app is not brought back.
- **What the log says:** each item kept is named in plain words, e.g.
  `seeding data: loaded the code's changes; kept 2 edits made in the app (signals/ipo, prompts/scout); Setup › Changes lists them`.
- **Setup › Changes** lists the kept items as "edited" against the new defaults. The admin keeps them as defaults or
  puts back the default, with the buttons that exist today.
- No new screen, endpoint or button.

**Unchanged.**
- The Changes list itself, "Update seeding data" (only ticked items are written, same file layout), and
  "Put back the default".
- The awaiting-review count, and the fields the seeds don't hold (`progress`, counts).
- The developer's workflow: edit a seed file, restart, and live picks it up. The one exception is an item also edited
  in the app since it was last loaded or written; that item stays and is listed in Changes.

**Change** (`seeding.py` only).
1. Record when each item was last made equal to the seed files: the load, "Update seeding data" (`_write_list`) and
   "Put back the default" (`revert`) set `seeded_at` on the items they touch. It is a new field on live config items.
   It is not in the seeds, so it is never compared or written to the files.
2. "Edited in the app" means `updated_at` is later than both the state's `loaded_at` and the item's `seeded_at`.
3. The state document keeps:
   - `ids`: the seed ids per list, as last loaded or written. This tells "removed from the code" apart from "added in the app".
   - `kept`: the refs kept at the last load, so Changes keeps listing them after `loaded_at` moves on.
4. `load_if_new()`:
   - Fresh database: `load()`, as today.
   - Fingerprint unchanged: return, after recording `ids` if this is the first start on this version.
   - Changed: `load(keep=edited_in_app, old_ids=state.ids)`, then record the fingerprint, `loaded_at`, `ids` and
     `kept`, and log the kept items.
5. `load()`:
   - Skips upserts for kept items, and for items deleted in the app (in the old ids, missing live).
   - Deletes only `old_ids − new_ids − kept − awaiting review`.
   - With no `ids` recorded (a database from before this version), it deletes nothing and creates only missing items.
6. `changes()`: an item counts as edited if `updated_at > loaded_at` **or** it is in `kept`, and it differs from the
   seeds (the existing comparison).
7. A `threading.Lock` around `update_seeding_data()` and the load, so two exports can't overwrite each other's `.tmp`
   file.

**Tests** (`tests/test_seeding.py`).
- Rewrite `test_load_rule` and `test_load_matches_seeding_data_exactly`: they assert today's overwriting and deleting.
- New:
  - a code change loads into untouched items;
  - an app edit survives a code change and is listed in Changes;
  - kept-as-default, then changed in the code, loads (no false keep);
  - put-back, then changed in the code, loads;
  - an item removed from the code is removed; an app-added item survives;
  - proposals awaiting review survive every load;
  - an item deleted in the app stays deleted;
  - a pre-version database deletes nothing;
  - two exports at once both land;
  - the log names the kept items.
- Must stay green: `test_changes_lists_edits_added_and_deleted`, `test_progress_alone_is_not_a_change`,
  `test_update_seeding_data_writes_only_ticked`, `test_update_seeding_data_added_and_deleted`,
  `test_failed_write_leaves_file_and_listing`, `test_proposals_waiting_for_review_are_counted_apart`,
  `test_revert_puts_back_the_default`, and every test that calls `load_if_new()` on a fresh database.

**Docs.**
- Training Manual ch. 20 "Be careful": an update with new defaults keeps edits made in the app and lists them in
  Changes.
- Product Guide, configuration chapter: one sentence.
- Deployment Guide ch. 13: the API "loads the starting setup when the database is new, and the code's new defaults
  into anything not edited in the radar".
- README, and the change log.

**Risks.**
- An item edited in the app no longer takes the code's later change. This is intended. Changes lists it, so a person
  decides.
- Clock skew between `updated_at` and `loaded_at`: both are written by the same API process.
- **Ship this version with no seed changes,** so existing databases record their `ids` cleanly.

### CR02: a run with failed technologies is recorded as completed

**Problem.**
- `_sweep_in_parallel` (`src/agent/analyzer/agent.py:118-132`) catches each technology's exception and only logs it.
  `run_scoring` then finishes "completed" (`:66-68`).
- Resume only accepts failed or terminated runs (`:50-51`; portal `app/admin/scoring/assessments/[id]/page.tsx:187`).
- `evidence._latest` (`src/app/services/evidence.py:162`) and Find evidence (`src/agent/find_evidence/job.py:256`)
  trust "completed".
- Inside one technology, `stacked.assess` (`stacked.py:199-208`) stops at the first fabric that fails and throws away
  the finished answers after it.

**After.**
- Any failed technology ends the run "failed: k of N technologies failed: <name>: <reason>; …" (at most 500
  characters; the full list goes in `run.failed`).
- Resume appears and redoes only the missing technologies and fabrics. Stored technology calls and finished fabrics
  are kept, as today.
- Add evidence "through to the PoV" says the assessment didn't finish, and why.
- A failing fabric no longer discards its siblings' answers.

**Unchanged.**
- A clean run is "completed" with no error.
- Stop still wins ("terminated by user").
- The per-measure path, progress counting, the Resume cost preview, and every resume rule.

**Change.**
- `_sweep_in_parallel` returns `[{tech_id, name, error}]`.
- `run_scoring` stores it and finishes `failed` when it isn't empty.
- `resume_scoring_run` clears `failed`.
- `stacked.assess` collects each fabric's error, stores the rest, then raises one error naming the failed fabrics.

**Tests** (`tests/test_engine_stacked.py`): `test_a_run_without_failures_completes`,
`test_a_technology_that_fails_fails_the_run_and_says_why`, `test_resume_does_only_the_failed_work`,
`test_a_fabric_that_fails_keeps_the_others`. Must stay green:
- `test_a_task_left_out_is_asked_again_alone_and_resume_doesnt_re_ask`
- `test_calls_are_one_per_technology_plus_one_per_fabric`
- `test_evidence.py::test_a_run_that_stopped_partway_keeps_the_previous_assessment`
- `test_find_evidence.py::test_through_to_the_point_of_view`

**Docs.** Training Manual ch. 28: a "run failed: k of N" row ("read the reason, press Resume"). Product Guide: "if a
technology can't be assessed, the run says which and why". Change log.

### CR05: a score counts only if it is valid and cites pages it was given

**Problem.** `measure_result()` (`src/agent/analyzer/engine.py:342-363`):
- keeps a score when the answer says `unscorable`;
- accepts `true` as 1, and NaN or ±Infinity as 10 or 0;
- stores `evidence_urls` without checking it is a list;
- never checks that the cited links were in the evidence.

The same function serves the stacked engine (`stacked.py:57-62`), the per-measure engine and Find evidence's
re-score.

**After.** A score counts only when all three hold:
- it is a real number;
- the answer did not abstain;
- at least one citation is one of the pages it was given, or the fabric's TCL TODAY source.

Otherwise the score is empty and "What would" gives the model's reason, or one of:
- "the answer said the pages don't support a score, so its number isn't used"
- "the answer's score wasn't a number from 0 to 10"
- "the answer cited only pages it wasn't given, so its score isn't used"

Invented links are removed, and `evidence_urls` is always a list. Roll-ups, placement, the PoV's sources and the market
band use only valid answers.

**Unchanged.**
- Clamping and rounding.
- The existing "no citations" text.
- The market-figure rule, watch metrics and prompts (no new skill version).
- Stored assessments and "Redo scores".
- Callers that pass no allowed set: they get no membership check, as `watch_result` does today.

**Matching rule.** This is the main regression risk: correct citations must not be dropped.
- The allowed set is `pages.link_key()` of each URL **as printed in the evidence**: the newest visit's `end_url`,
  returned by `build_dossier` as a new `urls` key.
- It also includes the `https://…` sources in the fabric's TCL TODAY text.
- A cited link is kept, exactly as written, when its `link_key` is in that set. `link_key` already ignores the scheme,
  `www.`, a trailing slash, `#fragment` and tracking parameters (`src/app/services/pages.py:22-28`).
- The stand-in model (`src/app/services/llm/standin.py:40-42`) is changed to cite a URL from its evidence.

**Tests.** New file `tests/test_measure_rules.py`:
- abstained answer has no score;
- only a real number is a score (True, False, NaN, inf, "7", None);
- only pages from the evidence count, including the tidy variants;
- citing only unseen pages empties the score;
- the list is always a list;
- TCL TODAY sources count;
- an unchanged revisit under another link can still be cited (the key guard).

Plus `test_engine_stacked.py::test_a_score_citing_invented_pages_is_not_placed`. Must stay green: the market-figure,
recipe, TCL TODAY, watch, dossier and stand-in tests (`test_recipe.py` changes to `_measure_check(None)`).

**Before release:** run the new rule read-only over a **copy** of the live assessments to count how many stored scores
it would have emptied. A large number means the matching rule is missing real citations; investigate before release.

**Docs.** Training Manual Part 4 "Score one measure", rules line. Product Guide, scoring paragraph: "only pages from
its evidence count". Change log.

### CR06: Tata-only measures are never sent to the model

**Problem.**
- The per-measure engine (`engine.py:480-494`) scores every measure, Tata's included.
- Find evidence's `rerun_measure` (`find_evidence/job.py:280-305`) and `POST /api/find-evidence`
  (`api/find_evidence.py:85-97`) do not refuse Tata scope.
- The screens never send it: Find evidence shows only on unscored rows (`FabricAssessment.tsx:273-277`).

**After.**
- The per-measure engine stores Tata measures exactly as the stacked engine does (`stacked.py:161-165`): waiting for
  your figure, `scope: "tata"`, no call.
- The API refuses a Tata measure with 422: "<Name> is a figure Tata enters, not one scored from pages: enter it on the
  technology's Assessment tab, or leave it out."
- A job already queued for one makes no call and says the same.
- The per-measure cost estimate (`estimate.py:24`) stops counting Tata measures.

**Unchanged.** The stacked engine, Tata entries and Gate 2, all other measures, Find evidence and links for everything
else, and stored assessments. A defensive reread of old stored Tata scores is left out: it would change how history is
shown.

**Tests:** `test_the_per_measure_engine_never_asks_for_tata_measures`, `test_a_tata_measure_is_refused_with_the_reason`,
`test_a_queued_rerun_for_a_tata_measure_scores_nothing`. `test_the_estimate_follows_the_engine` is adjusted.

**Docs.** None: Training Manual line 910 ("never sent to the AI") becomes true. Change log.

### CR01: a restart no longer terminates runs still waiting to start

**Problem.**
- A run is written `running` before its job is queued (`engine.py:52-63`, `store.py:41-56`, then `jobs.py:38-41`).
- At start-up and at worker stop, `recover()` (`jobs.py:78-100`) and the `shutdown()`s terminate every running run
  without looking at the queue.
- The queued job then still runs: a scoring job spends model calls and overwrites the reason with "terminated by user"
  (`agent.py:68`).

**After.**
- A run still waiting in the queue stays running and starts when the worker takes it.
- A run that was really cut off is terminated, with the same message as today.
- A run stopped while queued becomes "terminated by user" with no model call.
- An already-terminated run's old job ends at once, at no cost.

**Unchanged.** Thread mode (no worker), re-queuing `again` jobs, marking running jobs failed, Resume, and other job
kinds.

**Change.**
- `jobs.waiting()` returns the run ids of queued jobs (each job's first argument).
- `recover()` and `shutdown()` pass them as `keep` to `store.reconcile_stale_runs`,
  `engine.reconcile_stale_scoring_runs`, `runner.shutdown` and `engine.shutdown`, each of which adds
  `_id: {$nin: keep}`.
- `run_scoring` and `runner._execute` return at once unless their run is `running`; a `terminating` run is finished as
  "terminated by user".

**Tests** (`tests/test_jobs.py`): `test_a_restart_leaves_work_that_has_not_started_alone`,
`test_a_worker_stop_leaves_queued_work_alone`, `test_work_stopped_before_it_started_does_not_run`. Must stay green: the
existing restart, again, queued and thread-mode tests, and `test_skill_preview`.

**Before release:** a read-only check, on the copy, that no queued job belongs to a terminated run.

**Docs.** Deployment Guide ch. 16: "Work still waiting to start when the server restarts or is updated starts
afterwards." Change log.

### CR09: model calls retry only errors that can recover

**Problem.** `call_with_backoff` (`src/app/services/llm/llm.py:71-82`) retries every exception five times over about
230 s, so a wrong key or a refused request takes about 4 minutes to fail.

**After.**
- Fails at once, with the provider's message, on errors that can't recover: 400, 401, 403, 404, 413, 422 and billing
  errors.
- Still retries, on the same schedule:
  - 408, 409, 429 and 5xx;
  - the overloaded and rate-limit errors the provider sends mid-reply;
  - network and timeout errors;
  - MongoDB connection errors;
  - the adapters' throttling marker.

**Unchanged.** The schedule, cancellation, the signature (tests patch it), the deep agents' own retries, adapter
throttling, and a failed summary keeping its page.

**Decision taken: a reply cut off at the length limit keeps being retried, as today.** This follows rule 1; changing it
is a separate decision.

**Change.** `transient(exc)` in `llm.py` checks the exception's class names, status code and the body's error type, so
no SDK is imported at load. `call_with_backoff` re-raises at once when it returns false. `base._Retry` subclasses the
new `Transient`.

**Tests** (`tests/test_llm_retries.py`): permanent errors fail at once with no sleep; each transient kind is retried;
the full schedule when it persists; Stop ends the retries; adapter throttling is still retried.

**Docs.** Training Manual ch. 28: a row "failed with a message from the model service" → "trying again won't help on
its own: read the reason". Change log.

### CR03: saving a choice can't lose the old one or leave two in force

**Problem.** `decisions.create()` (`src/app/services/decisions.py:195-205`) deactivates the old choice, then inserts
the new one. If the insert fails, nothing is left in force. Two saves at once can leave two choices in force, and
undoing one brings the other back.

**After.** A failed save leaves the previous choice in force. Simultaneous saves end with exactly one, the newest.
Existing duplicates are repaired at start-up: the newest is kept, the others are marked replaced. Screens already show
the newest, so nothing visible changes.

**Change.**
- Insert first, then deactivate the older active rows for the key: earlier `at`, or the same `at` and a smaller `_id`,
  or no `at`.
- If a newer active row exists, deactivate the one just inserted.
- No unique index: a standalone MongoDB has no transactions, and an index can't coexist with "insert first".
- `bootstrap.dedupe_decisions()` runs in `backfill()` at every start. It groups by the key with `$ifNull` on the
  optional fields, keeps the newest and stamps the rest `replaced_at`.

**Tests** (`tests/test_decisions.py`): a failed save keeps the choice; a newer choice saved first stays; eight saves at
once leave one; start-up keeps the newest of duplicates. Must stay green: all of `test_decisions.py`, the import
reopen and confirm tests, the catalog undo test, the watch undo test, and `test_tech_status` choice pickup.

**Before release:** count duplicate active choices on the copy.

**Docs.** Deployment Guide ch. 16: "At start-up the radar checks each person's choice is recorded once." Change log.

### CR04: merging technologies carries over people's choices

**Problem.** `merge_technologies` (`src/app/api/technologies.py:433-463`) moves aliases and deletes the absorbed
technology. Its active choices stay on the deleted id, and its catalog membership (`imported`, `origin`) is lost. There
is no undo, and the confirmation mentions only pages.

**After.**
- **Confirmation:** "Merge X into Y? X's pages, names and the choices people made on it (changes, priorities, scores,
  Tata's plan) move to Y, and X is removed. Where both have a choice on the same thing, Y's is kept. This can't be
  undone."
- **Notice afterwards:** "Merged. Y now has X's pages; 5 of X's choices moved to Y. Y's own choice was kept for:
  Commercial availability (X had Pilot). X's catalog membership moved to Y."
- **History:** shows the moved choices; the dropped ones show as replaced.

**Unchanged.**
- The request body, its refusals, the alias union, the target keeping its name, and the restamp and refresh.
- History stays on the old id: assessments, PoVs, runs, technology calls, editions and their PoVs and rows, view
  counts, imports.
- The response still carries the technology.

**Change.** For each absorbed technology, in the order given:
- Re-point its active choices to the target. Where the target has the same key, keep the target's and mark the
  absorbed one replaced.
- Stamp `merged_from` on each.
- Copy `imported` and `origin` when the target lacks them.
- Then the existing alias, delete and restamp steps.

The response adds `merge: {absorbed, choices_moved, catalog_carried, conflicts}`, worded by the existing
`api.decisions.described()`. Re-running an interrupted merge is safe. No tombstone: nothing needs one.

**Portal.** `app/admin/technologies/[id]/page.tsx`: the new confirmation text, and a notice built from `merge`.

**Tests** (new file `tests/test_merge.py`): choices move and conflicts are named; catalog membership is carried;
history stays; an interrupted merge can run again; with two absorbed technologies, the first wins.

**Docs.** Training Manual ch. 7 (Manage) and ch. 29 ("Two technologies are really the same"). Product Guide
"Corrections". Change log. Retake a crop only if it shows the confirmation.

### CR12: removing a list value repairs what used it

**Problem.**
- `remove()` (`src/app/api/lists.py:117-133`) rewrites only the raw page classification.
- Active moves and the assessment's classification still point at the removed value. They take priority
  (`classify_effective.py:44-62`), so the technology shows "Unclassified" and counts disagree.
- A move to any string is accepted (`decisions.py:96-97`).
- "Put back the default" deleting an app-added value causes the same.

**After.**
- Removing a value withdraws the choices that pointed at it (History keeps them) and clears the assessment's answer
  for that field.
- It marks those technologies to be classified again, so they show the catch-all, or what their pages say, and the
  next Classify reclassifies them.
- **Confirmation:** "Technologies filed under it move to the catch-all, or to what the radar judged from their pages,
  marked to be classified again. A choice a person or an import made for it is withdrawn; History keeps it."
- A move to a value not in its list is refused: "'pilot' isn't in the Commercial availability list any more: choose a
  value from the list".
- If Pilot and Research are both gone, a nascent "yes" records the yes without moving availability, and says why.

**Unchanged.**
- The catch-all and TRL refusals.
- `moved_to_catch_all` (raw meaning, which the existing test asserts).
- Sub-domain merge and unmerge.
- Import values `new:<name>`.
- Removing assumptions, mechanisms and path steps.

**Change.**
- `lists.repair(name, item)` runs before `delete_one`. It deactivates moves with `removed_from_list`, unsets or nulls
  the matching `assessed_classification` part, and sets `classification_stale`. It returns counts.
- `changes.revert` calls it for app-added classification values.
- `decisions._check` validates move values against their list.
- The nascent "yes" picks an early value that exists.

**Portal.** The `ListItems.tsx:24` confirmation text.

**Tests** (`tests/test_classify.py`, `tests/test_seeding.py`): removal withdraws moves and clears the assessment; a
move to a value not in the list is refused; nascent yes falls back to Research, or moves nothing and says why;
put-back repairs like removal. Must stay green: the existing remove, priority-order, nascent, import, frontier and
setup-count tests.

**Docs.** Training Manual ch. 17 ("Add, edit or remove"). Product Guide "Classification lists". Change log.

### CR13: "Put back the default" refreshes the stored answers

**Problem.** `/api/changes/revert` (`src/app/api/changes.py:39-47`) is outside the paths that refresh stored answers
(`main.py:53-54`). Lists and gates stay old until the 30-minute sweep.

**After.** Putting back a setting, list, measure, fabric or scoring setting refreshes every technology, as the original
edit did. Putting back sources, prompts, signals or recipes does not, as their edits don't.

**Change.** In `revert()`: if anything was put back and any item's collection is in
`{settings, fabrics, measures, scoring_config, *lists}`, call `tech_status.touch_all()`. Add a comment by
`CONFIG_PATHS` pointing to it.

**Tests:** `test_putting_back_a_list_value_marks_every_technology`, `test_putting_back_a_signal_marks_none`.

**Docs.** Training Manual ch. 20, the Put back bullet. Change log.

### CR11: scoring settings are checked before they are saved

**Problem.** `PUT /scoring/config/{name}` (`src/app/api/scoring.py:158-163`) saves any dictionary. An empty band-edge
list crashes placement (`placement.py:18-22`).

**After.** An invalid save returns 422 with plain reasons, and nothing is saved. The portal already shows
"Not saved: <reason>".

**Rules:**
- **Unknown keys** are refused.
- **`open_question`:** null, or text up to 1,000 characters.
- **`priority_grid`:**
  - band edges are two numbers, 0 ≤ lower < upper ≤ 10;
  - the measure lists name existing measures;
  - the grid has exactly the cells for the bands, each P1–P6.
- **`evidence`:** a whole number above 0.
- **`engine`:** `stacked` or `per_measure`.
- **`horizons`:** near, mid and far, each a non-empty name.

**Unchanged.** All seven payloads the portal sends today (listed in the test), the edges preview, the 404, the version
bump, and that only successful saves refresh technologies.

**Portal.** The token box accepts only whole numbers (`config/page.tsx:477`), matching its own message.

**Tests** (new file `tests/test_scoring_config.py`): every portal save still saves; bad edges, cells, measures, tokens,
modes and keys are refused with nothing changed; a refused save refreshes nothing.

**Before release:** read the live `priority_grid` on the copy.

**Docs.** Training Manual ch. 18: "A save the radar couldn't use is refused, saying why." Product Guide: one line.
Change log.

### CR07: ports on this computer only; leaders' address reads only published data

**Problem.**
- `docker-compose.yml` publishes 27017, 8100, 3100 and 3200 on every address (`:26-27`, `:47-48`, `:83-84`,
  `:100-101`). MongoDB has no password.
- `proxy.ts:18-19` lets the leaders' address read the live PoV and the live assessment. The leaders' screens never use
  either, because every edition freezes `value` (`editions.py:289`).
- The matcher skips any `/api` path ending in an image extension (`proxy.ts:50`).

**After.** The four ports answer on 127.0.0.1 only. The leaders' address returns 403 for live reads and for image-named
`/api` paths. Every leaders' screen shows exactly what it shows today.

**Unchanged.**
- Container-to-container addresses, and every local tool: tests, the lens dev proxy, curl checks, perf and screenshot
  scripts.
- The admin PoV page's live view.
- The leaders' grid, table, PoV and every fold.

**Change.**
- Compose: `"127.0.0.1:<port>:<port>"` for the four ports, with an updated header comment.
- `proxy.ts`: delete the two entries, and add `"/api/:path*"` to the matcher.
- `PovValue.tsx:36`: never fetch live on the leaders' side.

**Tests.** Read-only `docker compose config`. A before-and-after network check of every leaders' PoV, with `*/seen`
blocked. 403 and 200 checks on a local leaders' build (port 3301). Lens tsc, lint and build.

**Docs.** Deployment Guide ch. 13: the containers' ports are bound to the server; only the front door is published;
use Docker Engine 28 or later. Change log.

### CR08: the radar never fetches private addresses

**Problem.**
- The pasted-link check (`api/find_evidence.py:30-37`) checks only the scheme and logins.
- The crawl client and `fetch_page` follow redirects anywhere (`crawl.py:388`, `:463`).
- The browser fallback (`browser.py:67-70`) has no filter.
- On AWS this can reach the metadata address (169.254.169.254) and the internal network.

**After.**
- Every fetch refuses loopback, private, link-local, carrier-grade NAT, reserved, multicast and unspecified addresses
  (IPv4, IPv6, mapped). The check runs before the request and on every redirect.
- Pasted links: 422 "this link points inside a private network: the radar reads only public websites. Save the page as
  a PDF and add the file instead."
- Crawls skip such links with that reason.
- A name that doesn't resolve goes on to fail as today ("the site couldn't be reached").

**Unchanged.** Public crawling, robots, feeds, sitemaps, the browser fallback for public pages, and the data adapters.

**Change.**
- New module `src/agent/scout/tools/addresses.py`: `private_host()`, an httpx request hook (which runs on every hop),
  `NotPublic`, and `PRIVATE`.
- The hook goes on both httpx clients.
- `why_failed`, `visit` and `fetch_page` handle `NotPublic`.
- `browser._fetch` routes every request through the check (service workers blocked) and checks the redirect chain
  after `goto`.
- `_bad_link` uses the check.

**Tests** (new file `tests/test_public_address.py`): each private form is refused; public and unresolvable addresses
pass; a name resolving to a private address is refused; a redirect to the metadata address is refused; a crawl skips
with the reason; a pasted link is refused; the browser guard aborts. `test_crawl_robust` and `test_find_evidence` stay
green.

**Before release:** one small collection on the scale copy, comparing page counts and time.

**Docs.**
- Deployment Guide ch. 6/7: **require IMDSv2 with hop limit 1**; the radar refuses private addresses.
- Training Manual, Add evidence: "Links to internal sites can't be read: save the page as a PDF and add the file."
- Change log.

### CR14: upload limits match storage and the portal

**Problem.**
- Add evidence allows 25 MB per file (`api/find_evidence.py:100`), but puts every file's text into one job document,
  which MongoDB caps at 16 MB (`job.py:113-117`).
- The portal's proxy silently cuts request bodies over 10 MB (Next's `proxyClientMaxBodySize` default).
- Tata imports near 10 MB are affected too.

**After.**
- Up to 8 MB per file and 16 MB together, refused with 413 and the reason.
- At most 12 MB of text read from them together, refused with 422 before anything is queued.
- The portal states the real limits and checks them before sending.
- The proxy passes bodies up to 20 MB whole.

**Unchanged.** 20 links and 10 files, the file types, the no-text refusal, and the job flow.

**Change.**
- Constants, reading with a limit, a running total and a text total, in the (now synchronous) handler.
- Lens: `proxyClientMaxBodySize: "20mb"` in `next.config.ts`, and the limit constants and check in `AddEvidence.tsx`.

**Tests:** a file over 8 MB is refused; files together over 16 MB are refused; text over the limit is refused; a
near-limit upload queues. Lens: build and a read-only form check (choosing a file sends nothing).

**Docs.** Training Manual, Add evidence: the limits. Deployment Guide: the front door must accept 20 MB request bodies
(nginx defaults to 1 MB). Change log.

### CR21: uploads and the Setup refresh don't hold up other requests

**Problem.** `async def add_evidence` (`api/find_evidence.py:117`) and `async def upload` (`api/imports.py:43`) parse
files and call MongoDB on the event loop. The middleware's `touch_all()` (`main.py:61-70`) does too.

**After.** The same answers and status codes; other requests are no longer paused.

**Change.** Both handlers become plain `def`, reading `UploadFile.file` (FastAPI 0.156 runs them in the threadpool).
The middleware uses `await run_in_threadpool(tech_status.touch_all)`.

**Tests:** `test_a_setup_edit_marks_every_technology_off_the_event_loop`. The import and Find evidence tests stay green.

**Docs.** None beyond the change log.

### CR19: locked builds and the brand font in the code

**Problem.**
- The API image installs `requirements.txt`, which uses `>=` bounds, and ignores `uv.lock`
  (`Dockerfile:8-9`, `requirements.txt`).
- The lens start scripts run `npm install`.
- `next/font/google` (`app/layout.tsx:2-12`) needs Google at build time.

**After.**
- Every build and start script installs exactly the locked, hash-checked versions.
- Restarts never pick up new packages.
- The portal builds with no font service, and looks identical: Montserrat 300–600, true italics, the same scripts,
  the same fallback metrics and the same preloads.

**Change.**
- `requirements.txt` becomes `uv export --frozen --no-dev --no-emit-project --format requirements-txt`.
- The Dockerfile uses `--require-hashes` and `pip install --no-deps -e .`.
- README: how to change a dependency.
- Lens start scripts run `npm ci` only when the lock changed.
- The 10 Montserrat woff2 files Next uses today, plus `OFL.txt`, go into `app/fonts/`. `next/font/local` handles
  latin (preloaded), and a small CSS file holds the other scripts with their exact unicode ranges.

**Tests.**
- `tests/test_dependency_lock.py` checks that requirements match the lock.
- Image check on a separate tag (never compose): `pip freeze` equals the lock, and Chromium launches.
- Before deploying, diff the live image's `pip freeze` against the lock.
- Lens: an offline build, a CSS diff, and before-and-after screenshots of four screens.

**Docs.** Deployment Guide ch. 13: builds are repeatable; the portal's build needs only the npm registry. README.
Change log.

### CR16: a late answer can't replace the current selection

**Problem.** `FabricAssessment.tsx:141-145`, `app/frontier/page.tsx:303-307` and
`app/frontier/pov/[id]/[tech]/page.tsx:38-40` apply whatever answer lands last.

**After.** The screen always ends on the selected fabric or technology. After a save, the reload is for the tab now
selected.

**Unchanged.** Previous data stays on screen while loading, error display, and saves using the data on screen.

**Change.**
- A `live` flag in the two leaders' effects.
- A request counter plus a ref to the latest `load` in FabricAssessment, so `done()` reloads the current tab.

**Tests.** tsc, lint and build. Throttled read-only switching on the admin technology page and the leaders' grid.

**Docs.** Change log only.

### CR17: errors and stale status shown truthfully

**Problem.**
- `lib/pipeline.ts:92-95` leaves Classify out of fast polling.
- `:108`: an action's refresh returns the request already in flight.
- `:112`: errors are swallowed.
- `lib/api.ts:63-75`: every 5xx says "tech-atlas is not running… start it in another terminal", shown to leaders too.
- The API's `detail` is ignored.
- `lib/tech-labels.ts:20` never retries after a failure.

**After.**
- **Error box:**
  - "The portal can't be reached" (no answer).
  - "The radar's server couldn't answer", with the API's detail or "it may be restarting… tell the team that runs the
    radar".
  - "The radar refused this request (HTTP n)", with the API's reason.
  - The terminal advice appears only in a development build.
- **Top bar:** "Not updated since 14:05" when a check fails, and "Status unavailable" before the first answer.
- **Polling and labels:**
  - after an action, one more status check follows the one in flight;
  - Classify polls every 5 s;
  - labels retry every 30 s.

**Unchanged.** Layouts, colours, API messages, the intervals, background-tab rules, one request at a time, and the pill
when all is well.

**Change.**
- `anyLive` adds Classify.
- A single queued refresh, with failure state and `usePipelineFailure()`.
- `StatusPill` shows the failure.
- `explain()` gets the three cases plus a development-only suffix.
- `tech-labels` sets loaded only on success and retries.

**Tests.**
- tsc, lint and build.
- The review harness, adjusted to resolve each fetch: expects two fetches.
- Read-only blocking of `/api/pipeline` and `/api/technologies/labels` in DevTools.
- A build pointed at a closed port, to see the 5xx wording.

**Docs.** Training Manual ch. 28: three rows for the new messages. Deployment Guide ch. 17 wording. Change log.

## 5. Acceptance for the whole piece

- All existing tests pass, plus every new test listed above.
- Lens: tsc, lint and a production build pass, including one build with no network.
- The review's own reproduction script, run on a test database, now records the expected results for CR01, CR02,
  CR03, CR04, CR05, CR06, CR11, CR12, CR13 and CR14. The frontend harness shows two fetches.
- A read-only walk of every screen on both addresses: same content as before; on the leaders' address, no request to
  a live endpoint.
- The perf check is unchanged: no screen call over 0.5 s.
- The documents and the change log are updated and re-rendered.
