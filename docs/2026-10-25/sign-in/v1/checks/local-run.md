# Local run on a restored copy (Phase 6), 26 Oct

The live backup restored into the brew MongoDB as `tech_atlas_test_copy`; the new API on 8101 (stand-in model) and a
production build of the portal on 3057. Dropped afterwards.

- No cookie: every page goes to `/sign-in?next=…`; `/api/*` answers 401.
- Wrong password: 400 "That email and password don't match.", shown on the form.
- Seeded account (starting password): signs in with must_change; every call but its own is 403 "Choose a new password
  first."; after the change, 200.
- Admin: `/` lands on `/admin`; `/frontier` opens; all 42 manual screens load with no error; the admin note shows on a
  leaders' Point of View.
- Leader: `/` lands on `/frontier`; every `/admin` page shows "This part is for the radar team"; admin API calls 403;
  the leaders' calls 200.
- Counter: the leader's visit counted with the name; the admin's not.
- `next=//example.com` ignored (lands on `/admin`).
- A save after the session was deleted: the browser lands on sign-in and nothing is saved.
- Admin signs out, the leader signs in in the same tab: nothing of the admin's is shown.
- Screenshots for the manual taken from this copy (signed in; only pages opened).
