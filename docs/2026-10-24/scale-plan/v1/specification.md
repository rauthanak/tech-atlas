# Specification: the radar at 10 million pages, 24 Oct 2026

What the radar must do so that it still works when it holds 10 million pages. The 10-million-page test of 24 Oct
(`docs/2026-10-23/implementation-plan/v1/checks/e2e-10m-results.md`) showed where it stops working. This
document says what changes and what the result must be. The plan beside it
([implementation-plan.md](implementation-plan.md)) says how it gets built, in what order and in how many hours.

**Status:** signed off on 24 Oct, with all four decisions in section 14 as recommended. Simplified the same day at
your request (keep the design and code simple). Building starts with phase 1.

**Your direction (24 Oct):** "2 should be on the title of the pages or links, as unique identifiers". A page is
known by its link and, where two links carry the same page, by its title. Everything that counts, lists or
organizes pages counts a page once, however many times it was collected. Section 3 sets out the rule, and
section 14, decision 1, explains why the title is checked together with the site and the text, not alone.

**Rules kept throughout:**
- No functionality is dropped.
- Every failure says why.
- Show the cost and ask; don't cap.
- Plain words on screen.
- Every new index, collection, setting and container goes into the shipped files (`seeds/indexes.json`,
  `services/db/mongo.COLLECTIONS`, `.env.example`, `docker-compose.yml`, the README) the same day.
- Nothing heavy runs on the live database or the live containers.
- The live database changes only with your yes (the upgrade step in section 11).

---

## Contents

1. [What the 10-million test showed](#1-what-the-10-million-test-showed)
2. [Words used here](#2-words-used-here)
3. [A page is known by its link or its title](#3-a-page-is-known-by-its-link-or-its-title)
4. [Each page's newest visit is marked](#4-each-pages-newest-visit-is-marked)
5. [Full text is kept apart](#5-full-text-is-kept-apart)
6. [Organize works on new pages only](#6-organize-works-on-new-pages-only)
7. [Re-linking touches only the pages that changed](#7-re-linking-touches-only-the-pages-that-changed)
8. [Stored answers: only what changed is worked out again](#8-stored-answers-only-what-changed-is-worked-out-again)
9. [An assessment reads newest pages until its pack is full](#9-an-assessment-reads-newest-pages-until-its-pack-is-full)
10. [Screens read small records and ready answers](#10-screens-read-small-records-and-ready-answers)
11. [Start-up, indexes and the upgrade step](#11-start-up-indexes-and-the-upgrade-step)
12. [The 10-million re-test](#12-the-10-million-re-test)
13. [Diagrams and the deployment note](#13-diagrams-and-the-deployment-note)
14. [Decisions needed from you](#14-decisions-needed-from-you)
15. [What does not change](#15-what-does-not-change)

---

## 1. What the 10-million test showed

The test copy: 10,000,000 pages, 315,420 technologies and 600 collections over two years. It held 147 GB of data, 78 GB
on disk. The database had a 6 GB memory cache and no container limits. A stand-in model answered every call, so only
the radar's own work was timed.

| Process | Measured | Why it is slow |
|---|---|---|
| Building indexes when the API starts | 74 min, and the API answers nothing until it ends | every index is built before the API starts |
| Organize, after one collection of 1,151 pages | not finished after 5 h 20 min | it reads the names on all 10 million pages, every time |
| Stored answers, full recount | 7,000 of 315,420 in 3.8 h | it runs after every collection, and each technology reads all its pages from disk |
| Assessment, the 50 biggest technologies | 0 of 50 after 1 h 40 min | each evidence pack reads all 20,000+ pages of its technology, then sorts them |
| A big technology's pages (screen) | 30–36 s | it groups all 20,000+ visits to find each page's newest one |
| Points of View (screen) | over 2 minutes | it works out "new pages since written" from every visit of hundreds of technologies |

These were fine at 10 million: the crawl (15 min 41 s for 1,151 pages); the Briefing in every window
(0.02–0.11 s); Technologies and To do (about 0.5 s); the leaders' view (0.1–0.7 s).

**The cause underneath.** A page record averages 26.6 KB, and 83% of that is the page's full text, which only a
few jobs read. Even a query that asks for two small fields makes the database load the whole record. At 10 million pages
that is about 150 GB, which can't fit in memory, so every step that reads pages reads them from disk. Five
steps read many or all pages each time they run.

A second cause came out of this review. **Every visit is its own record, and the radar counts pages in two
ways.** Technologies' `page_count` counts distinct links. Organize, the evidence pack and a technology's page list each
work out "one per page" again from all the visits, every time they run. The same page under a slightly different
link (`…/2610.03713` and `…/2610.03713v1`, or `?share=linkedin`) counts twice.

## 2. Words used here

- **Visit:** one record in `documents`, one collection of one link at one time. It stays as it is today.
- **Page:** what a reader thinks of as one page, known by its **page key** (section 3). A page has one or more
  visits.
- **Version:** a visit that carried new text. A revisit with unchanged text (a *stub*) repeats the version
  before it, as today.
- **Newest visit:** the latest visit of a page. Lists, counts and the evidence pack read only this one.

## 3. A page is known by its link or its title

**Rule.** Each visit gets a `page_key` when it is stored (`services/runs/store.save_document`):

1. **By link.** The link, tidied:
   - the host is lowercased and a leading `www.` is dropped;
   - the `#…` part is dropped;
   - a trailing `/` is dropped;
   - tracking parameters are dropped: `utm_*`, `share`, `ref`, `fbclid`, `gclid`, `mc_cid`, `mc_eid`;
   - the other parameters are sorted.

   So `https://www.example.com/a/?utm_source=x#top` and `https://example.com/a` are the same page.
2. **By title.** A visit whose tidied link is new still joins an earlier page when it has the **same site, the
   same title and the same text**. This catches the same page published under two links: arXiv's `v1` address,
   a press release at `/press-release/press-release/…`, a `?context=cs` copy.
3. **Neither.** A visit with no link (a file someone uploaded to Find evidence) is its own page, as today.

**Why the title isn't used alone.** On live data, 302 titles are shared by 1,000 different links, and many of those
are different pages under a generic title:
- "Press Releases": 38 links, 24 different texts, on rbi.org.in;
- "Blog", "News", "Overview" and "Accepted Papers", across many sites;
- "Client Challenge": 60 different nature.com articles behind a bot check.

Merging on the title alone would count 38 different RBI press releases as one page. Requiring the same site and the
same text keeps them apart, and still joins real copies. Section 14, decision 1, asks you to confirm this.

**What it does to live data (worked out read-only, 24 Oct):**

| | Count |
|---|---|
| Visit records | 5,719 |
| Distinct links today | 5,279 |
| Pages after the link rule | 5,207 (72 fewer) |
| Pages after the title rule | 5,023 (184 fewer) |

For example, 13 cert-in.org.in "Present" pages with identical text become one page. Some technologies' page
counts drop a little, and each now counts pages the way a reader would.

**Where the key is used:**
- Deciding whether a page is new or changed: today `save_document` looks up the previous visit by the raw link.
- `evidence.page_key`, which every "one per page" reader already calls: the evidence pack, Classify's pages,
  new evidence.
- Technologies' `page_count`, worked out in `resolver._recompute_stats`.
- A technology's page list.
- Organize, which picks out the new pages (section 6).

The link shown on screen stays the link that was visited.

**New index:** `documents {page_key: 1, scraped_at: -1}`, which replaces the role of `{end_url, scraped_at}` for this
lookup. That index stays, because the run page uses it. Also `documents {content_hash: 1}`, for the title rule's lookup.

## 4. Each page's newest visit is marked

**Rule.** The newest visit of each page carries `latest: true` and `visits: n`, the number of times the page was
collected. When a new visit of the page is stored:
1. it is written with `latest: true` and `visits` one more than before;
2. then every older visit of the same page key loses `latest`.

If the radar stops between the two writes, a page briefly has two newest visits. Readers still keep one per
page key, as they do today, so a count is never doubled.

**What reads it.** Every place that today reads all visits and keeps the newest:
- `evidence.newest_visits`, which the stored answers and new evidence use;
- the evidence pack (section 9);
- a technology's page list (section 10);
- Classify's pages (`agent/classifier/evidence.py`);
- the PoV list's "new since written".

With `latest: true` in the query, they read about one visit per page instead of all of them.

**New index:** `documents {technologies_resolved: 1, latest: 1, scraped_at: -1}`, with a partial filter so that it
holds only newest visits.

**Unchanged revisits (stubs)** now also copy the previous visit's `technologies_resolved` when they're stored, so they
arrive linked and Organize has nothing to do for them (section 6).

## 5. Full text is kept apart

**Rule.** A page version's full text moves to its own collection, `page_texts`:

```
{_id: <the visit id>, text, page_key, run_id, superseded: false}
```

The visit keeps a `has_text: true|false` flag and `text_pruned`, so counts and filters never open `page_texts`. A
visit record drops from about 26.6 KB to about 4.5 KB.

**Who reads the text.** These are all of them, found by searching the code for `extracted_text`. Each reads through
one helper, `services/page_texts.get(ids)`:

| Reader | File |
|---|---|
| Storing a page (writes it) | `services/runs/store.save_document` |
| The run page's page viewer | `api/runs.py` |
| Check again (re-reads the text) | `services/signals/recheck.py`; its count of checkable pages uses `has_text` |
| Linking known names (searches the text) | `agent/tagger/tagger.py` |
| The Skills page preview | `services/prompts/preview.py` |
| Retention | `services/runs/store.prune_old_text` |

**Retention, same rule as today.** A version older than the last `KEEP_FULL_TEXT_RUNS` collections, with a newer
version of the same page, loses its text:
- when a new version of a page is stored, the older version's text is marked `superseded`;
- after each collection, retention deletes superseded texts from collections outside the last ten, in one query;
- today it opens every old page one at a time.

New index: `page_texts {superseded: 1, run_id: 1}`, partial on `superseded: true`.

Existing records are moved once by the upgrade step (section 11) before anything reads them, so the code has
one way of reading text, not two.

## 6. Organize works on new pages only

**Today.** Every collection's Organize reads the names on all pages (`resolver._resolve` "gathering"). It then
stamps all pages (`_stamp_documents`) and recounts all technologies (`_recompute_stats()`), which marks every
technology's stored answers for a recount (`tech_status.touch_all`).

**Rule.** Organize works only from **visits it hasn't seen**. By the page key, that means new pages and new versions of
known pages. A revisit with unchanged text brings nothing new.

1. **Marked when stored.** Every new version is written with `to_organize: true`. New index:
   `documents {to_organize: 1}`, partial, so it holds only the waiting ones.
2. **Gather.** Read the names on the waiting visits only, leaving out set-aside pages, as today.
3. **New names only.** A name already claimed by a technology goes to that technology, as today. So does a new
   spelling of a claimed name ("ML KEM" for "ml-kem"), with no model call, as today. The difference is that this is
   now found from the claimed names' tidied forms, not by re-reading every page.
4. **Counted by page.** For each name still unclaimed, count the **pages** that name it, through the existing
   `technologies` index. This is what the "at least N pages" floor (`MIN_DOCS_PER_TECH`) and the choice of display
   spelling use. Today it counts visits; with the default of 1 the result is the same.
5. **Model passes.** Same skill and prompts, on the unclaimed names only. That is already true today (claimed names
   are never sent); only the reading changes.
6. **Register.** Write only the technologies that gained names.
7. **Stamp.** Link the waiting visits, plus older visits that name a newly claimed name (a name that only now
   reached the floor), through the `technologies` index. Then clear `to_organize`.
8. **Recount.** Page counts and stored answers, for the technologies linked before or after on those visits only
   (`_recompute_stats(names)`, `tech_status.touch_names`).
9. **Labels.** As today; it already does only the technologies without a label.

**The same Organize, run by hand from Operations**, does the same. When nothing waits, it finishes at once and says
"No new pages since the last Organize". **"Start over"** (`replace=True`), which rebuilds the register, still reads
every page. Its confirm step says how many pages that is.

**Target at 10 million:** Organize after a collection of about 1,200 new pages finishes within 5 minutes,
plus the model's own time, which is added from live averages.

## 7. Re-linking touches only the pages that changed

**Today.** Five jobs re-link every page and recount every technology (`restamp_all`):
- three places in imports (`api/imports.py:208`, `services/imports.py:516`, `services/imports.py:626`);
- Find evidence (`agent/find_evidence/job.py:208`);
- linking known names (`agent/tagger/tagger.py:318`).

At 10 million pages each of those is hours.

**Rule.** Each passes what it changed to `resolver.restamp(names)`, which already exists for a person's rename or
merge (built in plan 10, phase 7):

| Job | What it passes |
|---|---|
| An import | the names of the rows it added, renamed or claimed |
| Find evidence | the technology it filed pages under, and the names on the pages it set aside |
| Linking known names | the technologies it filed pages under |

`restamp_all` stays only for **Start over**. It stays out of every automatic path.

**Check, at today's size:** after each job, page counts and links match what `restamp_all` would have produced. A
test runs both and compares them, technology by technology.

## 8. Stored answers: only what changed is worked out again

**Today.**
- Organize marks every technology for a recount after each collection (section 6).
- A safety sweep marks every technology every 30 minutes (`tech_status.SWEEP_S`).
- At 315,420 technologies and 0.5 a second, either one takes about 175 hours, so the recount never catches up.

**Rule.**
1. After a collection, only the technologies whose pages changed are marked (sections 6 and 7), together with
   the ones marked today by time: new assessments, Points of View, choices and runs (`_changed_since`).
2. **The safety net becomes a rolling check.** When nothing else waits, the updater re-works the 500 technologies
   whose answers are oldest. It never marks them all at once, so a full pass happens in the gaps. A full recount
   happens only when something can move every technology:
   - a setting, list or method changes (the middleware in `main.py`);
   - the record shape changes (`VERSION`).

   The status line still says "N technologies being updated".
3. **Each recount reads less.**
   - Pages come from newest visits only (section 4), in records about 6× smaller (section 5).
   - Classify's waiting check (`_classify_waiting`) compares each page's newest version, not every version ever
     stored. That is the same set Classify itself reads (`agent/classifier/evidence.py`).

**Target at 10 million:**
- After a collection, the changed technologies' answers are ready within 10 minutes.
- A full recount (after a settings change) is measured and reported. It runs in the background, the screens stay
  usable, and the status line shows its progress.
- If the full recount takes over 2 hours at 10 million, the re-test report says so. It then proposes the next step:
  a small record per page and technology, so counting reads no page records at all. That isn't built now (section 14,
  decision 4).

## 9. An assessment reads newest pages until its pack is full

**Today.** `agent/analyzer/engine.build_dossier` reads every visit of the technology, keeps one per page, sorts
them with "pages carrying a finding" first, then cuts the pack at `max_dossier_tokens` (300,000 tokens, about 1.2
million characters, about 2,400 pages).

**Rule.** Read newest first and **stop when the pack is full**:
1. With "findings first": first the newest visits that carry a kept finding about this technology. This query needs
   the new index `documents {signals.technologies_resolved: 1, latest: 1, scraped_at: -1}`. Then the other newest
   visits, newest first. Each stops at the budget.
2. The pack still says what it left out ("N oldest pages omitted"). N comes from the technology's `page_count` minus
   the pages read, so nothing is read just to count it.
3. What it records stays the same: `dossier_pages`, `runs`, and `dossier_from` when it was cut. New evidence still
   works off these.

The pack's contents are the same as today's for every technology whose pages fit, which on live data is every
technology. A test builds the pack both ways on the test database and compares them.

**Target at 10 million:** building the pack for the biggest technology takes 5 seconds or less. The run of the 50
biggest finishes, and its time per technology is recorded, with the model's time added from live averages.

## 10. Screens read small records and ready answers

**A technology's pages** (`api/technologies.technology_documents`):
- `find({technologies_resolved: name, latest: true}).sort(...).skip().limit(50)`, through the index in section 4;
- the total is the technology's `page_count`;
- "collected N times" is the visit's `visits`;
- the "new" flags are worked out for the 50 rows shown, as today.

**Points of View** (`api/scoring_runs.all_povs`):
- "New pages since it was written" becomes a stored answer: `tech_status` gains `f.new_since_pov`, worked out
  with the rest of the technology's answers;
- the list reads stored answers only, and no page records;
- filtering, sorting and paging stay as they are.

**A technology's summary** (`api/technologies.technology_summary`): "since the PoV" reads the same stored answer.

**Target at 10 million:** every screen answers in 1 second or less for one person, and 2 seconds or less with five
at once, during a collection.

## 11. Start-up, indexes and the upgrade step

**Indexes.**
- Today the API builds every missing index before it answers (`db/bootstrap.ensure_database`); at 10 million, after
  a copy, that was 74 minutes.
- From now on the API creates missing collections and starts at once. The **worker** builds missing indexes in the
  background at its start; MongoDB builds them without blocking reads and writes.
- There are no unique indexes, so nothing can go wrong while one is missing, only slower.
- Without a worker (`JOBS_IN_WORKER=false`), the API's own background thread does it.
- A fresh install still has every index within seconds, since the collections are empty.

**The upgrade step.** Existing data needs, once, for each visit:
- its page key;
- the newest-visit mark and its visit count;
- its text moved to `page_texts`;
- `has_text`.

This is `services/db/upgrade_pages.py`. The API runs it at start-up, before it answers, whenever it finds visits
without a page key; after that it finds none and does nothing.
- It goes through the visits oldest first and applies the same steps as storing a new visit (`pages.py`), so the
  rule lives in one place.
- If it's stopped, the next start carries on with the visits not done yet. Nothing extra is recorded for that.
- It writes its progress to the log.

The API waits for it, which is seconds at today's size. It is a one-off, so making the API answer during it isn't
worth the extra code.

| Size | Upgrade time |
|---|---|
| Live today, 5,719 visits | seconds |
| 10 million | measured in the re-test (my estimate: 1–2 hours) |

Before the upgrade runs on live, the live database is backed up with `mongodump`. It runs on live only with your yes.

## 12. The 10-million re-test

**The copy is rebuilt (`checks/scale_copy.py`)**, because the old copy can't be reused:
- its links differ only after `#copy…`, which the link rule drops, so all 10 million would fold into 5,279 pages;
- every copy also had the same text, which the title rule would fold.

The new copy:
- **10 million distinct pages**: each copy gets its own path (`/copy-123`) and text fingerprint;
- **plus revisits and new versions in live's own proportion** (5.5% unchanged revisits, about 2% new versions),
  so about 10.8 million visit records;
- the same 315,420 technologies, 600 collections over two years, a 6 GB database cache, no container caps;
- the stand-in model.

It is built in the old shape, so the upgrade step is measured at 10 million.

**What is run and timed, in order**, written to `e2e-scale-results.json` and `e2e-10m-results.md`:

| Step | Recorded |
|---|---|
| 1. Generating the copy | time |
| 2. API start with no indexes | time to the first answer; worker index build time |
| 3. The upgrade step | time; disk before and after |
| 4. Start-up upkeep: stored answers, Briefing days | time to finish |
| 5. A collection: 86 sources, 15 pages each, real websites | crawl, Organize, linking, Classify, stored answers after it |
| 6. Assessment of the 50 biggest technologies | per technology; pack build time; model time added |
| 7. Points of View for those 50 | per Point of View; model time added |
| 8. Publish an edition | time |
| 9. Import Tata's catalog (the October xlsx) | upload and check, match, accept, confirm |
| 10. Rename the biggest technology and back | time each way |
| 11. Check again, 10-minute sample | pages a second; projected full time; model time added |
| 12. A full recount after a settings change | time to finish |
| Screens, after steps 4, 5 and 12 | every screen in `checks/perf.py`, one person and five at once |

Each target in sections 6–11 is checked against what's measured. Anything that misses is reported with its reason,
not hidden.

**Disk.** The 10-million copy needs about 80 GB, plus about 65 GB while the upgrade runs (the text is written to
`page_texts` before space is reclaimed). There is 128 GB free, plus the 84 GB the old copy's volume frees when it's
dropped. It is checked before starting.

## 13. Diagrams and the deployment note

After the re-test, with its numbers, these are revised to show the final design:

| Picture | File | What changes |
|---|---|---|
| Business process | `artifacts/Business Architecture/Radar Business Architecture (standalone).html` | the six steps with the two gates; who acts where |
| Technical architecture | `artifacts/System Architecture/Radar Architecture v0.10 (standalone).html` | API, worker and the jobs queue; ready answers (`tech_status`, `briefing_days`); pages, visits and `page_texts` |
| Process flow | `artifacts/Radar Process Flow (standalone).html` | what runs after a collection, and what each step reads |
| The client docx's process picture | `docs/2026-10-20/1/make_diagrams.py` | the same, redrawn |

Also in the deployment note (client docx), the **database sizing** promised earlier:

| Pages held | Memory for the database | Disk | Cores |
|---|---|---|---|
| 100,000 | | | |
| 1 million | | | |
| 10 million | | | |

The figures are filled in from the measured sizes.

## 14. Decisions needed from you

1. **How a page is known (your point on fix 2).** Recommended: by its tidied link, or by the same site + same title +
   same text (section 3). The other choice is by title alone, which would merge different pages that share a generic
   title (38 RBI press releases titled "Press Releases").
2. **Tracking parameters dropped from links** (`utm_*`, `share`, `ref`, `fbclid`, `gclid`, `mc_cid`, `mc_eid`).
   Recommended: a fixed list in the code. A setting would mean re-keying every page whenever it's edited.
3. **The upgrade on live.** Seconds at today's size, after a `mongodump` backup. It runs only when you say yes, after
   the re-test.
4. **If a full recount is still over 2 hours at 10 million:** report it and propose a small page-and-technology
   record (recommended), or build that record now, without the measurement.

## 15. What does not change

- What a person sees and can do on every screen.
- How pages are crawled and read.
- The skills and their prompts.
- How Classify, assessments and Points of View judge.
- The Briefing (already fast at 10 million).
- Editions and the leaders' site.
- The seeding data, apart from new indexes.
- `documents` stays one record per visit. Visits, their dates, findings and history are all kept.
- Only these numbers move: page counts, which now count a page once under any of its links, and the counts that
  follow from them.
