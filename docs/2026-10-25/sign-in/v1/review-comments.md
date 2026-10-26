# Sign-in design review v1

Review of [specification.md](specification.md) and [implementation-plan.md](implementation-plan.md), checked against the current Tech Atlas and Tech Lens code.

## Assessment

The approach fits the existing product: opaque server-side sessions, slow salted password hashes, authorization in Atlas, a common portal address, and explicit attribution. Keeping email password recovery outside this release is reasonable. Administrator-assisted recovery can cover it, provided the operational recovery path is complete.

I would clarify the items below before implementation. They are specification gaps and integration risks, rather than claims that the proposed authentication implementation already contains these bugs. The local probes use a synthetic FastAPI application and do not access the application database or running services. The two original drafts are unchanged.

Keep the proposed PBKDF2-HMAC-SHA256 implementation, unique salts, constant-time comparison, hashed session tokens and server-side expiry checks. The stated PBKDF2 work factor is consistent with the relevant [OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#pbkdf2). There is no need to add a framework simply to address this review.

**P1** below means resolve the design or acceptance condition before the affected authentication capability is released. **P2** means make the behavior explicit and include it in implementation/testing. Neither label represents a confirmed deployed authentication incident.

## Priority comments

### S01 P1 Give every person a different starting password

**References:** specification lines 81-86; implementation plan lines 223-226.

The plan explicitly permits one starting password for everyone. Anyone given that password could sign in using another person's listed email and choose that person's permanent password first, including an administrator account. Requiring a password change does not establish which person performed it.

Use a unique randomly generated temporary password for each account, delivered to that person through an agreed independent channel. Give temporary credentials an expiry. Keep production credential hashes in an access-controlled bootstrap input rather than a reusable committed seed file or distributed image; a hash is still sensitive password-verification material. Names and roles can remain a template.

Also correct “the one you were given works only once”: `must_change` alone permits repeated sign-ins until a change succeeds. Define whether it is genuinely single-use, or describe it accurately as a temporary password that grants only access to password change.

**Acceptance:** One person's temporary password fails for every other account. Expired temporary credentials cannot sign in. Repeated/concurrent first sign-ins have a defined outcome.

### S02 P1 Complete recovery without email and protect the last usable administrator

**References:** specification lines 180-185 and 299; implementation plan Phase 1.

The risk table says the hash command provides recovery for any account. The planned command only prints a hash; it does not update an account, clear a pause, set forced change or revoke sessions. If every admin is locked out or has forgotten a password, the specified recovery workflow is incomplete.

Add a server-console management command such as `reset-password --email ...`, using a hidden password prompt, an explicit database target, session revocation, pause clearing, forced change and an audit record. Document who is allowed to run it and how an admin verifies the person's identity before a normal temporary-password reset. Email delivery is unnecessary.

Preventing self-demotion/switch-off is useful, but does not by itself guarantee a usable administrator remains: two administrators can disable or demote each other concurrently, and all administrators can lose credentials. Protect the last enabled administrator as an invariant, including concurrent requests, while retaining console recovery.

**Acceptance:** Recover when every normal admin login is unusable, on disposable data. Concurrent cross-demotion/switch-off cannot remove all enabled administrators.

### S03 P1 Specify CSRF protection and make HTTPS a release condition

**References:** specification lines 104-106, 121 and 230; implementation plan lines 64-65 and 175.

“SameSite=Lax means another website can't make a signed-in change” is too strong. Same-site and same-origin are different; sibling applications on a shared domain can be same-site. The application also accepts multipart uploads and several writes without a JSON body, so requiring JSON on the login endpoint would not protect the whole API. [OWASP describes SameSite's limits and additional CSRF controls](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#limitations-of-samesite).

Choose an explicit policy for all unsafe methods, including sign-in, password change, logout and People: a session-bound CSRF token, or a carefully defined origin/header policy appropriate to the deployed topology. Define missing/null origins, CLI clients and trusted forwarding headers. If validating the browser's origin, compare against the intended public origin; the rewritten backend address can be `http://atlas:8100`, which is different from the browser's HTTPS address.

Local HTTP with insecure cookies can remain a development mode. Shared deployment must require HTTPS and Secure cookies, host-only scope, exact cookie deletion attributes and suitable cache controls. Do not leave this as a setting someone may forget to turn on. The scope restriction to one configurable setting may need a small amendment if the chosen CSRF policy needs the public origin.

**Acceptance:** Cross-origin JSON, multipart and bodyless writes are refused; intended browser and scripted calls work through the production forwarding path. Secure cookie creation, rotation and deletion are tested there.

### S04 P1 Make session revocation race-safe and rotate after password change

**References:** specification lines 102-106, 112-116 and 182-183; implementation plan lines 57-59.

The session copies role and `must_change` from the account, while a role/password/account change revokes existing sessions by deletion. There is a race: sign-in reads an old admin role, another admin demotes the account and deletes sessions, then the original sign-in inserts a new session carrying the old role. That session may remain privileged for the full lifetime. Password reset and account disabling have analogous races.

Use an account authentication revision, or equivalent current-account validation. Sessions must match the account's current revision and enabled state. Credential/role/disable changes must make sessions issued from an older revision unusable even if they are inserted after a deletion sweep.

The current session should receive a fresh token after changing a password, with `must_change` cleared, rather than retaining an unchanged restricted token. Specify the new token's expiry and invalidate its predecessor. [OWASP recommends session renewal on password/privilege changes](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html#renew-the-session-id-after-any-privilege-level-change).

**Acceptance:** Interleave sign-in with demotion, disabling, password reset and password change. No session with stale privileges or an old credential revision can authorize a later request. Concurrent password changes have one defined winner.

### S05 P1 Strengthen the password and guessing policy

**References:** specification lines 76-79 and 107-116; implementation plan lines 37-38 and 55-57.

Eight characters is a weak default for this password-only design, especially with administrators who can reset other accounts. Current [NIST SP 800-63B guidance](https://pages.nist.gov/800-63-4/sp800-63b.html#passwordver) calls for at least 15 characters for single-factor passwords and support for at least 64. This is a design recommendation here, not a claim that NIST compliance is contractually required. Permit passphrases and password managers; add a common-password check and sensible input upper bounds. Changing algorithms is not necessary to improve this policy.

The pause also needs precise semantics: does the attempt count reset when the pause expires, do attempts while paused extend it, and how does an admin unlock an account without changing its password? Make counter transitions atomic. Add a bounded per-origin/network or overall sign-in throttle as well as the account counter; per-account pausing alone permits password spraying and deliberate lockout of known administrators.

Unknown accounts should perform comparable password-hash work and receive comparable errors/statuses, so timing or paused-account responses do not undermine the generic wrong-credentials message. Apply guessing controls to current-password verification too. Define recent reauthentication for particularly sensitive People actions such as resetting another administrator's password.

**Acceptance:** Concurrent wrong/right attempts, pause expiry, unknown emails, malformed hashes, oversized passwords and repeated sensitive actions behave predictably without excessive CPU work or account enumeration.

### S06 P1 Keep authentication's blocking work off the event loop

**References:** implementation plan lines 54-65; existing [main.py](../../../../src/app/main.py) and [mongo.py](../../../../src/app/services/db/mongo.py).

The proposed guard is async, but the existing database client is synchronous. A direct MongoDB lookup inside that guard blocks the event loop on every request. Password hashing in an async sign-in/password handler would do the same during its expensive work. This could reintroduce the blocking behavior removed during the earlier review fixes.

Use the existing threadpool pattern for blocking database/hash work, or synchronous endpoints for the appropriate operations. Keep the request's actor ContextVar assignment/reset in the async request context after retrieving the principal; a value set only inside a worker thread does not automatically propagate back to its caller. Bound concurrent expensive verification work.

**Acceptance:** Slow session lookup and concurrent real-cost hash checks do not prevent health and ordinary requests from progressing. At least one test checks the real production hash cost configuration rather than lowering it globally.

### S07 P1 Define the browser error contract before changing `lib/api.ts`

**References:** specification lines 161-162; implementation plan lines 148-152; existing [api.ts](../../../../../tech-lens/lib/api.ts) and [ActButton.tsx](../../../../../tech-lens/components/ActButton.tsx).

The rule “a 401 redirects; neither is thrown” is incomplete. Wrong credentials at `/sign-in` must be returned to the form as an error. The password page must display a wrong-current-password error rather than redirect to itself. A request that redirects must never resolve as if a mutation succeeded: current callers await `sendJson()` and then show success or run `onDone()`.

Define stable machine error codes, separately from human wording, for unauthenticated, invalid credentials, password-change-required, paused, disabled, insufficient role and unavailable authentication storage. Reserve redirection for the relevant codes. Define a cancelled/redirected request outcome, coalesce simultaneous redirects, and handle sign-out idempotently even with an expired cookie.

Also specify successful auth response bodies: the shared helper always calls `response.json()`, so a 204 response must be handled explicitly or the auth endpoints should return JSON. There is an existing raw `fetch()` for the seen event in the leaders' PoV page, so “every call uses lib/api.ts” is not completely accurate.

**Acceptance:** Wrong login/password errors stay on the correct form. Expired-session mutations never report success. Many simultaneous 401 responses produce one redirect. JSON and empty response contracts work as defined.

### S08 P1 Clear identity-dependent client state and treat cookie roles only as hints

**References:** specification lines 149-166; implementation plan line 153; existing [pipeline.ts](../../../../../tech-lens/lib/pipeline.ts), [changes.ts](../../../../../tech-lens/lib/changes.ts), [tech-labels.ts](../../../../../tech-lens/lib/tech-labels.ts).

The proposed `useMe()` module cache needs explicit invalidation on sign-in, password change, logout and account revocation. Existing module caches and in-flight requests also survive ordinary client navigation. Signing out one person and signing in another in the same tab must not retain the old name, role, admin data or request results.

A full document navigation after identity transitions is a simple way to reset these stores; otherwise reset them deliberately and key authenticated data by identity/revision. Use no-store behavior for identity/session responses and appropriate private-data caching controls. Test browser Back, multi-tab logout and an old response arriving after account switching.

The cookie's role prefix is expressly untrusted, which is correct. Define malformed, forged and stale prefixes as navigation hints only; they must not cause redirect loops or grant data access. Validate `next` with a same-origin URL parser, rejecting external/protocol-relative destinations and choosing a role-appropriate fallback. Preserve an allowed deep link through forced password change.

**Acceptance:** Admin A signs out and leader B signs in in the same tab: no A data/name remains. A forged `admin.` prefix cannot authorize an admin call, and a leader's admin deep link ends at a clear no-access page.

### S09 P1 Decide what leaders may read beyond a published edition

**References:** specification lines 131-134 and 221; existing [scoring.py](../../../../src/app/api/scoring.py), [technologies.py](../../../../src/app/api/technologies.py), [PovValue.tsx](../../../../../tech-lens/components/PovValue.tsx).

Moving the existing proxy list to Atlas correctly establishes a server-side role boundary. However, the listed helpers return live data: `/scoring/fabrics` returns complete setup documents, including context/defaults/open questions; `/technologies/labels` returns names/labels across the register, with no published-edition filter. The value helpers also use live definitions. This predates sign-in, but conflicts with an unqualified “published-data-only” promise.

Choose explicitly: leaders may read a documented, limited set of current metadata, or they see only metadata frozen with their published edition. If the latter, expose lean edition-scoped DTOs and leave setup/catalog endpoints admin-only. When adding `updated_by` fields to setup documents, ensure those new emails/names are not unintentionally exposed through the leader reads.

**Acceptance:** A role test checks response fields, unpublished technology names and attribution data, not just HTTP status. Editing setup without publishing has the intended visible effect for leaders.

## Important implementation and grey-area comments

### S10 P2 Define the complete session schema and lifecycle

**References:** specification lines 102-120; implementation plan lines 35 and 46.

Specify the hashed token as the session `_id`, or give its lookup field a unique index. Add an account/email index for revocation. Store `expires_at` as a UTC BSON datetime, not the ISO string returned by the existing `now_utc()` helper: [MongoDB TTL expiry requires a date-valued field](https://www.mongodb.com/docs/manual/core/index-ttl/). Continue to enforce expiry during authorization, independently of eventual TTL deletion.

State whether twelve hours is absolute or sliding, whether inactivity has a separate limit, and what happens when it expires while editing or running a job. A sensible distinction is that an already-authorized background job continues, while further browser actions require sign-in. Explicitly choose that behavior.

On authentication storage failure, fail closed with an availability error; do not silently create an anonymous principal or clear a valid cookie as though the user supplied bad credentials. Bound malformed token/hash parsing and never include cookies/passwords/hashes in logs or API payloads.

### S11 P2 Make bootstrap restart-safe and fail clearly on placeholders

**References:** specification lines 81-86; implementation plan lines 39-45.

“Seed only when accounts is empty” is not restart-safe if startup inserts only some accounts before a failure. A second startup sees a nonempty collection and skips the missing people. Parallel API starts can also race. Use an idempotent bootstrap operation with completion state and a clear policy for intentionally removed accounts; do not blindly recreate every missing identity forever.

A placeholder hash must be safely non-matching, not a parsing exception. More importantly, production startup/release should fail clearly if there is no usable recovery-capable admin. Replacing a placeholder in the file after initial seeding will not update already-created accounts under the proposed one-time rule. Define a completion/reset command and test this path.

The existing generic seeding system can remain separate, which is a good choice. Test that bootstrap inputs and password fields cannot be exported through Changes or previews.

### S12 P2 Cover security administration and destructive actions in attribution

**References:** specification lines 187-203; implementation plan Phase 4.

The plan records starters and latest editors, but “who did what” currently omits several consequential actions: account creation/role change/disable/reset/unlock, stopping and resuming someone else's run, single-PoV composition/recomposition, merge, import reopen/discard, setup deletion/revert and writing seed defaults. Keep original author separate from `stopped_by`, `resumed_by`, `undone_by` or a subsequent action event.

Adding `updated_by` beside `updated_at` cannot identify who deleted a document: that record is gone. Changes currently reconstructs deleted items from seed data. A small append-only audit event or deletion tombstone is needed if deletion attribution is promised. A last-editor field also does not constitute a complete history of setting changes; describe the intended guarantee accurately.

Account security events deserve actor, target, action, time and outcome without secrets. Decide whether every admin may promote/reset every other admin; that is the consequence of the proposed two-role model. It can be intentional, but should be explicit.

### S13 P2 Carry audit identity through every execution boundary

**References:** implementation plan lines 119-122; existing [context.py](../../../../src/app/services/llm/context.py), [jobs.py](../../../../src/app/services/jobs.py), [supervisor/agent.py](../../../../src/agent/supervisor/agent.py).

The async-dependency-to-sync-endpoint assumption works in the installed stack. The local probe also confirms that an ordinary nested `ThreadPoolExecutor` loses the actor, while `copy_context()` preserves it. Existing `carry()` already copies context, so reuse it consistently; some submissions, including the scout fan-out, currently do not use it. Do not assume changing only `jobs.start()` covers all descendants.

Separate the authenticated request principal from the job's initiating actor. A worker's stored actor is attribution, not a fresh authority to act as that person. Decide whether queued work continues after the initiating account is disabled/demoted; record requested-by and execution identity accordingly. Reset ContextVars in `finally` blocks and test two actors concurrently through nested and retried jobs.

### S14 P2 Account for test fixtures, the scale stack and scripts

**References:** specification lines 223 and 237-239; implementation plan lines 178-181; existing [scale_copy.py](../../../2026-10-23/implementation-plan/v1/checks/scale_copy.py) and [perf.py](../../../2026-10-23/implementation-plan/v1/checks/perf.py).

The scale API runs the same guarded code. Its database-copy script uses a fixed collection list that currently excludes accounts and sessions. Thus “the scale stack is unchanged” is not enough: define separate synthetic accounts and sign-in for its checks, without copying live credential hashes or active sessions. Existing direct urllib API calls need cookie-jar handling, including concurrent checks, and each base URL needs its own authenticated client.

Cookies are not scoped by TCP port. A browser using the same hostname for live/development/scale instances can overwrite a same-named cookie or send a token to the wrong instance. Use distinct hostnames or an explicit isolation policy; separate cookie jars suffice for scripted clients.

Keep legacy test overrides scoped and cleaned up, but avoid fabricating authentication identity for unrelated internal service calls. Pair overridden tests with real-guard integration tests for each important workflow. Existing fixtures also override cache/freshness behavior; at least one real-session test should use production freshness settings.

### S15 P2 Make the authorization test matrix concrete

**References:** specification lines 125 and 253-256; implementation plan lines 68 and 76.

An app-wide dependency protects normal application route execution, but not every ASGI surface. The local probe observed `/docs` and `/openapi.json` returning 200 without running the guard. Explicitly disable or protect built-in docs/schema in shared deployment. Review mounts and any future sub-applications as separate boundaries.

The same probe returned 422 for malformed JSON before the dependency ran. This does not show an unauthorized handler execution; it means route dependencies are not an ingress/body-size defense. Retain request-size limits and consider early credential checks before expensive unauthenticated multipart parsing.

The route walk also needs representative concrete paths: `/lists/{name}` is one declared route, while a leader should read `mechanisms` but not its sibling lists. Test dynamic values, methods, trailing slashes, forged role prefixes, forced-change sessions, missing/expired/revoked cookies, and direct Atlas access. Check spoofed actor fields and hash/token leakage as well as 200/403 statuses.

### S16 P2 Specify what view counts mean

**References:** specification lines 205-216; implementation plan lines 130-141.

Choose whether counts are lifetime totals per technology, per published edition, or per PoV version. They are currently technology totals; the stored edition is resolved from the latest publication, which can differ from the page a person already has open. Carry the displayed edition identity if edition attribution is intended.

An opened event is a client-reported event, and a print event means a print dialog/event occurred; the browser does not prove a PDF was saved or printing completed. Refreshes, multiple tabs and development effect re-runs can duplicate opens. Define an event/deduplication policy and wording appropriate to that evidence. Record only valid published PoVs and use names captured at the event or a clearly defined current-name rule.

The designated leaders' test account will contribute to live engagement under the current plan. State whether that is intentional, and do not count smoke-test data as evidence of customer readership. Keep leader names/emails confined to the admin responses that need them.

### S17 P1 Rehearse migration and security-preserving rollback

**References:** specification lines 147-148 and 301; implementation plan Phase 8.

The plan removes `frontier` from the compose definition, then calls `docker compose stop frontier` and `rm frontier`. Keep the previous compose definition or an explicit old-container reference for that removal; rehearse the exact sequence on a disposable stack. Do not assume a removed service remains addressable through the edited file.

Add a worker-idle/drain condition before replacing it: the current worker owns running jobs, and the repository's compose comments already warn against rebuilding it while work runs. Mixed old/new API and portal versions need a maintenance/compatibility policy. Verify usable bootstrap credentials and console recovery before enforcing sign-in.

Retain previous image identifiers and configuration, and define rollback without overwriting intervening business data. Rolling back to the old application also restores anonymous access; keep the external front door restricted or in maintenance until a secure version is back. Include session invalidation when restoring an authentication database snapshot, since it can restore tokens that had been revoked.

**Acceptance:** Upgrade and rollback are exercised on a copy, including partial startup failure, an invalid bootstrap input and existing business data. No unintended access reopening or job loss occurs.

### S18 P2 Amend the plan's promises, documentation and estimates

**References:** specification lines 9-16, 35-36 and section 8; implementation plan Phases 0, 6-8 and effort table.

“Every old test is unchanged” is too rigid when access control and engagement semantics deliberately change. Preserve old business assertions, updating setup/expectations where necessary; do not preserve misleading assertions or bypass real authorization to maintain a number. Similarly, release smoke checks and signing in create session/audit data, so clarify the distinction between a read-only business-data walk and a literally zero-write check.

Extend Phase 0 beyond cookie set/get: production forwarding, Secure attributes, cookie clearing on 401, logout, rotation, forced-change navigation, two simultaneous identities and nested-job context. Add integration tests for the races and state transitions above. The current acceptance walk/lint/build cannot establish these guarantees.

The guide/process document list needs review: sign-in, forced password change and admin-assisted recovery are new entry/access steps even if assessment checkpoints stay the same. The standing repository rules call for affected business-process material to stay in step. Also, the planned post-change speed measurement should be recorded in the performance report if it becomes a new measurement, with authentication overhead distinguished from prior figures.

Remove the promise that future email recovery needs only a mail setting and page: it will require a separate secure token/recovery workflow and tests. That work can remain fully deferred. Re-estimate after adding recovery, race tests, CSRF and migration rehearsal; proposed file line counts and an unchanged test count should not constrain the implementation.

## Decisions to settle before coding

| Decision | Recommended starting point |
|---|---|
| First credentials | Unique, expiring temporary password per person; protected bootstrap input |
| No-email recovery | Another admin resets after identity verification; server-console reset when no admin can sign in |
| Privilege revocation | Account authentication revision checked by sessions, with token rotation after password change |
| Browser writes | Explicit CSRF policy and HTTPS/Secure release gate |
| Password-only policy | Longer passphrases, bounded inputs, common-password checks and bounded guessing |
| Leader data | Lean published metadata, or a documented exception for specific live metadata |
| Jobs after logout/disable | Already-authorized work continues with initiating-actor audit unless an explicit cancellation policy says otherwise |
| Identity transitions | Full navigation/reset of client stores; authenticated server state remains authoritative |
| Audit scope | Latest editor versus complete action history stated separately; security and destructive actions recorded |
| Engagement | Define edition/version scope, duplicate handling and treatment of test accounts |
| Release | Idle/drained worker, rehearsed removal of the old service, usable bootstrap and secure rollback |

## Suggested plan amendments

| Existing phase | Add |
|---|---|
| 0 | Production-style cookie/error/rotation checks; nested context probe; capture old service/image configuration |
| 1 | Unique bootstrap credentials, temporary expiry, restart-safe bootstrap, real recovery command, password/input policy |
| 2 | Revocation revision, CSRF, off-loop blocking work, explicit error/response contracts, docs/schema policy, BSON expiry/indexes |
| 3 | Last-admin invariant, unlock, security action audit and sensitive-action reauthentication |
| 4 | Destructive/stop/resume/single-PoV attribution; nested thread context; distinguish initiator from authority |
| 5 | Engagement scope, valid-PoV checks, duplicate/test-account handling and privacy of names |
| 6 | Client cache reset, safe deep links, raw-fetch exception, script cookie jars and independent scale identities |
| 7 | Real-guard workflow tests, race tests, production-mode/browser tests and affected documentation |
| 8 | Rehearsed migration, worker drain, recovery verification, secure rollback and session policy on restore |

## Evidence and limits

[review_probes.py](checks/review_probes.py) and [review-observations.json](checks/review-observations.json) record the small local framework checks. They establish the installed stack's dependency/context behavior, not correctness of an authentication feature that has not been implemented.

No live database, credentials or deployment were used. No application source, original specification/plan, product guide, training material or business behavior changed. Those client documents therefore need no update for this review-only work.
