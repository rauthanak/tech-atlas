# Sign-in, roles and "who did what": specification (v1)

What was agreed with Akshay on 25 Oct, checked against the code the same day. This says what the product does after
the change, what stays exactly as it is, how it is tested, and which client documents change. The order of work is in
`implementation-plan.md`.

## 1. Rules for this work

1. **Nothing that works today stops working.** Every screen, job, score, run and setting behaves as it does now, only
   behind sign-in. Section 3 lists every difference a person could notice; there are no others.
2. **Keep it simple.** No new dependencies, services, frameworks or sign-in providers. Passwords use Python's own
   `hashlib`; sessions live in MongoDB like everything else; the portal keeps its one build.
3. **Failures say why**, in plain words: a wrong password, a paused account, a switched-off account, a page that isn't
   for this role.
4. **Tests first-class.** The 441 existing tests stay green and keep testing what they test today. Every rule below
   gets its own test.
5. **Documents stay in step** (AGENTS.md).
6. **Never test on live.** Tests run on `tech_atlas_test*` databases only.

## 2. Scope

| ID | What | App |
|---|---|---|
| A1 | Accounts: name, email, role (admin or leader), password stored only as a slow salted hash | atlas |
| A2 | The first accounts come from the seed data and must change their password at first sign-in | atlas |
| A3 | Sign in, sign out, change password; a session lasts 12 hours | atlas + lens |
| A4 | Wrong passwords: after 5 in a row the account is paused for 15 minutes | atlas |
| A5 | Every API call is checked: signed in, and allowed for the person's role | atlas |
| A6 | One address for everyone: admins land on the portal, leaders on the leaders' view | lens + compose |
| A7 | Setup › People: admins add people, change roles, switch accounts off and on, set a temporary password | atlas + lens |
| A8 | "Made by": choices, setting changes, runs, imports and publishing record who did them | atlas + lens |
| A9 | The view counter counts leaders only, with who, and starts from zero | atlas + lens |

Not in scope:
- **Reset by email.** It stays off until Tata gives us a mail account. Until then the sign-in page says "Forgot your
  password? Ask a radar admin to set a temporary one." Adding it later is its own small piece of work: a mail
  setting, a one-time emailed link, one page and its tests.
- Self sign-up, domain rules, two-step codes, Google or Microsoft sign-in, password expiry.
- Anything the leaders see or do beyond what they do today.

## 3. Everything a person could notice

These are the intended differences. Nothing else should look or behave differently.

| Where | Today | After |
|---|---|---|
| Opening the radar | Opens at once | Sign-in page first; after signing in, the page asked for |
| First sign-in with a seeded or temporary password | — | "Choose a new password" before anything else |
| The leaders' view | Its own address (port 3200) | The same address as the portal. Leaders land on it; admins open it from **Leaders' view** in the top bar |
| A leader opening an admin page | Not possible (separate address) | "This part is for the radar team", with a link to the leaders' view |
| Top bar (portal and leaders' view) | No person | The person's name, with **Change password** and **Sign out** |
| Setup | Ends with Changes | **People** added under System, admins only |
| A technology's History | "By a person, 25 Oct 14:02" | "By Hasan Pasha, 25 Oct 14:02" (records from before sign-in keep "By a person") |
| Setup › Changes | "edited 25 Oct 14:02" | "edited 25 Oct 14:02 by Hasan Pasha" |
| Operations history, import page, last edition | When | When and by whom |
| View counter on a PoV (portal) | "Leaders opened it 3 times …; who isn't known until there's sign-in" | "Opened 3 times by 2 leaders (Ankur Jindal, …), last …; printed or saved as PDF 1 time". Admins' visits never count. Counting starts from zero at release |
| Leaders' PoV page, opened by an admin | Not possible on the portal's address | Shows as leaders see it, with a small note: "You're viewing as an admin: this visit isn't counted" |
| **Print / Save as PDF** | Counted on the leaders' address | Unchanged button; counted for leaders only |

## 4. The design

### 4.1 Accounts (A1, A2)

One collection, `accounts`, one record per person:

| Field | Meaning |
|---|---|
| `_id` | the email address, in lower case (the sign-in name; `Ankur.Jindal@` and `ankur.jindal@` are one person) |
| `name` | as shown in the portal |
| `role` | `admin` or `leader` |
| `password_hash` | `pbkdf2_sha256$<iterations>$<salt>$<hash>`, never the password |
| `must_change` | true for a seeded or temporary password |
| `disabled` | true when an admin switched the account off |
| `wrong_tries`, `paused_until` | the wrong-password pause (A4) |
| `last_signed_in`, `created_at`, `created_by`, `password_set_at` | for the People screen |

**Passwords.** PBKDF2-HMAC-SHA256 from Python's `hashlib`, a random 16-byte salt per password, 600,000 iterations
(today's common guidance), compared with `hmac.compare_digest`. It is SHA-256 underneath, but deliberately slow, so a
copy of the database can't be used to guess passwords quickly. Every password, new or temporary, is at least 8
characters.

**The first accounts** are in `seeds/accounts.json` (`{"accounts": [{email, name, role, password_hash}]}`). At start-up,
when the `accounts` collection is empty, each one is created with `must_change: true`. They are loaded once only: the
file is not part of Setup › Changes or Update seeding data, so later edits on the People screen are never overwritten
or listed as changes. The hash is made with one command, `uv run python -m app.services.accounts hash`, which asks for
the password without showing it and prints the hash. The person who runs it keeps the password and gives it out
verbally. Until a real hash is in the file, its placeholder simply never matches: sign-in fails with the usual
message, and nothing crashes.

**Recovery from the server** (for the day no admin can sign in): `uv run python -m app.services.accounts set-password
<email>` asks for a temporary password without showing it, and sets it on that account. It also sets `must_change`,
clears the pause and signs the person out everywhere, exactly like **Set a temporary password** on the People screen.
It is run where the radar runs (`docker compose exec atlas …`), so only someone with access to the server can use it.

| Name | Email | Role |
|---|---|---|
| Akshay Pratap Singh Rauthan | rauthan1@wharton.upenn.edu | admin |
| Hasan Pasha | hpasha@wharton.upenn.edu | admin |
| Nicholas Muchinguri | nickmuch@wharton.upenn.edu | admin |
| Joseph Nebistinsky | jneb@wharton.upenn.edu | admin |
| Scott Snyder | ssnyder6g@gmail.com | admin |
| Abhishek Nimbhorkar | abhishek.nimbhorkar@tatacommunications.com | admin |
| Shashank Manerikar | shashank.manerikar@tatacommunications.com | admin |
| Ankur Jindal | ankur.jindal@tatacommunications.com | leader |
| Akshay Rauthan (leaders' test) | rauthanak@gmail.com | leader |

### 4.2 Sessions and sign-in (A3, A4)

- **Sign in** (`POST /api/auth/sign-in` with email and password). On success, a random token (`secrets.token_urlsafe`)
  is made and only its SHA-256 is stored, in `sessions`, with the person's email, name, role, `must_change` and
  `expires_at` (12 hours from now, stored as a date, not as text, so MongoDB's clean-up can read it). The 12 hours
  run from sign-in; using the radar doesn't extend them. The browser gets one cookie, `radar_session`: HttpOnly, SameSite=Lax, Path=/, the
  same 12 hours, and Secure when the `SECURE_COOKIES` setting is on. Its value is `<role>.<token>`. The role in front
  is only so the portal can choose a landing page; the API never trusts it and reads the role from the session.
- **Wrong email or password**: "That email and password don't match." The same words either way, so the page can't be
  used to find out who has an account. It is a 400 answer, never a 401. A 401 always means "not signed in", and only
  a 401 sends the browser to the sign-in page (4.4), so a mistyped password stays on the form with its message. The
  same goes for a wrong current password on the change-password page.
- **Wrong tries**: each wrong password adds one to `wrong_tries`. At 5, the account is paused for 15 minutes ("Too many
  wrong passwords. Try again in 15 minutes, or ask a radar admin."). A right password resets the count.
- **Switched off**: "This account is switched off. Ask a radar admin." (only after a right password).
- **Must change**: sign-in succeeds, and the answer says `must_change`. Until the password is changed, every call
  except me, change password and sign out is refused with 403 "Choose a new password first."
- **Change password** (`POST /api/auth/password` with the current and the new one). The new one must differ from the
  current one and be at least 8 characters. It clears `must_change`, and signs the person out everywhere else (their
  other sessions are deleted; this one stays).
- **Sign out** (`POST /api/auth/sign-out`): the session is deleted and the cookie cleared.
- **Me** (`GET /api/auth/me`): name, email, role, must_change. The portal uses it for the top bar.
- Old sessions are removed by MongoDB on their own (a TTL index on `expires_at` in `seeds/indexes.json`); an expired
  one is refused even before that.
- Every sign-in endpoint answers with JSON, sign-out included (`{"signed_out": true}`), because the portal's request
  helper reads every answer as JSON.
- **Kept off the shared request loop.** Sign-in and change password are ordinary (`def`) endpoints, so the slow
  password check runs in the server's worker threads, not on the loop every request shares. That loop is what the
  last review fixes kept clear.
- **Cross-site requests**: SameSite=Lax stops other websites' pages from sending the cookie with a change, which
  covers the common case. That is enough for one internal site on its own address.

### 4.3 Every call is checked (A5)

One check, `auth.guard`, is added to the whole API (`FastAPI(dependencies=[Depends(auth.guard)])`), so no endpoint can
be forgotten. For each call:

1. Open to everyone: `GET /api/health` and `POST /api/auth/sign-in`.
2. No session, or an expired one: 401 "Sign in to continue." (the answer also clears the cookie).
3. `must_change`: only me, change password and sign out (403 otherwise).
4. A **leader** may make only the calls the leaders' view makes today. These are the lists from `proxy.ts`, moved into
   the API: `GET /api/frontier`, `GET /api/frontier/pov/{id}`, `GET /api/scoring/fabrics`,
   `GET /api/lists/mechanisms`, `GET /api/technologies/labels`, `POST /api/frontier/pov/{id}/seen`, plus me, change
   password and sign out. Anything else: 403 "This is for the radar team."
5. An **admin** may make every call.
6. The person is remembered for this call (a context variable), so "made by" can be recorded where things are saved
   (4.6) without passing a new argument through every function.

The guard itself is `async`, so the person it remembers reaches the endpoint. Its one database read, the session
lookup, runs with `await run_in_threadpool(...)`, the same pattern as the Setup refresh in `main.py`. The shared loop
never waits on MongoDB, and the person is still set in the request's own context.

Health stays open because it says only whether the database answers. The background worker and the command-line tools
don't go through the API and are unchanged.

### 4.4 One address (A6)

The portal is already one build. Today a setting (`APP_SIDE`) makes the second copy, on port 3200, the leaders' side.
After this change:

- The `frontier` container and port 3200 are removed from `docker-compose.yml`. The radar runs as four services:
  mongo, atlas, worker, lens.
- `proxy.ts` decides by the cookie:
  - `/sign-in` is always open;
  - with no `radar_session` cookie, any page goes to `/sign-in?next=<the page asked for>`;
  - `/` goes to `/admin` for an admin and to `/frontier` for a leader;
  - a leader asking for `/admin…` sees `/no-access` ("This part is for the radar team");
  - an admin may open `/frontier…`.

  The API calls pass straight through: the API decides (4.3).
- The **Leaders' view ↗** link in the top bar opens `/frontier` on the same address, in a new tab as today.
  `NEXT_PUBLIC_FRONTIER_URL` is no longer needed.
- Pages already decide their admin or leader rendering by where they are (`/admin` or `/frontier`), not by
  `APP_SIDE`, so an admin on `/frontier` sees exactly what leaders see.
- `lib/api.ts`:
  - a **401** sends the browser to `/sign-in?next=<this page>`, once even when several calls fail together;
  - a **403** "Choose a new password first" sends it to `/account/password`;
  - in both cases the call still fails for the page that made it. A save that meets an expired session therefore
    never shows "Saved" or runs what follows a success;
  - every other error (a wrong password is a 400) reaches the page as today, so the sign-in and password forms show
    their own messages.

  Every page loads its data through `lib/api.ts`, so no page needs its own handling. The exception is the leaders'
  PoV page's "seen" call, which is fire-and-forget and stays as it is.
- **A change of person reloads the whole page.** After signing in, after signing out and after changing a password,
  the portal goes to its next page with a full page load (`window.location`), not an in-app link. Nothing the last
  person loaded (their name, the screens' remembered answers) stays in the tab.

New pages (outside `/admin` and `/frontier`, with the plain brand header):
- `/sign-in`: email, password, **Sign in**, and the line about asking an admin. It goes to `next` only when that is a
  path on this site (it starts with a single `/`; `//…` and full addresses are ignored), else to `/`. When
  `must_change` is set, it goes to `/account/password` first, then on to `next`.
- `/account/password`: current password, new password, the new one again. When forced, it says so: "Choose a new
  password to go on. Until you do, the password you were given opens only this page."
- `/no-access`.

### 4.5 People (A7)

Setup › System › **People** (`/admin/people`), admins only. It is a table with name, email, role, status (active,
must choose a new password, paused until …, switched off) and last signed in. The actions:

- **Add a person**: name, email, role, temporary password. The person must change it at first sign-in. An email
  already there is refused, with the reason.
- **Change role**.
- **Switch off / Switch on**.
- **Set a temporary password**: for someone who forgot theirs. It sets `must_change` and clears the pause.

A new role or a switch-off signs that person out (their sessions are deleted), so it takes effect at once. A new name
shows from the person's next call, with no sign-out. An admin can't change their own role or switch themselves off, so nobody can lock everyone out
by accident; the row says why. The API is `GET/POST /api/accounts`, `PUT /api/accounts/{email}` (name, role, disabled)
and `POST /api/accounts/{email}/password`. Nothing is ever shown or stored in a form the password could be read from.

### 4.6 Made by (A8)

`auth.by()` gives `{"email", "name"}` of the person making this call, or None (a test, the command line, the
radar's own background work). It is stored as `by`:

| What | Where it's stored | Where it shows |
|---|---|---|
| A choice (move, commitment, watch, …) | `decisions.by` (the field exists and is always None today) | the technology's History: "By Hasan Pasha, …" |
| A setting change | `updated_by` next to every `updated_at` an edit writes (lists, scoring, signals, prompts, sources, settings, technologies) | Setup › Changes: "edited … by Hasan Pasha" |
| A run started (collection, assessment, Classify, PoVs, Find evidence, tagging, Check again, linking names) | `by` on the run's own record | Operations history |
| An import uploaded / confirmed | `by` / `confirmed_by` on the import | the import page |
| An edition published | `by` on the edition | the Briefing's last edition line |

Jobs: `jobs.start` and `jobs.later` copy `auth.by()` onto the job line, and the worker runs the job as that person. A
run record written inside a job therefore records the same person, whether the job runs in the worker or in a thread.
`updated_by` is not a seeded field: the Changes comparison, Put back and Update seeding data ignore it, as they do
`updated_at`. Records made before the release have no `by` and show as they do today.

"Made by" records **who did it last**: who made a choice, who last edited a setting, who started a run. It is not a
complete history of every edit, and a deleted setting has no record left to carry a name.

### 4.7 The view counter (A9)

- `POST /api/frontier/pov/{id}/seen` records a visit only when the person is a leader, with `by` (email and name).
  For an admin it answers as now and records nothing.
- `editions.views()` counts only visits with `by`. Visits recorded before the release (anonymous, possibly ours)
  stay in the database and are not counted: the count starts from zero, and nothing is deleted.
- Each technology returns what it does today (`opened`, `printed`, `last_opened`) plus `leaders`: one row per leader,
  with name, opened, printed and last opened, the most recent first. Admins see the names; leaders never see the
  counter.
- The portal shows: "Opened 3 times by 2 leaders (Ankur Jindal, …), last …; printed or saved as PDF 1 time. Admins'
  visits aren't counted." The PoV list shows the same numbers it shows today, from the leaders-only count.
- **Print / Save as PDF** stays as it is. A print is counted by the browser's print event, as today.

## 5. What stays exactly as it is

- Every screen's content, every job, score, run, PoV, edition and setting.
- What the leaders see, and the published-data-only boundary for them.
- The seed data and the Changes tab for configuration.
- The background worker, the command-line tools, the scale copy's own stack.
- Upload limits, time zones, the error wording (beyond the new sign-in messages).

## 6. Settings

| Setting | Where | Default | Meaning |
|---|---|---|---|
| `SECURE_COOKIES` | atlas `.env` / compose | `false` | `true` once the radar is behind HTTPS (the Deployment Guide says so); the cookie is then sent only over HTTPS |

Nothing else is configurable. The 12-hour session, 5 tries, 15-minute pause and 8-character minimum are constants in
`services/auth.py`.

## 7. Tests

The existing tests call the API without signing in. `tests/conftest.py` gains one automatic fixture that signs every
test call in as a test admin (an override of `auth.guard`). Every existing test therefore runs exactly as today. The
sign-in tests turn the override off.

New tests:
- `test_passwords.py`: hash and verify; a different salt each time; a wrong password fails; the stored hash never
  contains the password.
- `test_sign_in.py`:
  - sign-in sets the cookie, and wrong email or password gives the same message, as a 400 (never a 401);
  - the session's `expires_at` is stored as a date;
  - every sign-in endpoint answers with JSON;
  - the pause after 5 wrong tries, and the count resetting;
  - a switched-off account;
  - an expired session;
  - sign-out;
  - must-change blocks everything but me, password and sign-out;
  - change password signs out the person's other sessions.
- `test_roles.py`:
  - every API route is either open, admin, or on the leaders' list. This test walks `app.routes`, so a new endpoint
    can't slip through unnoticed;
  - a leader gets 403 on an admin call and 200 on each leaders' call;
  - no session gives 401;
  - while a slow session read is held, `/api/health` still answers (the guard doesn't block the loop).
- `test_people.py`:
  - add, with a duplicate refused;
  - role change and switch-off sign the person out;
  - an admin can't demote or switch off themselves;
  - a temporary password sets must_change and clears the pause;
  - `set-password <email>` from the command line does the same, and signs the person out.
- `test_accounts_seed.py`:
  - the first start creates the seeded accounts with must_change;
  - a second start changes nothing;
  - accounts never appear in Changes;
  - the placeholder hash never matches and doesn't raise an error.
- `test_made_by.py`:
  - a choice, a setting change, an import, a publish and a run started through the API record the person;
  - a job run by the worker records the person who started it;
  - `updated_by` doesn't show up as a change.
- `test_view_counter.py`:
  - a leader's visit counts, with their name;
  - an admin's doesn't;
  - old anonymous visits aren't counted;
  - the per-leader rows.

Portal: `npm run lint`, `npx tsc --noEmit` and `npm run build`. A walk of every screen signed in as an admin and as a
leader (read-only; it only opens pages) checks that each screen loads, a leader is refused every admin page, and an
admin can open the leaders' view. By hand, on the local run:
- a wrong password stays on the form;
- a save after the session is deleted shows the failure and lands on sign-in;
- signing out as an admin and in as the leader in the same tab shows nothing of the admin's;
- `next=//example.com` is ignored.

## 8. Client documents

| Document | Change |
|---|---|
| Training Manual | New chapter "Signing in and managing people": sign in, first sign-in, change password, forgot password, People. The leaders' view now opens from the top bar on the same address. The counter's new wording; "made by" in History, Changes and Operations. New screenshots: sign-in, choose a new password, People |
| Product Guide | Who can use the radar and what each role sees; one address; who did what; the leaders-only counter |
| Deployment Guide | Four services, not five; one address to put behind HTTPS; `SECURE_COOKIES`; the first accounts and passing out the starting password; the after-deployment checks sign in first |
| Technical architecture | The separate leaders' container goes; the portal routes by role; sign-in at the API |
| Business process | No change: the steps and checkpoints are the same, only who may do them is now enforced |
| Performance report | No change: no new measurements |
| Change log | Change 53 |

## 9. Risks and how each is covered

| Risk | Cover |
|---|---|
| A cookie set by the API doesn't reach the browser through the portal's `/api` forwarding | Checked first, in Phase 0, before any other code |
| The person isn't known inside a sync endpoint (the context variable doesn't reach the thread) | A Phase 0 test, before building on it |
| An endpoint left open by mistake | The route-walk test in `test_roles.py` fails the build |
| Locking everyone out | No self-demotion or self-switch-off; seven admins; `set-password <email>` on the server sets a temporary password for any account (4.1) |
| Slow password checks or session reads holding up other requests | Hashing runs in `def` endpoints; the guard reads the session through the threadpool (4.2, 4.3) |
| A save after the session expired looks successful | A 401 still fails the call; only then does the browser go to sign-in (4.4) |
| One person's data left on screen for the next | Sign-in, sign-out and password change reload the whole page (4.4) |
| The old leaders' container can't be stopped once compose no longer lists it | Phase 8 stops and removes it first, by its container name |
| Replacing the worker while a job runs | Phase 8 starts only when Operations shows nothing running |
| The checks and screenshot scripts stop working | They sign in first, with an account from the environment (Phase 6) |
| Live release changes access for everyone at once | A backup first; release only with Akshay's go-ahead; the starting password is ready before release |
