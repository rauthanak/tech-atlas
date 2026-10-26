# Baseline before sign-in (Phase 0)

- atlas: `TEST_MONGO_DB=tech_atlas_test_signin uv run pytest -q`: 441 passed.
- lens: `npm run lint` clean; `npx tsc --noEmit` clean.
- Cookie through the portal's `/api` forwarding (`next dev`, a throwaway backend): the `Set-Cookie` from the backend
  reached the client, and the client's `Cookie` reached the backend. Passed.
- The person reaches the endpoint: an async app-wide dependency that sets a ContextVar after `run_in_threadpool`;
  a sync endpoint, an async endpoint and a thread started with `copy_context().run` all saw the value. Passed.
- Nothing queued or running in live `jobs` (0). Backup: `docs/2026-10-25/backup/tech_atlas-before-sign-in.archive.gz`
  (77 MB, gitignored).
