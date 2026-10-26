# Checks, 25 Oct

## Phase 0: on a copy of the live data (read-only)
- Duplicate active choices (CR03): 0
- Moves pointing at values not in their list (CR12): 0
- Queued jobs belonging to terminated runs (CR01): 0 (no queued jobs)
- Live priority_grid (CR11): edges [4, 7] and [4, 7], valid
- Active choices on technologies that no longer exist (CR04): 0
- Live image vs uv.lock (CR19): 27 packages newer in the image (builds floated); the release installs the lock

## Phase 1.6: CR05 dry-run (cr05_dry_run.py, on the copy)
14,614 stored scores checked; 3 (0.02%) would be emptied, each citing a page its assessment never read.

## Phase 7: the review's own reproductions, run against the fixed code (a copy of reproduce_review.py)
- CR01: the queued run stays running and its job is still taken
- CR02: "failed", "1 of 1 technologies failed: test technology: simulated provider failure"
- CR03: one active choice after concurrent saves; the old choice survives a failed save
- CR04: the absorbed technology's choice is on the survivor; none left on the deleted id
- CR05: an abstained score is null; a boolean score is null with its reason
- CR06: no model call for a Tata measure; nothing stored
- CR11: an invalid save is refused, with reasons; nothing saved
- CR12: the technology shows the existing catch-all
- CR13: put back refreshes every technology (touch_all called)
- CR14: a 17 MB file gets 413 "larger than 8 MB …", no DocumentTooLarge

## Tests
- Backend: 318 at the start → 441, all pass
- Portal: tsc and lint clean; production build passes with the network off

## Phase 8: release to live
- Backup: docs/2026-10-25/backup/tech_atlas-before-review-fixes.archive.gz (77 MB), dry-run restore OK
- Rebuilt atlas, worker, lens, frontier; restarted mongo for the port change; same record counts after
- Health OK; Setup › Changes 0 (1,981 sub-domains awaiting review untouched); seeding state recorded
- 43 screens 200; leaders' address: live reads 403, published data 200
- Ports: 8100, 3100, 3200 on 127.0.0.1 only; MongoDB not published
- Speed: 0 of 16 calls over 0.5 s (perf-live-after-release.txt)
