# Plan 7: The team's new signals, and a fresh start on 12 sources (tech-atlas)

**Date:** 2026-10-05 · **Folder:** 2026-10-05/1 · **Status:** signed off on 5 Oct with three decisions (§9): hyperscalers stay in Competitor move ("if they think their competitors are hyperscalers"); Sports Video Group is added as a 13th source, so Media has one; assessments cover technologies with 3 or more pages. **All seven steps done by 6 Oct**; build notes are in §10.

**Portal:** no changes. Nothing in tech-lens names a signal type or counts them, so this plan has no tech-lens half.

**Where this came from:** the review in `../Signals and sources review.xlsx` (moves to `replaced/` in step 7), and the decisions of 5 Oct:
- **Signals:** widen four types, reword one, and add one.
- **Data:** clear the collected data, then start again on 10–12 sources. I choose them, spread evenly across the three horizons, so that they catch almost every signal type, with 60 pages per source. Run cost isn't a concern.
- **Order of work:**
  0. you sign off;
  1. back up and delete the collected data;
  2. make the signal changes;
  3. make the source and setting changes;
  4. update the seeding data and run the checks;
  5. run a fresh collection;
  6. run assessments and write Points of View;
  7. make the spreadsheet's version 2, last.

---

## 1. Summary

| | Today | After this plan |
|---|---|---|
| Signal types | 35 (28 never-miss, 7 can-ignore) | **36** (29 never-miss, 7 can-ignore) |
| Types changed | — | 4 widened (2 of them renamed), 1 reworded, 1 new |
| Sources switched on | 21 of 147 | **13 of 147**: 4 per horizon, plus Sports Video Group for Media (decision 2) |
| Pages per source per collection | 40 | **60** |
| Collected data | 2 collections, 423 pages, 2,494 technologies, 491 assessments, 163 Points of View | Backed up, then deleted; rebuilt by one fresh collection |

Of the 14 ideas the team sent:
- **Covered after this plan:** 12, including all 7 that were already covered and the 5 that were partly covered.
- **Not covered:** the 2 that are sources rather than signals. "Academic papers" is covered by arXiv, which stays on. "Patent filings" waits for the EPO key (see the project mailbox, in the spreadsheet's Discussion tab).

Of our 3 suggestions:
- **Spectrum or licence decision:** goes into the new type.
- **Customer demand:** becomes a question for TCL.
- **Research or patent surge:** waits for a later build.

---

## 2. Step 1: back up, then delete the collected data

**Which database.** Only Docker's `tech_atlas`, in the container `tech-radar-mongo-1`. Every command runs inside that container (`docker exec`). Nothing goes through `localhost:27017` from the Mac, because that reaches the older brew MongoDB, which holds `tcl_radar` and an old `tech_atlas`. That database, and the dev copy `tech_atlas_dev`, are not touched.

**What's deleted and what's kept:**

| Deleted: every document in these collections (the collections and their indexes stay) | Count now |
|---|---|
| `runs`: collections | 2 |
| `documents`: collected pages, with their summaries and signals | 456 (423 pages, 33 unchanged revisits) |
| `technologies`: the technology register, with aliases and labels | 2,494 |
| `resolves`: organizing runs | 6 |
| `scoring_runs`: assessment runs | 5 |
| `assessments`: scores per technology and fabric | 491 |
| `povs`: Points of View | 163 |
| `pov_compose_jobs`, `recheck_jobs`: job records | 2, 2 |

**Also reset:** the `progress` field on the 6 data sources. This is where saved searches remember how far they've read, and where job boards keep last run's count. With it cleared, the fresh collection reads the last 30 days, as a first run does.

**Kept, unchanged:** every setting. That is `sources`, `signals`, `prompts`, `settings`, `fabrics` (with the TCL-today profiles), `measures`, `scoring_config`, and the `seeding` state. No technology is switched off, and the backup keeps the whole register, including any hand edits, should any be needed again.

**How:**
1. **Check nothing is running.** Operations shows no collection, check, assessment or writing job in progress. The API refuses to start one while another is running, so nothing new can start partway through.
2. **Back up:**
   - run `mongodump --db tech_atlas --archive --gzip` inside the container;
   - copy the archive to `replaced/db-before-plan7.archive.gz` in this folder.
3. **Prove the backup works:**
   - restore it into a scratch database, `tech_atlas_restore_check`, in the same container;
   - compare every collection's count with the live one;
   - drop the scratch database.
4. **Delete:** `deleteMany({})` on the 9 collections above, then `$unset: {progress}` on the data sources. The commands go in this folder as `clear_collected_data.js`, so step 3's test can reuse them.
5. **Check:**
   - the 9 collections hold 0 documents;
   - the 8 settings collections hold what they did before (147, 35, 12, 1, 6, 12, 4, 1);
   - Operations shows "Not collected yet";
   - the Briefing, Technologies and Points of View are empty;
   - Setup → Changes still shows 0.

**Undo:** `mongorestore --archive --gzip --drop` from the backup puts everything back exactly as it was.

---

## 3. Step 2: the signal changes

The changes are made through the API, the same calls the Setup → Signal list page makes. Each signal keeps its id, so a rename changes only the name that's shown.

| Type (id) | Change | Before | After |
|---|---|---|---|
| **Funding round** (`funding-round`) | Reworded: any stage | A company raises money. Note the stage, the amount and the investors, including corporate venture arms and sovereign or pension funds. Significant: a disclosed amount, or a named top-tier, corporate or sovereign investor. | A company raises money **at any stage, from pre-seed and seed to late stage**. Note the stage, the amount and the investors, including corporate venture arms and sovereign or pension funds. Significant: a disclosed amount, a named top-tier, corporate or sovereign investor, **or a first round for a deep-tech company**. |
| **Partnership** (`partnership`) | Widened: MoUs and research partnerships | Companies team up to build, integrate or sell a technology. Note it especially when it involves one of Tata Communications' own partners: Cisco, AWS, Microsoft, TCS, Versa, NVIDIA or Johnson Controls. | **Companies, universities or governments** team up to **research,** build, integrate or sell a technology, **including a memorandum of understanding (MoU) or a joint research programme**. Note it especially when it involves one of Tata Communications' own partners: Cisco, AWS, Microsoft, TCS, Versa, NVIDIA or Johnson Controls. |
| **Competitor move** (`competitor-move`) | Widened: first moves, and hyperscalers | A company competing with Tata Communications launches, prices or invests in a technology, including in earnings calls or filings. For example: Orange Business, BT, Lumen, NTT, Colt or Verizon in networks; Zscaler, Palo Alto Networks or Cato Networks in security; Twilio, Sinch or Infobip in customer communications; Vodafone IoT, KORE or 1NCE in IoT; Akamai or LTN in media; Yotta, CtrlS or Jio in cloud in India. | The same, plus: **It counts especially when it is the company's first move into an area new to it: a first patent, research paper, product, acquisition or team there. Hyperscalers (AWS, Microsoft, Google) count when they move into Tata Communications' markets.** |
| **Spin-out → Spin-out or startup launch** (`spin-out`) | Widened and renamed | A university or corporate lab spins out a company. | A university or corporate lab spins out a company, **or a new deep-tech startup is founded, incorporated or comes out of stealth. Note the founders, the backers and what it builds.** |
| **Market figure → Market figure or analyst coverage** (`market-figure`) | Widened and renamed | An analyst market size, forecast or survey figure, with its scope and date. | An analyst market size, forecast or survey figure, with its scope and date; **or an analyst firm covering a technology for the first time, such as its first report on it or its first appearance in a hype cycle, wave or quadrant.** |
| **Approval, licence or certification** (`approval-licence-or-certification`) | **New**, never-miss, placed straight after Regulation or mandate | — | A regulator or certification body approves, licenses or certifies a technology, product or provider: for example a NIST validation of a post-quantum algorithm or module, a spectrum or satellite licence, or a telecom equipment certification. Note who granted it, to whom and for what. |

**Unchanged:** the other 30 types.

**One wording choice to confirm:** adding hyperscalers to Competitor move. AWS and Microsoft are also TCL partners (they're named in Partnership). Both can be true: a partner moving into TCL's market is still a competitive move.

**Test before going further.** `signal_dry_run.py` in this folder runs the page-analysis step on chosen pages and stores nothing. It uses the live analysis instruction and the new list, so it's the same call a collection makes, and it runs inside the atlas container, about 1 call per page. It reads 8 real, recent pages:

| Page | Should be found as |
|---|---|
| A pre-seed or seed round announcement | Funding round |
| A company–university MoU or joint research programme | Partnership |
| A competitor or hyperscaler entering a new area for the first time | Competitor move |
| A deep-tech startup coming out of stealth (no funding announced) | Spin-out or startup launch |
| An analyst's first report on a technology, or its first hype cycle, wave or quadrant entry | Market figure or analyst coverage |
| A NIST validation, or a spectrum or satellite licence | Approval, licence or certification |
| Check: a Series B round | Funding round, as before |
| Check: a page of patch notes | Set aside as Routine update; no signal |

If a type doesn't fire, or fires on the wrong page, I adjust the wording and run that page again. The pages and results go in the build notes (§10).

---

## 4. Step 3: sources and collection settings

### The 13 sources: 4 per horizon, plus Sports Video Group for Media

| Horizon | Source | How it's read | What it's there for | Today |
|---|---|---|---|---|
| H1 | **Light Reading** | Website | Competitor moves, launches, deployments, pilots, partnerships, deals, prices, regulation and approvals across telecom: the widest single source | On (checked 4 Oct) |
| H1 | **TeleGeography** | Website and feed | Subsea and terrestrial builds, cable cuts and outages, spectrum and licence awards, prices and market figures. Network is TCL's core business | On (checked 4 Oct) |
| H1 | **CX Today** | Website | The Interaction fabric (CPaaS, CCaaS, AI agents): competitors such as Twilio, Sinch and Infobip, launches, deals, and analyst coverage such as Magic Quadrants | On (checked 4 Oct) |
| H1 | **CERT-In advisories** | Website | Security advisories, and India's security directions (mandates). It's the only security agency we can read: CISA refuses our collector | On (checked 4 Oct) |
| H1 | **Sports Video Group** (decision 2) | Website and feed | The Media fabric: broadcast and streaming launches, deployments, deals and partnerships | On (checked 4 Oct) |
| H2 | **TechCrunch: venture** | Feed | Funding at every stage, new funds, acquisitions, IPOs, shutdowns, stealth launches | **Off → on**; first check in this step |
| H2 | **Hacker News** | Website, following links out | Developer adoption, open-source milestones, startup launches ("Launch HN"), shutdowns | On (read in earlier collections) |
| H2 | **Company job boards** | Data source: public job-board APIs, no key | Hiring surges and new teams at 13 named companies (Cloudflare, Zscaler, Netskope, OpenAI, IonQ, PsiQuantum, SandboxAQ and others) | **Off → on**; first check in this step |
| H2 | **IoT Analytics** | Website and feed | The IoT fabric: market figures and analyst coverage, deployments, launches | On (checked 4 Oct) |
| H3 | **arXiv** | Website and feeds | Research breakthroughs, and papers accepted at top conferences | On (read in earlier collections) |
| H3 | **OpenAlex: grants** | Data source: OpenAlex API, no key needed | Government programmes and funded university research, on 8 saved topics (quantum key distribution, post-quantum cryptography, coherent optics, network slicing, LEO satellite, zero trust, edge AI, network digital twin) | **Off → on**; first check in this step |
| H3 | **GSMA** | Newsroom and feed | Standards and network APIs (Open Gateway, CAMARA), alliances, operator pilots | On (checked 4 Oct) |
| H3 | **IETF** | Website | New working groups, adopted drafts and published standards: the clearest source for "a standards body forms a working group" | On (read in earlier collections) |

**Switched off (11):** TCL News Centre, Cisco Blogs, Amazon Science, RBI, SEBI, Techstars, Mplify, TM Forum Inform, SMPTE, 3GPP and ETSI. All stay in the register and can be switched back on in Setup → Sources.

**Media:** the first proposal of 12 had no Media source. You chose to add Sports Video Group as a 13th (decision 2), so every fabric has at least one source.

### Will these catch almost every signal type?

| Signal type | Where it should show up |
|---|---|
| Funding round · New fund or investment theme · IPO or listing | TechCrunch: venture |
| Acquisition or merger | TechCrunch: venture, Light Reading, CX Today, TeleGeography |
| Shutdown or failed raise · Spin-out or startup launch | TechCrunch: venture, Hacker News |
| Government programme or grant | OpenAlex: grants |
| Regulation or mandate | CERT-In, TeleGeography, Light Reading, GSMA |
| **Approval, licence or certification** | TeleGeography, Light Reading |
| Security advisory | CERT-In |
| Major outage or cable cut · Infrastructure build · Price change | TeleGeography, Light Reading |
| Research breakthrough | arXiv |
| Prototype or field trial | Light Reading, GSMA, IoT Analytics |
| Standard milestone | IETF, GSMA |
| Open-source milestone · Developer adoption jump | Hacker News |
| Alliance formed | GSMA, Light Reading |
| Product launch · Named deployment | Light Reading, CX Today, IoT Analytics, Sports Video Group, Hacker News |
| Competitor move | Light Reading, CX Today, TeleGeography |
| Partnership | Light Reading, GSMA, CX Today, TechCrunch: venture |
| Market figure or analyst coverage | IoT Analytics, CX Today, TeleGeography |
| Hiring surge or new team | Company job boards |
| *Thin:* Top-conference recognition · Public tender | arXiv (papers that name their venue) · TeleGeography and Light Reading (network tenders) |
| *No direct source:* Patent filing or grant · Employment trend | Only when the news reports one. EPO and USAJOBS both wait on the project mailbox |

**In short:** 25 of the 29 never-miss types have a clear source, 2 are thin, and 2 wait on the project mailbox. Step 5 shows what the fresh collection actually finds, and the spreadsheet's Notes tab will record it.

### Settings

- **Pages per source:** 40 → **60**, in Setup → Sources → Collection settings.
  - The 11 websites read up to 60 pages each.
  - OpenAlex: grants splits its 60 across its 8 searches, so 7 results each.
  - The job boards produce 13 summaries, one per company.
- **Unchanged:** the lookback stays at 30 days, and the pages to skip stay as they are.

### Test before the fresh collection

Three sources haven't been read before: TechCrunch: venture, Company job boards and OpenAlex: grants.
1. **Check TechCrunch: venture** the way the others were checked on 4 Oct: robots.txt, its feed, and an article page, with our collector's user agent.
2. **Run a smoke collection:** all 13 sources at 3 pages each (the run's own page limit), about 60 pages.
   - Every source should finish with pages and no "didn't finish".
   - Each failure must say why.
3. **Clear the smoke data** with `clear_collected_data.js`. That also resets `progress`, so the saved searches still read the full 30 days in the fresh collection. The backup from step 1 isn't needed again.

---

## 5. Step 4: seeding data, and the checks

1. **Save the before copies** in `replaced/`:
   - `signals-before-plan7.json` (35 types);
   - `sources-before-plan7.json` (147 sources, 21 on);
   - `settings-before-plan7.json` (collection settings).
2. **Update the seeding data:** in Setup → Changes, tick every item and use "Update seeding data". Expected:
   - 6 signal rows;
   - the never-miss rows whose order moved because of the new type;
   - 14 sources (3 switched on, 11 switched off);
   - the collection settings.
3. **Checks:**
   - `../../2026-10-04/4/live_vs_seeds.py` reports 0 items a load would change, and the fingerprint matches the files;
   - Setup → Changes shows 0;
   - the backend tests all pass (85 today; they use their own sample signals, not the seeding data);
   - the Signal list page shows 36 types in the right order.
4. **The seeding files** (`signals.json`, `sources.json`, `settings.json`) change in tech-atlas. That's live but not saved as a version in git. Saving it as a version, or putting it on GitHub, is your call, as before.

---

## 6. Step 5: the fresh collection

- **Start it** from Operations → Collect: all three horizons. The confirmation should read "11 websites, 2 data sources, up to 60 pages each".
- **Expected size:** up to about 730 pages (660 from websites, up to 56 grants, 13 job summaries).
  - That's about one model call per page for the summary and its signals, plus link choosing and a few calls to organize and label technologies.
  - It should take about 2 hours; the last collection read 216 pages in 37 minutes.
- **Afterwards, I report:**
  - pages per source;
  - findings per signal type, checked against the coverage table in §4;
  - the number of technologies;
  - any problems, each with its reason.
- **Known, not fixed here:** the agent layer still fails its first call (the pending "agent 400" fix). The run falls back to its built-in sweep, as it has since 4 Oct, so the results are complete.

---

## 7. Step 6: assessments and Points of View (decision 3)

Deleting the data also removed every assessment and Point of View, so the radar is empty until this step.
- **Assessment cost:** about 30–40 model calls per technology, made up of 2, plus 12 for each fabric the technology is scored in.
- **Point of View cost:** 1 call per technology.

The counts below are scaled from today's register, which has 117 technologies with 3 or more pages out of 423 pages. The portal shows the exact number, and the estimate, before anything starts.

| Scope | Technologies (rough) | Calls (rough) |
|---|---|---|
| 5 or more pages | about 60 | about 2,000–2,500, plus 60 Points of View |
| **3 or more pages (recommended)** | about 190 | about 5,500–7,500, plus 190 Points of View |
| 2 or more pages | about 580 | about 17,000–23,000, plus 580 Points of View |

**Why 3 or more pages:** a technology on one or two pages rarely has enough evidence for its measures to be scored. Three or more gives the radar a broad first picture without spending on single mentions.

---

## 8. Step 7: the spreadsheet's version 2 (last)

**File:** `Signals and sources review - v2.xlsx`, in this folder. Version 1 moves to `replaced/`. Please close it in Excel first; it's open now. The generator, `make_signals_xlsx.py`, goes in this folder, so the file can be rebuilt.

**Signals tab:** the same rows, with columns Signal | Old or New | Sources | Already Configured | **Added to the code**.
- **Old or New** stays as it was.
- **Already Configured** stays as the 5 Oct review said, so you can see before and after.
- **Sources** shows the new state: which of the 12 are on, which are off, and what to add.
- **Added to the code** says plainly what happened to each row:

| Row | Added to the code |
|---|---|
| A type that changed | "Yes: widened in v2", "Yes: widened and renamed in v2 (was Spin-out)", or "Yes: reworded in v2" |
| An idea covered by a changed type | "Yes: Partnership widened in v2", and so on |
| An idea covered by the new type | "Yes: new type Approval, licence or certification (v2)" |
| An idea already covered | "Not needed: already covered by Prototype or field trial", and so on |
| Not added | Why: "No: needs the EPO key (project mailbox)", "No: question for TCL", "No: a later build" |
| Unchanged types | "Already in, no change" |

Changed type names show both names, for example "Spin-out or startup launch (renamed from Spin-out)". Rows that changed are highlighted.

**Notes tab:** the legend and the key points, updated, plus what the fresh collection found for each signal type, taken from the run and its date.

**Discussion tab (new):** the points and questions from 5 Oct.
1. **The project mailbox:**
   - what it is;
   - which sources need it: EPO patents, SEC EDGAR and USAJOBS, and what each would add;
   - why your own email can't be used;
   - the two options, a new free mailbox now or a TCL address;
   - who does what: the team creates it and registers, the keys go in the radar's private settings file, and I switch the sources on and test them.
2. **Customer demand: the question for TCL.**
   - TCL's framework sets P3 as "prototype or MVP on customer demand", and the radar can't see demand.
   - The question: "Can TCL share a simple monthly summary of customer requests by technology (technology, fabric, region, count), with no customer names?"
   - What happens if TCL says yes, and what happens if it says no.
3. **Decisions made on 5 Oct:**
   - widen four types and add one;
   - 12 sources, 4 per horizon, 60 pages each;
   - the data cleared, and where the backup is.
4. **Known gaps, and what would close them:**
   - Media has no source;
   - patents and employment trends wait on the mailbox;
   - licensed sources wait on TCL;
   - a research or patent surge needs a later build.
5. **Open questions:** anything still waiting on you or on TCL.

---

## 9. Decisions for you at sign-off

1. **Signal wording (§3):** are the six wordings right? In particular, should hyperscalers be in Competitor move? **Decided: yes, all six as written.**
2. **Sources (§4):** the 12 as proposed, or Sports Video Group as a 13th so that Media has a source? **Decided: add it.**
3. **Assessment scope (§7):** 3 or more pages (recommended), 5 or more, or something else? **Decided: 3 or more pages.**

**Not in this plan:**
- EPO patents, SEC EDGAR and USAJOBS: they wait on the project mailbox.
- Licensed sources such as Crunchbase, PitchBook and Gartner: they wait on TCL.
- The research or patent surge: a later build.
- Customer demand: TCL's answer comes first.
- The agent-call fix.
- **The deck v2:** it says 35 signal types and 21 sources on, which become 36 and 12. I can update it after this plan if you want.

---

## 10. Build notes

**Model change during the build (5 Oct).** You switched `.env` to `MODEL_NAME=gpt-6-luna` (cheaper than gpt-5.6-luna). Docker reads `.env` only when a container is created, so I recreated the atlas container (`docker compose up -d --no-deps --force-recreate atlas`). The database and portal stayed up. One test call answered "ready" on gpt-6-luna. Every step from here runs on it, and the signal test was run again on it.

**Step 1, done.**
- **Backups:**
  - the before copies are `replaced/signals-before-plan7.json`, `sources-before-plan7.json` and `settings-before-plan7.json`, the seeding files, which matched live (Changes 0);
  - the database backup is `replaced/db-before-plan7.archive.gz` (5.1 MB, mongodump of Docker's `tech_atlas`).
- **Backup proved:** restored into the scratch database `tech_atlas_restore_check`, all 17 collections matched the live counts, and the scratch copy was dropped.
- **Deleted with `clear_collected_data.js`:**
  - 2 collections and 456 page records;
  - 2,494 technologies and 6 organizing runs;
  - 5 assessment runs, 491 assessments and 163 Points of View;
  - 2 writing jobs and 2 check jobs.
- **Nothing to reset:** no data source had any reading progress yet.
- **After the delete:** the settings collections were unchanged, Changes was 0, and Operations read "Not collected yet".

**Step 2, done, with two wording additions to Competitor move.** All six changes went in through the API. That makes 36 types (29 never-miss), and Approval, licence or certification is placed 8th, straight after Regulation or mandate.
- **The dry run** (`signal_dry_run.py`, 8 real pages, nothing stored) on gpt-6-luna passed every page except the hyperscaler one:
  - pre-seed round (Arq, The Quantum Insider): Funding round;
  - university-led MoU (6G Flagship at Oulu with the Bharat 6G Alliance): Partnership;
  - out of stealth (Eridu, TechCrunch): Spin-out or startup launch, plus Funding round;
  - first-ever report (Group-IB in Gartner's inaugural Magic Quadrant for cyberthreat intelligence, PR Newswire): Market figure or analyst coverage;
  - NIST validation (Quantum XChange Phio TX, CAVP and CMVP certificates): Approval, licence or certification;
  - the Series B check (Exaforce) stayed Funding round;
  - the patch-notes check (PostgreSQL 17.2) was set aside as Routine update.
- **Pages that couldn't be read** were replaced by the next candidate; each refusal or time-out is recorded in the script's output:
  - BW Education refused us (403);
  - CrowdStrike's investor site and GlobeNewswire timed out or disconnected.
- **An unrelated catch:** on the Amazon page, the new type also caught "FCC approves Amazon's Generation 2 satellite constellation".
- **The hyperscaler page** (Amazon Leo's enterprise beta, The Next Web) was the one weak spot. Every Amazon event on it was caught, but as Product launch, Prototype or field trial, Approval and Partnership, not as Competitor move. So I added two sentences to Competitor move, in the spirit of your decision:
  - the hyperscaler sentence now names TCL's markets: "enterprise connectivity (satellite included), cloud, security, customer communications, IoT or media services";
  - "Report it as a Competitor move even when the same news is also a product launch, partnership, acquisition or deployment."
- **Result after the additions:** Competitor move fired on 1 of 2 runs, and never on the MoU or Series B pages. More wording is unlikely to make the model fully consistent. The events themselves are always caught, so I stopped there. After the fresh collection I'll check how often hyperscaler moves carry the competitor label.

**Step 3, sources and settings, done.**
- **Switched on:** TechCrunch: venture, Company job boards and OpenAlex: grants.
- **Switched off:** the 11 listed in §4.
- **Now on:** 13 sources: H1 has Light Reading, TeleGeography, CX Today, CERT-In and Sports Video Group; H2 has TechCrunch: venture, Hacker News, Company job boards and IoT Analytics; H3 has arXiv, OpenAlex: grants, GSMA and IETF.
- **Settings:** pages per source is 60 (lookback unchanged at 30 days). The collection preview reads "11 websites, 2 data sources, 60 pages each".
- **TechCrunch:** its robots.txt allows our collector for the venture feed and its articles. Both had already been read in the dry run.

**The test collection** (run `9d14c2b64e35`, 3 pages per source) read 47 pages, all of them new.
- **Every source gave pages:**
  - each of the 11 websites gave its 3;
  - the job boards gave 13 company summaries;
  - OpenAlex: grants gave 1 (1 per search at this limit).
- **Results:** 63 findings, 18 "Other", none set aside, 0 problems, and 154 technologies organized. The "didn't finish: N links left" notes only reflect the 3-page limit.
- **The agent layer works on gpt-6-luna.** The orchestrator answered and each horizon's supervisor dispatched its scout, without the first-call failure seen on gpt-5.6-luna since 4 Oct. So the pending "agent 400" fix appears unneeded.
- **Cleared afterwards** with `clear_collected_data.js`: 1 run, 47 page records, 154 technologies and 1 organizing run. That also reset the reading progress on 2 data sources (job boards and OpenAlex: grants), so the fresh collection reads the full 30 days.

**Step 4, done.** Setup → Changes listed 38 edits:
- 1 setting: 60 pages per source;
- 14 sources: 3 switched on, 11 switched off;
- 23 signal rows: the 6 changes and the new type, plus 17 that moved down one place to make room for it.

"Update seeding data" wrote all 38 to `seeds/settings.json`, `seeds/sources.json` and `seeds/signals.json`. Checks:
- Changes 0;
- `live_vs_seeds.py`: 0 items a load would change, and the fingerprint matches the files;
- all 85 backend tests pass.

The three seeding files are live but not saved as a version in git.

**Step 5, done.** Collection `a4795679954e`, on 11 websites and 2 data sources at 60 pages each, took 70.5 minutes. The three horizons run one after another, about 20 minutes each, and organizing the technologies takes the rest. My first estimate of 2 hours was too high.
- **Totals:** 631 pages visited, 623 stored (all new), 869 never-miss findings, 204 "Other", 26 set aside as noise, 0 problems, and 1,150 technologies organized.
- **Pages per source:**
  - all 60: Light Reading, CX Today, TeleGeography, IoT Analytics, TechCrunch: venture, GSMA, IETF and arXiv;
  - Sports Video Group 59 of 60, and CERT-In 54 of 60 (some pages had no text to store);
  - Company job boards 13, one per company;
  - Hacker News 16. The link chooser ran out of links it judged promising, and left 179 unchosen.
  - OpenAlex: grants 2, because only 2 new grants matched its 8 topics in the last 30 days.
- **Follow-up, not done:** the note "didn't finish: N links left" should say why the crawl stopped. That's a small code fix, waiting for your go-ahead.
- **Findings per signal type:** 27 of the 29 never-miss types fired at least once.
  - Acquisition or merger 116; Market figure or analyst coverage 108; Partnership 100; Product launch 90; Named deployment 88; Infrastructure build 63; Prototype or field trial 47.
  - Regulation or mandate 34; Standard milestone 31; Funding round 26; **Approval, licence or certification 25 (new)**; Competitor move 23; Security advisory 20; Research breakthrough 17.
  - Government programme or grant 15; Hiring surge or new team 15; Public tender 11; Major outage or cable cut 10; IPO or listing 8; Alliance formed 5.
  - New fund or investment theme, Open-source milestone, Price change and Employment trend 3 each; Shutdown or failed raise and Spin-out or startup launch 2 each; Developer adoption jump 1.
  - **None:** Patent filing or grant (no patent source until the EPO account exists) and Top-conference recognition. Both were expected to be thin (§4).

**Step 6, done (6 Oct).**
- **Assessments:** run `6d0c41a2d13d`, 04:26–07:34 UTC, so 3 hours 8 minutes. It covered all 147 technologies with 3 or more pages (your scope), none skipped and no errors.
  - **Output:** 346 assessments, about 2.4 fabrics per technology, from 4,474 model calls. Of those calls, 4,152 were measure scoring, 147 relevance checks, 147 watch metrics, and the rest the agent's own steps. The portal's ceiling of 10,878 assumed six fabrics for every technology.
  - **Why it took 3 hours:**
    - technologies are assessed one after another, largest first, with 6 calls at a time;
    - each technology costs 2 calls plus 12 per relevant fabric;
    - every call carries all of the technology's pages, and Agentic AI's evidence alone is about 100,000 characters.
  - **Rate limits:** in the first 20 minutes, OpenAI refused 131 requests with "429 Too Many Requests" (the gpt-6-luna limit on our account). All were retried and succeeded, so no score was lost. There were no refusals after that.
  - **Agent step limit:** at 05:12 UTC the analyzer agent used up its 60 steps after 28 technologies. The backup loop carried on through the same list, as it's built to, and nothing was lost or redone.
  - **How solid the scores are:**
    - 1,744 of the 4,152 measure results were scored (42%);
    - 2,408 came back unscorable, each with the reason the evidence fell short;
    - there were no call failures.
  - **Placement:** 136 of the 346 assessments got a priority: P1 5, P2 43, P3 74, P4 2 and P5 12. The other 210 have none, because none of their 4 "potential" measures could be scored. Thin evidence is the cause:
    - 60% of assessments on 6 or more pages were placed (63 of 105);
    - 30% of those on 3–5 pages were placed (73 of 241).
- **Points of View:** job `cba38c759829`, 07:35–07:49 UTC (14 minutes). All 147 were written and none failed.

**Step 7, done early, at your request** (5 Oct, while the collection was still running): `Signals and sources review - v2.xlsx`, made by `make_signals_xlsx.py` from the live radar. Version 1 is in `replaced/Signals and sources review - v1.xlsx`. It has four tabs.
- **Signals:** the same 52 rows, with columns Signal | Old or New | Sources | Already Configured | Added to the code.
  - **Old or New** now marks each of the team's ideas plainly: New – added in v2 (5), New – we already had it (8), New – not added yet (1, patents). Our suggestions are marked added (1) or not added yet (2), and the radar's own types are marked Old (35).
  - **Sources** lists what's read now, what's switched off and why, and what's worth adding.
  - **Already Configured** keeps the 5 Oct state.
  - **Added to the code** says in plain words what changed, and names the real test page for each added type.
- **Sources:** all 111 sources and suggestions the sheet names, each with its horizon, its status, how the radar reads it, what it gives us, the signal types it feeds, and a comment.
- **Notes:** a summary and how to read the sheet.
- **Discussion:**
  - the project mailbox;
  - the customer-demand question for TCL;
  - the 5 Oct decisions;
  - the known gaps;
  - the open questions, including running the horizons side by side.
- **Deviation:** the plan had the per-signal findings of the fresh collection on the Notes tab. You asked for the sheet before the collection finished, so they're left out; the portal's Briefing shows them.
