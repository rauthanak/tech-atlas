# Answering the 28 Oct review: specification (v1)

This is what Akshay agreed on 31 Oct, after the review with Ankur Jindal's team on 28 Oct. Every point was checked against the code and the live database (read-only) the same day.

This document says:
- what the product does after the change;
- what stays exactly as it is;
- how each change is checked;
- which client documents change.

How it is built is in `implementation-plan.md` (tech-atlas, the master) and `../../../../../tech-lens/docs/2026-10-31/review-28-oct/v1/implementation-plan.md` (tech-lens).

**Sources**
- `review-comments/10-31-2026/oct28_review.pdf`: our deck for 28 Oct.
- `review-comments/10-31-2026/The Wharton School Mail - Review with Ankur and Tata team - Summary.pdf`: Hasan's summary of 29 Oct, and Abhishek's reply of 30 Oct with test cases.
- `artifacts/Client/Emerging Technology Radar_Reference.pptx`: Tata's own 2×2 and its priority definitions.
- `artifacts/Client/Federated Learning - PoV.pptx`: Tata's Point of View format.

## 1. Rules for this work

1. **Diagnose first.** Every change below names its root cause, found in the code or the data. A change without one is out.
2. **Keep it simple.** Use the radar's own ways of working and nothing new beside them:
   - data enters as pages, from sources, during a collection;
   - judgement lives in skills, which are editable and versioned in the portal;
   - numbers that may change are configuration;
   - a person's choice is a decision, kept and undoable.
   No new services, dependencies, run types or side calls.
3. **Nothing that works today stops working**, except the differences listed in section 4.
4. **Configuration changes go through the app**: edited live through the API or Setup, then written into the seeding data from Setup › Changes ("Keep as defaults"). They are never typed into seed files by hand. At the end, Setup › Changes shows nothing waiting.
5. **Failures say why**, in plain words, where they happen.
6. **Never test on live.** Tests run on `tech_atlas_test*` databases. Screenshots are taken from the running product without pressing anything that changes data.
7. **The test cases stay honest.** The names Abhishek sent are never typed into saved searches, look-for names or skills. We add the kinds of sources that cover those areas and see whether the radar finds them.

## 2. Scope

| ID | What | Asked by | App |
|---|---|---|---|
| R1 | The 2×2 laid out exactly as Tata's radar: axes, quadrant names, P1–P6 | Backlog 1 (Akshay) | lens + config |
| R2 | The measures behind each dot, visible from the 2×2; admins can change one there | Backlog 2 (Akshay) | atlas + lens |
| R3 | Add a source by hand in the portal | Decision 2 ("open sources added by the admin"); Akshay | atlas + lens |
| R4 | The sources Ankur named for early signals, and the kinds of sources the missed test cases need | Guidance 2; Abhishek's test cases | data (through R3) |
| R5 | Counts over the last 2–3 years for "when to act": papers, citations, patents, and startup and funding activity | Guidance 3 | atlas + skill + data |
| R6 | A ballpark market size on each use case | Guidance 4, backlog 3 | atlas + skill + lens |

**Not in scope**, and why:

| Item | Why it's out |
|---|---|
| Deployment changes (external licensed MongoDB, hand-over to Tata's repository) | Akshay, 31 Oct: left for now. |
| Leader's response, BU summary | Parked (Akshay, 31 Oct). Ankur doubts BU heads will enter commitments, and admins already record them per technology and fabric. Hasan is told; a read-only export of commitments for Abhishek's portal is offered. |
| Points of View in Tata's format | Abhishek decides. We send him a mapping first (implementation plan, step 9). |
| Per-fabric relevance view | Marked "future" in the backlog. |
| Fewer measures | A read-only mock-up comes first. On today's data, a grid that reads only four measures moves no dot, because no disruption-threat or serviceable-capture figure has been entered. |
| Changing how the technology-wide Market size measure is scored | Not asked. Tata asked for a size per use case (R6). |
| Sector weighting (BFSI) of use cases | Fabrics are not sectors. Raised again only if Tata insists. |
| Focus list | Akshay is raising it with Hasan and the Tata team. |
| Calibrating where PQC and QKD sit | They are already found but placed wrongly, so a collection can't fix them. They are calibrated after the full run, as their own piece of work. |
| Model judgements made in code instead of a skill | Akshay picks which to fix later. |

## 3. Requirements

### R1. The 2×2 as Tata draws it

**Asked.** "Check the 2×2's axis orientation against your radar (time to impact on the vertical axis)." Akshay chose to copy Tata's radar exactly.

**Diagnosis.** Tata's reference slide puts **Impact Timeline** on the vertical axis, with Now at the top and Later at the bottom, and **Impact Potential** on the horizontal axis, Low to High. Its quadrants:

|  | Low potential | High potential |
|---|---|---|
| **Now** | Watch | Act |
| **Later** | Wait | Plan |

Its six priorities sit in 3 potential columns × 2 timeline rows:

|  | Low | Medium | High |
|---|---|---|---|
| **Now** | P5 | P3 | P1 |
| **Later** | P6 | P4 | P2 |

Ours today:
- How soon runs across, sooner to the right. How big runs up (`tech-lens/components/frontier/Grid.tsx:243-268`).
- **Our Watch and Wait are the wrong way round:** our Watch is later and smaller, our Wait is sooner and smaller (`Grid.tsx:30-35`).
- Our priority map is `seeds/scoring_config.json`, `priority_grid.grid`. It differs from Tata's in four of nine cells: near_mid P2, near_low P4, mid_low P5, far_high P3.

**After the change.**
1. **Axes.**
   - The vertical axis is how soon, with the soonest at the top. It is titled "Impact timeline (how soon)", with "Now" at the top and "Later" at the bottom.
   - The horizontal axis is how big, biggest to the right. It is titled "Impact potential (how big)", with "Low" on the left and "High" on the right.
   - In the Defence view, the horizontal axis is the disruption threat, titled "Disruption threat", Low to High.
2. **Quadrants**, with Tata's meanings:
   - Act: now, bigger
   - Plan: later, bigger
   - Watch: now, smaller
   - Wait: later, smaller
3. **The split lines stay where the configuration puts them**: the upper cut-point on each axis, 7 by default. The lower cut-points stay as dotted lines.
4. **The priority map becomes Tata's.**

   |  | high | mid | low |
   |---|---|---|---|
   | **near** | P1 | P3 | P5 |
   | **mid** | P2 | P4 | P6 |
   | **far** | P2 | P4 | P6 |

   - Our three timeline bands stay, because horizons H1–H3 depend on them.
   - "Now" is the near band; "Later" is mid and far.
   - It is a configuration change made through the API, then kept in the seeding data from Setup › Changes.
5. **The same layout everywhere a grid is drawn**: the leaders' 2×2, the print pack, the priority table on Setup › Scoring › Weights & Grid, and the "How a cell is chosen" table on an assessment run's page. All are now time down the side and impact across.
6. **Words follow Tata's definitions**:
   - The priority legend becomes "Priority P1 (act now) to P6 (no action yet)". Today P6 says "just watch", but Watch is Tata's P5.
   - The leaders' help text describes the new corners.
7. **Unchanged**:
   - how scores, bands, priorities and horizons are computed;
   - zoom and pan, and dots that share a point;
   - the frontier line and its band (it still joins the dots no other beats on both axes);
   - the Growth and Defence views;
   - the fabric and stage filters, the table view, and "Act now: P1".
8. **Older editions** keep the priorities they were published with. The new map applies from the next edition, after Redo scores on the latest run.

**Checks.**
- A unit test maps each of the nine band pairs to Tata's priority.
- On the running portal, a dot with high how soon and high how big sits top-right in Act. One with low how soon and low how big sits bottom-left in Wait.
- Both priority tables show time down the side.

### R2. The measures behind a dot, from the 2×2

**Asked.** "Make the scores and sub-scores behind each placement visible and adjustable" (committed).

**Diagnosis.**
- Every assessment stores each measure's score, reason and pages (`assessments.measures`).
- An admin can already replace one score by hand, with a reason (decision `hand_score`), on the technology's Assessment tab. The dot moves at once on live data (`src/app/services/effective.py`).
- The 2×2's tooltip only says "from N of M measures", and **a click on a dot goes straight to the Point of View** (`Grid.tsx:214`).
- The 2×2 exists only on the leaders' site, which shows the published edition.
- The edition doesn't record which measures make "how soon" and "how big".

**After the change.**
1. **Clicking a dot opens a side panel**, on the right of the grid (below it on a phone). The panel shows:
   - the technology, fabric, priority, quadrant and evidence word;
   - **How soon**, from its measures: each measure's name, its score 0–10, and the first sentence of its reason, with "more" for the rest and its pages;
   - **How big**, the same way;
   - for a measure without a score: "Not scored" and what would show it, or "Waiting for Tata's figure", as on the Point of View;
   - **Open the Point of View**: the old click behaviour, one more click away.
2. **The measures shown are the ones that placed this dot in this edition.** At publish, the edition records which measures make each axis, next to its cut-points. An edition published before this change has no such record, so its panel shows every measure, under "Measures".
3. **For admins only**, each measure has **Change**:
   - It opens the same small form as Score by hand on the Assessment tab: a score 0–10 and a required reason.
   - It saves the same `hand_score` decision.
   - After saving, the panel says: "Saved. The dot moves in the next edition; on the technology's Assessment tab it applies now." The link goes to that tab.
   - Undoing works where it does today, on the Assessment tab.
   - Leaders see no Change.
4. **Where the numbers come from**: the edition's frozen Point of View. A dot whose technology has no Point of View in the edition shows its how soon and how big only, with "No Point of View in this edition, so its measures aren't shown."
5. **Unchanged**: the tooltip on hover, the table view (its rows still open the Point of View), and the Point of View page itself.

**Checks.**
- An API test: a published edition records which measures make each axis.
- A test: a `hand_score` saved from the panel's call is the same decision the Assessment tab saves.
- On the running portal (on a scale copy, never live), a click opens the panel; Change is shown to an admin and not to a leader.

### R3. Add a source by hand

**Asked.** We told Tata (decision 2) that open sources are added by the admin. Akshay asked for this as its own requirement.

**Diagnosis.** It can't be done today.
- The API has list, read and edit, but no create (`src/app/api/sources.py:55-106`), so a new source means editing `seeds/sources.json`.
- The rest already works for a new item: Setup › Changes lists items added in the app, and "Keep as defaults" writes them into the seeding data (`src/app/services/db/seeding.py`, `ID_FIELDS["sources"]`).

**After the change.**
1. **Setup › Sources gets an Add source button.** The form asks for:
   - **What kind**:
     - *Website*: the radar reads its pages.
     - *Data source*: the radar runs saved searches through one of its connectors, for example OpenAlex papers, OpenAlex trends, EPO patents or EPO patent trends.
   - **Name** and **home address** (http or https).
   - **Horizon** H1–H3, **group** (chosen from the groups already used, e.g. "Analysts and trade press"), and **cost** (free, free tier, licensed).
   - For a website: **start pages** (optional; the home address is used when there are none) and **follow links to other sites** (on or off).
   - For a data source: the **connector**, with its search help and an example, and the **saved searches**, one per line.
   - **Switched on**: yes or no.
2. **The source's id is made from its name**, for example "Converge Digest" becomes `converge_digest`. If that id is taken, the form says so and asks for another name. The id never changes afterwards.
3. **Rules**, the same as editing:
   - addresses must be web addresses;
   - start pages are for websites only, saved searches for data sources only;
   - a licensed source can't be switched on unless paid sources are allowed (`INCLUDE_PAID_SOURCES`);
   - a connector whose keys are missing shows "Not configured: set … in .env", and the source can be saved switched off.
4. **A new source is live at once.** The next collection reads it. It appears on Setup › Changes as added, with who added it and when, and "Keep as defaults" writes it into the seeding data.
5. **A source added in the app can be switched off but not deleted**, like every other source, so the pages already collected keep their source.
6. **Unchanged**: the source list, the edit page, and how collections read sources. The run report already says why a website gave no pages.

**Checks.**
- API tests cover: add a website; add a data source; a taken id is refused; start pages on a data source are refused; an unknown connector is refused; a licensed source switched on is refused.
- A test: a source added through the API shows on Setup › Changes as added, and "Keep as defaults" writes it into a copy of the seed file.

### R4. The sources Ankur named, and the ones the missed test cases need

**Asked.**
- Guidance 2, early signals: patents with no startup yet; technologies absent from VC portfolios; university research in the US, Israel, Canada, Singapore and China; standards and open-source communities (IEEE, IETF, MEF); collaboration announcements.
- Abhishek's discovery cases, and two quadrant cases the radar couldn't place or find.

**Diagnosis** (live data, 31 Oct):

| Case | Today | Why |
|---|---|---|
| Internet of Cognition | not found | It was announced on Outshift by Cisco, a separate site from Cisco Blogs (which is on). Fierce Network covered it but is **switched off**. The Next Platform isn't in the list. |
| Linear drive pluggable optics | not found | No optics or data-centre trade press in the list (Light Reading is on but covers telecom). |
| Near-packaged optics | 1 page, thin | The same gap. |
| Distributed low-communication training | not found | arXiv is on, but only seven "recent" lists, and machine learning (cs.LG) isn't one of them. Google DeepMind's publications aren't in the list. |
| QRNG | thin (4–5 pages), split across two names | Few pages. The two names weren't merged at the first checkpoint. |

Ankur's other kinds of sources: no Israel or Canada universities; no IEEE standards news; Y Combinator, GitHub, MIT CSAIL and Stanford AI are off; EPO patents are off because the free keys are empty.

**After the change.** Before the full run, these sources are added (through R3) or switched on:

| Kind | Source | Action |
|---|---|---|
| Test case: Internet of Cognition | Outshift by Cisco (blog), The Next Platform | add |
|  | Fierce Network | switch on |
| Test cases: optics | Lightwave, Converge Digest | add |
| Test case: AI training methods | arXiv: add the cs.LG list to arXiv's start pages | edit |
|  | Google DeepMind (publications and blog) | add |
| Universities | Technion, Weizmann Institute, Tel Aviv University (Israel); Vector Institute, Mila, University of Waterloo IQC (Canada) | add |
|  | MIT CSAIL, Stanford AI Lab | switch on |
| Standards | IEEE Standards Association news | add |
| Startups and open source | Y Combinator (company directory), GitHub | switch on |
| Patents | EPO Open Patent Services | switch on, once Akshay has put the free keys in `.env` |
| Trends | OpenAlex trends, EPO patent trends (R5) | add |

1. **Each new or switched-on website is checked before the run by opening its start pages.** One that gives no readable page is fixed or left off, with the reason recorded in the build notes.
2. **No source uses the test names** in its start pages or saved searches.
3. **Pages per source** goes from 60 to 120 for this run (Setup › Sources › Settings). It stays at 120 unless Akshay lowers it.

**Checks.**
- Before the run, the run preview lists every new source and any saved search that would be "too broad".
- After the run, the run report shows pages from each new source, or says why it gave none.

### R5. When to act: counts over the last 2–3 years

**Asked.** "What to watch to decide when to act: startup activity, seed and incubator funding, and growth in patents and citations over the last two to three years."

**Diagnosis.**
1. **Saved searches are a catch-up stream, not a trend.**
   - On its first run a saved search looks back `lookback_days` (30). After that it reads from where it stopped, oldest first.
   - Each run shares the page budget across a source's searches: 60 pages over 20 OpenAlex searches is 3 papers per search (`src/agent/scout/tools/adapters/base.py:121, 166-203`).
   - Every OpenAlex paper we hold is from 2026 (52 papers).
   - Raising the look-back to 3 years wouldn't give a trend. Each search would start in 2023 and take a few of the oldest papers per run. A broad search would hold more than 2,000 results, be marked "too broad", and stop moving.
2. **The counts already exist at the source.** OpenAlex and EPO both say how many results a search has in a date range. The connector reads that number and throws it away. Nothing asks OpenAlex for citations, or for counts by year or country.
3. **Patents are off**: the EPO source is disabled because its free keys are empty. There are 2 patent pages in total.
4. **Our own funding pages skew to the collection date.** Of 578 dated funding-round pages, 273 are from 2026 and 20 from 2023. They show recent events, not a trend.
5. **Nothing tells the skills to look for Ankur's four metrics.** `watch_metrics` picks 2–4 metrics of its own each time.

**After the change.**
1. **Two new kinds of data source**, using the radar's existing "digest" way of reading. The job boards already work this way: one page per saved search per collection, stating counts. Each saved search gives one page per run:
   - **OpenAlex trends.** For the search's words, in titles and abstracts:
     - papers per year for the last three full years and this year so far;
     - citations per year to the 200 most-cited of those papers, said as exactly that;
     - papers by authors' country for the same years, naming the US, Israel, Canada, Singapore and China first.
   - **EPO patent trends.** For the search's patent query:
     - patent filings published per year for the last three full years and this year so far;
     - the applicants on a sample of up to 25 filings from the latest full year, so a reader can see whether startups or only incumbents are filing.
   - Each page says what was counted and where, with the address of the search, so a reader can check it.
   - The pages are stored, read, summarised and filed under technologies like any other page.
2. **Two new sources use them**: "OpenAlex: trends" and "EPO: patent trends", added through R3. Their saved searches are the same as the existing OpenAlex and EPO sources'. Admins add more the same way (for example a technology in Tata's catalog worth tracking), but never the test names.
3. **The `watch_metrics` skill (v4 → v5) is told to look for Ankur's four metrics first**:
   - startup activity;
   - seed and incubator funding;
   - patent filings per year;
   - research papers and citations per year.

   Each is used whenever the evidence gives it, with the counts per year as its current value and the page as its source. It still adds its own metrics, up to four in all. It never guesses a count the evidence doesn't give.

   This is a skill text change made in the portal, then kept in the seeding data. There are no new blanks, because the trend pages arrive as evidence.
4. **Startup activity and seed and incubator funding** come from:
   - the startup sources switched on in R4 (Y Combinator's directory and the incubators already on);
   - the funding-round, spin-out and partnership signals already found on pages.

   There is no free source of startup counts by year. The metric says "recent events", not a trend, until Tata licenses one (Crunchbase, Dealroom), which would then be added through R3.
5. **Unchanged**: how placement is computed. The counts are evidence for the Growth measure and for the signs to watch, not a new measure. Whether they should move the dot is decided after calibration.
6. **Cost.** Per saved search per run: 3 OpenAlex calls and up to 5 EPO calls, all free. Model calls are unchanged: the trend pages are read like other pages. With the 20 current searches, that is about 60 OpenAlex and 100 EPO calls per collection.

**Checks.**
- Adapter tests with recorded API answers: the counts per year, the citation sums, the country split and the applicants are read correctly. An empty result says "no results"; an API refusal says why.
- After the full run, a technology covered by a saved search has a trend page in its evidence. Its signs to watch name the four metrics where the pages give them.

### R6. A ballpark market size on each use case

**Asked.** "Size the opportunity as a ballpark: hundreds of millions, billions or trillions, or a percentage saving, to rank use cases against each other." Backlog: "Ballpark market-size band per use case, recorded in the system." Akshay, 31 Oct: per technology and fabric (where use cases live); from the data if available, otherwise a comparable with why it was picked, otherwise say there is no reliable data.

**Diagnosis.**
- Use cases already exist: up to two per technology and fabric, written by the `value_levers` skill (v4) in each fabric's call.
- That skill is told "never write a figure", and a check in code refuses any money or percentage in a use case's lever chain or capital note (`src/agent/analyzer/value.py:25, 62-64, 91-92`). So no use case can carry a size.
- The technology-wide Market size measure has its own bands, written in code (`src/app/services/market.py:8`: under $1B … over $100B), not on Hasan's scale.

**After the change.**
1. **Each use case carries a size, chosen by the skill in this order:**
   1. **From the evidence**: a page states the market (or saving) this use case addresses.
   2. **A comparable**: a page states the size of a comparable market, recent or historical. The skill names it and says in a sentence why it is comparable.
   3. **No reliable data**: the reason, and what figure would settle it.

   A size is one of:
   - a market figure in US dollars, with the year and what it covers;
   - a percentage saving, with what it saves on.

   It always cites its page; a comparable cites the comparable's page. The model never sizes from its own knowledge. That keeps what we told Tata on 21 Oct: "never a figure the model makes up".
2. **The band is worked out by the radar**, not the model, from one list of bands in configuration (scoring configuration `market_bands`), on Hasan's scale:
   - under $100M
   - $100M–1B
   - $1–10B
   - $10–100B
   - $100B–1T
   - over $1T

   The **same list replaces the bands in code** for the technology-wide Market size card. A percentage saving shows as "about N% saving on …".
3. **The skill's other rules stay**: the lever chain and capital note still never carry a figure, and the code check stays on those fields. A malformed size doesn't make the use case fail. It is stored as "no reliable data" with the reason it couldn't be used, and the use case is kept.
4. **Where it shows**:
   - **The Point of View's "Use cases, fabric by fabric" table** gets a **Ballpark size** column: the band, or "about N% saving"; "comparable: <name>" with its reason on hover; or "No reliable data" with its reason. Each carries its page number.
   - Within a fabric, use cases are listed biggest first, then savings, then those with no size. The skill's own rank breaks ties.
   - **The admin Assessment tab** shows the same line on each use case.
   - **The Point of View text** may quote a use case's band, with its page number, and must say "comparable" when it is one. This is a `pov` skill text change (v11 → v12) made in the portal. The input heading in code that says "never write a figure" says instead "never write a figure other than the sizes given".
5. **For a use case with "No reliable data", an admin can press Find evidence on that line.** It is the existing Find evidence job, with the existing daily budget and web search. Its query is the technology, the fabric, the use case and "market size". Pages it finds are read like any page, and that fabric's use cases are asked again on the evidence now. A figure found this way is cited like any other.
6. **Published editions** keep their use cases as published; the size appears from the next edition. Older Points of View with no size show "—" in the column.

**Checks.**
- Unit tests of the size check:
  - a size from the evidence;
  - a comparable with its name and reason;
  - no reliable data with a reason;
  - a size citing no page becomes "no reliable data" with the reason;
  - a figure in the lever chain is still refused;
  - the bands come from configuration.
- A Point of View test: the table rows carry their size and sort biggest first.
- A Find evidence test: the query for a use case's size names the use case and "market size".

## 4. Everything a person could notice

| Where | Today | After |
|---|---|---|
| Leaders' 2×2 | How soon across, how big up; Watch = later and smaller, Wait = sooner and smaller | Impact timeline down the side (Now at the top), impact potential across; Watch = now and smaller, Wait = later and smaller (Tata's) |
| Priorities | Our map | Tata's map from the next edition (R1 table); legend "P1 (act now) to P6 (no action yet)" |
| Setup › Scoring › Weights & Grid, and a run's "How a cell is chosen" | How big down the side, how soon across | Time down the side, impact across |
| Clicking a dot | Opens the Point of View | Opens the panel with the measures behind it; Open the Point of View is in the panel |
| Panel, admin | — | Change on each measure (a hand score, shown in the next edition) |
| Setup › Sources | Edit only | Add source |
| Setup › Changes | — | Added sources listed as added |
| Sources list | — | New sources and connectors: OpenAlex trends, EPO patent trends, the sources in R4 |
| Evidence of a technology | — | Trend pages (counts per year) where a saved search covers it |
| Signs to watch | The skill's own picks | Ankur's four first, where the pages give them |
| Use cases (Point of View, Assessment tab) | No size | Ballpark size, comparable, or "No reliable data", with page; Find evidence on a missing size |
| Point of View Market size card | Bands under $1B … over $100B | Bands under $100M … over $1T |

## 5. Client documents to update (AGENTS.md)

| Document | What changes | For |
|---|---|---|
| Product Guide | The 2×2 description and figure; the panel; Add source; trend pages and signs to watch; ballpark size on use cases | R1, R2, R3, R5, R6 |
| Administrator's Training Manual | How to add a source; the panel and Change; Part 4: `watch_metrics` v5, `value_levers` v5, `pov` v12, and the two new connectors; new screenshots | R1–R3, R5, R6 |
| Business process (cards and flowchart) | Only if a step's wording changes. Expected: the Evidence step names trend pages; Gate 2 is unchanged | R5 |
| Technical architecture | The two new digest connectors | R5 |
| Client change log (.docx) | One entry per requirement, with before and after screenshots | all |

No dates and no counts of configurable things in client documents. Screenshots come from the running product.

## 6. Decisions taken in this specification (Akshay can overrule any)

1. **Trends come from digest pages, not a longer look-back** (R5, diagnosis 1). A 3-year look-back would fill each run with a few of the oldest papers, and stall broad searches as "too broad".
2. **A comparable must come from a page.** One already in the evidence, or one found by Find evidence (web search), pressed by an admin for that use case (R6.5). There is no automatic web search on every use case, which keeps runs fast and their cost the same.
3. **One list of market bands for both** the use cases and the technology-wide Market size card, on Hasan's scale (R6.2).
4. **A click on a dot opens the panel**; the Point of View is one more click (R2.1).
5. **The axis titles use Tata's words, with ours in brackets**: "Impact timeline (how soon)", "Impact potential (how big)". Other screens keep "how soon" and "how big".
