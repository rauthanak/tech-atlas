# Sign-in, roles and "who did what": implementation plan (v1)

The order of work for `specification.md`. Each phase ends green: the full test suite passes before the next phase
starts.

## Ground rules for every phase

- No new dependencies, in either app.
- Change only what the specification lists. If something else looks wrong on the way, write it down; don't fix it.
- Tests run with `TEST_MONGO_DB=tech_atlas_test_<name>` on the brew MongoDB. Never against live.
- Reuse what's there: `request_tz`'s dependency pattern, the `lib/api.ts` request path, the Setup side menu, the
  existing table and button styles.
- Plain words in every message a person reads.

## Phase 0: baseline and two checks before building (about 1 h)

1. Run both test suites and record the baseline in `checks/baseline.md`:
   - atlas `uv run pytest`, expected 441 passing;
   - lens `npm run lint`, `npx tsc --noEmit`, `npm run build`.
2. **Cookie through the portal's forwarding.** On a scratch branch:
   - add a throwaway endpoint that sets a cookie;
   - call it through `npm run dev` on `/api/...`;
   - confirm the browser receives the `Set-Cookie`, and that the next request carries it to the API.

   If it doesn't, stop and report: the design depends on it. Remove the throwaway endpoint.
3. **The person reaches the endpoint.** A throwaway test: an `async` dependency sets a context variable, and a sync
   (`def`) endpoint reads it through `TestClient`. It must see the value. Same rule: stop and report if not.
4. Back up live with
   `docker compose exec mongo mongodump --archive --gzip > docs/2026-10-25/backup/tech_atlas-before-sign-in.archive.gz`
   (gitignored, like the last one).

## Phase 1: accounts and passwords (about 2 h)

**atlas**
- `src/app/services/db/mongo.py`: add `accounts` and `sessions` to `COLLECTIONS`.
- `src/app/services/accounts.py` (new, about 120 lines):
  - `hash_password(pw)` and `check_password(pw, stored)`, using PBKDF2-SHA256, `ITERATIONS = 600_000` and
    `MIN_LENGTH = 8`;
  - `seed_if_empty()`, which reads `seeds/accounts.json` when `accounts` is empty and creates each account with
    `must_change: true`;
  - `set_temporary(email, pw)`, which sets the hash, `must_change`, clears the pause and deletes that person's
    sessions. The People screen and the command line both use it;
  - `__main__`, with two commands:
    - `hash` asks for the password twice with `getpass` and prints the hash;
    - `set-password <email>` asks the same way and calls `set_temporary`, saying "No account <email>" when there
      isn't one.
  - A stored hash that isn't in the `pbkdf2_sha256$…` form (the placeholder) simply doesn't match: `check_password`
    returns False and never raises.
- `src/app/services/db/bootstrap.py`: in `run()`, call `accounts.seed_if_empty()` after `seeding.load_if_new()`.
- `seeds/accounts.json`: the nine accounts from the specification (4.1). The hash comes from Akshay running the
  `hash` command (see "What I need from you"). Until then, the placeholder `"not-set"`, which can't match any
  password.
- `seeds/indexes.json`: a TTL index on `sessions.expires_at` (`expireAfterSeconds: 0`).

**Tests:** `test_passwords.py` and `test_accounts_seed.py`, including the placeholder and `set-password`. Speed: tests set `accounts.ITERATIONS` low through a
fixture, so the suite doesn't slow down.

## Phase 2: sign-in and the check on every call (about 3 h)

**atlas**
- `src/app/services/auth.py` (new, about 150 lines):
  - `SESSION_HOURS = 12`, `TRIES = 5`, `PAUSE_MINUTES = 15`;
  - `CURRENT: ContextVar`, plus `by()` and `acting_as(person)` (a context manager used by jobs);
  - `sign_in(email, pw)`, which applies the messages and the pause of spec 4.2 and returns `(token, session)`.
    `expires_at` is a `datetime` (UTC), not `now_utc()`'s text, so the TTL index works. A wrong email or password
    raises 400;
  - `session_for(token)`, `sign_out(token)`, `change_password(session, current, new)`,
    `sign_out_everywhere(email, except_token=None)`;
  - `LEADER_CALLS`: (method, path pattern) pairs moved from `proxy.ts`, plus the three own-account calls;
  - `OPEN = {("GET", "/api/health"), ("POST", "/api/auth/sign-in")}`;
  - `async def guard(request)`, which applies the steps of spec 4.3 in order:
    - it reads the session with `await run_in_threadpool(session_for, token)`, so the loop never waits on MongoDB;
    - it raises `HTTPException` with the reason (the 401 also carries a header that clears the cookie);
    - it sets `CURRENT` in the request's own context.
- `src/app/api/auth.py` (new): `sign-in`, `sign-out`, `me`, `password`.
  - All four are plain `def` endpoints, so hashing runs in the threadpool.
  - All four answer with JSON; sign-out answers `{"signed_out": true}`, even with no or an expired cookie.
  - The cookie options are in one helper; Secure comes from `SECURE_COOKIES`.
- `src/app/settings.py`: `self.secure_cookies`, read like `jobs_in_worker`.
- `src/app/main.py`:
  - `FastAPI(..., dependencies=[Depends(auth.guard)])`;
  - include the auth router;
  - a comment saying why the guard is app-wide.

**Tests**
- `tests/conftest.py`: an autouse fixture that sets `app.dependency_overrides[auth.guard]` to an `async` function
  setting `CURRENT` to a test admin, removed after each test. A marker, `@pytest.mark.real_sign_in`, skips the
  override for the sign-in tests.
- `test_sign_in.py` and `test_roles.py`:
  - the route walk;
  - the 400-not-401 rule;
  - JSON answers;
  - `expires_at` stored as a date;
  - health still answers while a session read is held up (a monkeypatched slow `session_for`).
- Then the full suite: 441 plus the new tests, all green.

## Phase 3: People (about 1.5 h)

**atlas**
- `src/app/api/accounts.py` (new):
  - `GET /api/accounts` returns the list, with no hashes;
  - `POST /api/accounts` adds a person;
  - `PUT /api/accounts/{email}` changes name, role or disabled;
  - `POST /api/accounts/{email}/password` sets a temporary password, through `accounts.set_temporary`.

  It applies the self-protection rule, and signs the person out on any change (spec 4.5). It is admin-only through
  the guard.
- `main.py`: include the router.

**Tests:** `test_people.py`.

## Phase 4: made by (about 2.5 h)

**atlas**
- `services/decisions.py:207`: `"by": auth.by()`. Undoing keeps the original `by`, and adds `undone_by`.
- `updated_by: auth.by()` beside each `updated_at` an edit writes:
  - `api/lists.py` (98, 114, 245);
  - `api/scoring.py` (26);
  - `api/signals.py` (102, 120, 131);
  - `api/prompts.py` (102);
  - `api/sources.py` (99);
  - `api/settings.py` (43, 82);
  - `api/technologies.py` (363, 365, 382, 461, 516).

  `scoring.py`'s `PROTECTED_KEYS` gains `updated_by`.
- `services/db/seeding.py`: `changes()` rows carry `updated_by`. `NOT_COMPARED` is untouched: it compares only seeded
  fields, and `updated_by` is never one (checked by a test).
- Runs: `"by": auth.by()` on the record each run writes:
  - `services/runs/store.py:40`;
  - `agent/analyzer/engine.py:54`;
  - `agent/classifier/classify.py:305`;
  - `agent/find_evidence/job.py:114`;
  - `agent/tagger/tagger.py:280`;
  - `agent/analyzer/pov.py:518`;
  - `services/signals/recheck.py:67`;
  - `agent/resolver/resolver.py:91`.
- `services/jobs.py`:
  - `start()` and `later()` store `"by": auth.by()` on the job line;
  - `run()` wraps the call in `auth.acting_as(job.get("by"))`;
  - the thread path starts the thread with `contextvars.copy_context().run`, so a thread sees the same person.
- Imports: `services/imports.py` `create()` stores `by`; `confirm()` stores `confirmed_by`.
- Editions: `services/editions.py` `publish()` stores `by` on the edition and returns it in `summary()`.
- `_about()` in `api/usage.py`, `runs.list_runs` and `scoring_runs.list_runs` already return the run records, so
  `by` comes through with no change. Check each and add it to a projection only where one leaves it out.

**Tests:** `test_made_by.py`.

## Phase 5: the view counter (about 1 h)

**atlas**
- `api/frontier.py` `seen()`: record only when `auth.by()` is a leader. The role is read from the session, through a
  small `auth.role()`.
- `services/editions.py`:
  - `record_view(tech_id, kind, by)` stores `by`;
  - `views()` matches `{"by": {"$ne": None}}` and also groups by `by.email` to build `leaders`, returning `opened`,
    `printed` and `last_opened` exactly as now, plus `leaders`;
  - the docstrings are updated.

**Tests:** `test_view_counter.py`. Check that `test_pov_list.py` still passes unchanged.

## Phase 6: the portal, compose and scripts (about 5 h)

**lens**
- `proxy.ts`: rewritten to the rules in spec 4.4, about the same length as today. The `APP_SIDE` branch, the
  `FRONTIER_READS` list and the 403 move to the API.
- `lib/api.ts`, in `request()`:
  - a 401 sends the browser to `/sign-in?next=<here>`, unless it is already on `/sign-in`. A module-level flag makes
    several failing calls send it only once;
  - a 403 with the "Choose a new password first" reason sends it to `/account/password`, once, the same way;
  - in both cases `request()` still throws, so a caller awaiting a save never treats it as done. Pages are left as
    they are, since the browser is already leaving;
  - every other status is thrown exactly as today. A wrong password is a 400, so `/sign-in` and
    `/account/password` show the API's message on their own form.
- `lib/me.ts` (new): `useMe()`, which fetches `/api/auth/me` once per page load (module cache).
- `app/sign-in/page.tsx`, `app/account/password/page.tsx`, `app/no-access/page.tsx` (new).
  - After signing in, after a password change, and on **Sign out**, the page moves on with
    `window.location.assign(...)`: a full page load, so module caches (`useMe`, tech labels, pipeline, changes count)
    start empty for the next person.
  - `next` is followed only when it starts with `/` and not `//`; otherwise it goes to `/`.
  - A forced password change carries `next` through. Each has a small shared
  header, `components/PlainHeader.tsx`, styled like the leaders' header.
- `components/PersonMenu.tsx` (new): the name, **Change password** and **Sign out**. Used in `TopBar.tsx` and in
  `app/frontier/layout.tsx`.
- `TopBar.tsx`: **Leaders' view ↗** links to `/frontier`. `NEXT_PUBLIC_FRONTIER_URL` is removed.
- `app/admin/(setup)/people/page.tsx` (new), and the **People** entry under System in `(setup)/layout.tsx`.
- "Made by" shown:
  - `TechHistory.tsx:83`: "By {by.name}" when `by` is set, else "By a person";
  - `(setup)/changes/page.tsx:230`: " by {updated_by.name}";
  - `OperationsHistory.tsx:162`;
  - `app/admin/import/page.tsx:119`, plus the confirmed line;
  - `PublishEdition.tsx:61`.
- `LeadersSee.tsx`: the new counter wording and the leaders' names. The "who isn't known until there's sign-in"
  line goes.
- `app/frontier/pov/[id]/[tech]/page.tsx`: the note for an admin, using `useMe()`. The `seen` calls stay as they are,
  and the comment is updated.
- `README.md`: one address; the leaders' view at `/frontier`.

**atlas compose and scripts**
- `docker-compose.yml`:
  - remove the `frontier` service;
  - `SECURE_COOKIES` on atlas, default `false`, with a one-line comment;
  - the header updated (four services).
- `README.md`: the first accounts, the `hash` command, `SECURE_COOKIES`.
- The read-only scripts sign in first, with `RADAR_CHECK_EMAIL` and `RADAR_CHECK_PASSWORD` from the environment,
  never stored:
  - `checks/` (the screen walk and the speed check);
  - `final_deliverable/training-manual/take_screens.py`.

**Checks:** lint, typecheck and build. A local run with `npm run dev` and the atlas API on a test database:
- sign in as an admin and as a leader;
- the forced password change;
- every admin screen loads for the admin;
- every admin page gives no-access for the leader;
- the leaders' view works for both;
- the counter counts the leader only.

## Phase 7: whole-piece regression and documents (about 3 h)

1. atlas full suite, which must be every old test plus the new ones, all green. Then the lens lint, typecheck and
   build.
2. Grep for leftovers: `APP_SIDE`, `3200`, `NEXT_PUBLIC_FRONTIER_URL`, `FRONTIER_READS`.
3. Documents (spec section 8):
   - Training Manual: the new chapter, the edits and the three screenshots;
   - Product Guide;
   - Deployment Guide;
   - architecture (`architecture.html` and `architecture()` in `make_classic.py`, then `make_png.py`);
   - change log entry 53 in `make_change_log.py`.

   Re-render each with `build_pdf.py`. Screenshots come from a local run on a copy, signed in, only opening pages.

## Phase 8: release to live (needs your go-ahead; about 1 h)

1. **Nothing running.** Operations shows no run in progress and no queued job
   (`docker compose exec mongo mongosh tech_atlas --quiet --eval 'db.jobs.countDocuments({status:{$in:["queued","running"]}})'`
   is 0). If something is running, wait for it to finish; never stop it.
2. The backup from Phase 0, or a fresh one if live changed since.
3. `docker compose build atlas worker lens`. The running containers are untouched while it builds.
4. **The old leaders' container, by its container name**, because the new compose file no longer lists it:
   `docker stop tech-radar-frontier-1`, then `docker rm tech-radar-frontier-1`. Nothing else is touched.
5. `docker compose up -d mongo atlas worker lens`.
6. Check:
   - `/api/health` is OK;
   - `docker ps` shows four containers, with no `frontier`;
   - the nine accounts were created;
   - Changes still shows 0;
   - sign in as an admin, and every screen loads;
   - sign in as the leaders' test account: the leaders' view loads, and admin pages show no-access;
   - the counter shows zero and counts the test leader's visit;
   - the speed check (16 calls) is as before.
7. Tell everyone their starting password, in person.

## What I need from you

- **The starting password:** before Phase 8 (Phase 1 can use a placeholder). You run
  `cd tech-atlas && uv run python -m app.services.accounts hash` and paste me the printed hash (not the password),
  or put it into `seeds/accounts.json` yourself. One starting password for everyone is fine: each person must change
  it at first sign-in.
- **The go-ahead for Phase 8.**

## The design review (review-comments.md)

Assessed with Akshay on 25 Oct.

**Taken into this plan:**
- S17: the release order, and nothing may be running;
- S02: `set-password` on the server;
- S06: the guard and hashing are kept off the shared loop;
- S07: a wrong password is a 400, and a 401 still fails the call;
- S08: a full page load when the person changes, and a safe `next`;
- S10: `expires_at` stored as a date;
- S11: the placeholder hash never matches and never errors;
- wording fixes to S01, S03, S12 and S18.

**Not taken:** the rest. The radar is for nine named internal people, and those comments are written for a public,
internet-facing service:
- per-person expiring starting passwords;
- last-admin protection under simultaneous edits;
- anti-forgery tokens;
- session revision numbers and token rotation;
- 15-character passwords, common-password lists and per-network throttling;
- a full audit log;
- edition-scoped leader data, which would change what leaders read today;
- nested-thread identity;
- separate scale-test identities;
- de-duplicating views;
- rollback rehearsal.

## Effort

| Phase | Hours |
|---|---|
| 0 Baseline and checks | 1 |
| 1 Accounts and passwords (with `set-password`) | 2.5 |
| 2 Sign-in and the check (off the loop, 400 vs 401) | 3.5 |
| 3 People | 1.5 |
| 4 Made by | 2.5 |
| 5 View counter | 1 |
| 6 Portal, compose, scripts | 5 |
| 7 Regression and documents | 3 |
| 8 Release | 1 |
| **Total** | **about 21 h of my work** |

## Progress

| Phase | Status |
|---|---|
| 0 | done: baseline 441; both checks passed (checks/baseline.md); live backed up |
| 1 | done |
| 2 | done (the route walk reads the app's schema: this FastAPI nests included routers) |
| 3 | done (a name-only change keeps the person signed in; spec 4.5 updated) |
| 4 | done |
| 5 | done (one existing test now makes its visits as a leader, as agreed) |
| 6 | done; local run on a restored copy passed every check (checks/local-run.md) |
| 7 | done: 484 tests pass; lint, typecheck and build clean; documents updated and rendered |
| 8 | done 26 Oct: released; signed-in checks on live with two temporary accounts (deleted after): roles, Changes 0, 42 screens, speed 0 of 16 over 0.5 s (checks/perf-live-after-release.txt) |
