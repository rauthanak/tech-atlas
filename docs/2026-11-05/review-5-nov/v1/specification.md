# Review of 5 Nov: hand changes before Publish, "too early to place", checked market figures, and Points of View in Tata's shape: specification (v1)

**Status: built and live on 6 Nov; 529 tests pass; Changes 0. Differences from this plan are listed at the end of the master plan.**

The design and implementation plan is `implementation-plan.md` in this folder. The portal's part is `../../../../../tech-lens/docs/2026-11-05/review-5-nov/v1/implementation-plan.md`. The read-only checks to run before any code are in `pre-build-tests.md`.

## Why

Abhishek's reply of 3 Nov, and Tata's Federated Learning Point of View (`review-comments/11-05-2026/`), raised four things. Akshay settled them on 5 Nov:

1. **Hand changes are invisible at Publish.** An admin can change a score by hand. The change goes to the working copy and reaches leaders at the next Publish. It is recorded (who, when, why) on the technology's History, but the Publish panel only shows counts ("3 priorities moved"). Whoever publishes can't see which scores people changed by hand.
2. **Catalog technologies the radar can't place yet vanish.** A technology from Tata's catalog whose evidence is judged thin or not credible is never assessed, so it never reaches the leaders' view. Tata reads the silence as "missed". Tata wants these shown as "too early", without cluttering the grid, and with a way to switch it off.
3. **The market figure must never be made up.** Today a market figure is kept only when it cites a page the AI was given. Nothing checks that the number is actually written on that page. The growth rate (CAGR) isn't kept as a figure at all.
4. **Tata's Point of View has parts ours lacks.** These are: why customers want it, alternatives, who's building it (value chain and players), risks, what's new, and use cases by industry. Each must come from the evidence, never be invented, and stay short.

## Principles (Akshay, 5 Nov)

- Nothing made up. Every figure and every new bullet is checked in code against the pages, not just asked for in a prompt.
- No over-engineering. No new screens, lists in Setup, weights or services. Each change sits inside something that already exists.
- Think like a first-time reader (Don Norman): one glance shows what matters, details fold away, an empty part says why it is empty, and nothing new has to be learnt.

## What we build

### S1. "Changed by hand" in the Publish panel

- **Where:** the Publish panel (on the Briefing's To do strip and on Operations) gets one more line under "Publishing now sends …": **"4 changes made by hand since Edition FY27 Q3"**. The line folds open to a list.
- **What counts as a change by hand:** everything a person did since the last edition that changes what leaders see on the grid:
  - a score set by hand;
  - a score Tata entered (Disruption threat, Serviceable capture);
  - a priority set by hand;
  - any of these undone.
- **Each row says:**
  - the technology (a link to its page, where the change can be undone);
  - the fabric, when the change is for one fabric;
  - what changed, as a before → after: "Growth: the radar's 5 → 8 by hand", "Priority: the scores give P3 → set to P1", "Disruption threat entered as 7", "Growth scored by hand: undone";
  - who and when, in the person's own time zone, as everywhere;
  - their reason.
- **Point of View check:** if the technology's Point of View was written before the change, the row adds: "Its Point of View was written before this change: rewrite it before publishing". Rewriting uses the button already on the technology page.
- **When there's nothing to list:** no line is shown.
- **Before the first edition:** no line is shown, as for the other "since" counts today.
- **Leaders:** see nothing new. They still can't change scores. Only admins see Change.
- **Not added:** emails, alerts and any approval step.

### S2. "Too early to place" on the leaders' view

- **Who counts:** a technology that meets all of the following:
  - it is in Tata's catalog (imported, or added by a person);
  - it is switched on;
  - its evidence is judged **thin** or **not credible**, a person's choice included;
  - it isn't assessed, so it is neither on the grid nor under "Not placed yet".

  That is about 265 technologies today (251 thin, 14 not credible). Catalog technologies not judged yet don't count: the radar hasn't looked at them, which is a different message. They show on the Technologies list as today.
- **On the grid:** nothing new is drawn. The Wait corner gets one more line under its name: **"+265 too early to place"**. It is a link that jumps to the list below the grid.
- **The list:** a section **"Too early to place · 265"**, right after "Not placed yet", built the same way:
  - one line of explanation: "From Tata's catalog. The radar has looked, but the evidence so far is too thin or not credible to say how soon or how big. More evidence can move them onto the grid.";
  - two folded groups: **"Evidence too thin so far"** and **"Evidence not credible yet"**, each with its count;
  - each technology shows its name and, in grey, the reason the radar gave (e.g. "Only one vendor, across two promotional blog posts"). There's no link, because there is no Point of View.
- **The same in every view:** the line and the list appear the same in every fabric, stage and lens view, and in the edition pack. They are about the technology, not a fabric.
- **Frozen with the edition:** like everything leaders see. A technology that gets assessed moves out of the list at the next Publish.
- **The setting:** Setup › Sources › Settings gets **"Show 'too early to place' on the leaders' view"**, on by default. Switched off, the next edition carries no list and no corner line. Switching it back on brings both back. It is listed on Setup › Changes and kept as a default from there, like every setting.
- **Not changed:** no skill, no scoring rule, nothing on the grid itself.

### S3. Market figures checked against their page, and the growth rate

- **The check:** a market figure is kept only if the exact words that state it are on the page it cites. The AI gives those words with the figure, and the code looks for them in the page's saved text (its full text, or its summary when the full text is no longer kept). If they aren't found, the figure isn't kept, and the card says "No market figure in the evidence".
- **A second check:** where those words give a US-dollar amount, it must match the figure the band is worked out from, within 5%. This catches a slip in converting "$312 million" to 0.312 billion.
- **What the reader sees:** the band, then the page's own words, with its source number. For example:
  > **$100M–1B**
  > "expected to reach USD 312.4 million by 2030" (federated learning platforms, 2030) [4]
- **Growth rate:** the Growth measure gives a growth rate when a page states one, with the same words-on-the-page check. The Market size card shows it under the size: **Growing:** "a CAGR of 15.2% from 2024 to 2030" [4]. Otherwise it shows "No page gives a growth rate". The AI never works a rate out from two figures.
- **The same check for use-case sizes:** each use case's ballpark size already cites its page, and gets the same words-on-the-page check.
- **What doesn't change:** the bands (Setup), the rule for wider markets ("Wider market:"), or the scoring.

### S4. An industry on each use case

- Each use case keeps its fabric and gains an **industry**, for example "Banking and financial services", "Healthcare", "Manufacturing", or "Cross-industry".
- The list of industries is part of the use-case skill's text (Setup › Skills), so Tata can edit it there. No new list in Setup.
- **Shown:** as a small grey label next to the use case's title, in the Point of View's use-case table and on the technology's Assessment tab.
- **Order:** biggest ballpark size first, as today. That ordering already answers "which sector is biggest". **No sector weights:** we'd have to invent them.

### S5. Five short new parts in the Point of View

The Point of View skill writes five more parts, from the same assessment data and pages:

| Part | What it says | From |
|---|---|---|
| **Why customers want it** | The needs that pull buyers to it (privacy rules, cost, sovereignty…) | What the pages say about buyers, regulation and demand |
| **Alternatives** | Other ways to solve the same problem, each with how it differs in one line | Pages that compare it with other approaches |
| **Who's building it** | The companies and groups named on the pages, each with what they do (e.g. "Google: open-source framework") | Names on the pages |
| **Risks** | What could stop it, or stop it paying off for Tata | The strongest argument against each score (already in the assessment) and risks the pages state |
| **What's new** | The latest developments, each with its date | The newest dated pages |

**What the skill reads:** today the Point of View skill sees the assessment (scores, reasons, arguments against, use cases) and only the titles and dates of the pages. For these parts it also needs what the pages say, so each cited page's short summary is added to its list of sources.
- Summaries are about 230 words' worth of tokens each, and a Point of View cites about 16 pages on average (80 at most).
- So each Point of View reads about 4,000 more tokens of input, 18,000 at most.
- The parts come only from the pages the assessment cited. If those pages don't cover a part, the part says so.

**The rules, enforced in code:**
- Each part has at most 3 bullets ("Who's building it" up to 5), one short line each.
- Every bullet ends with its source number(s). A bullet that cites no listed page is dropped.
- No figure unless the page gives it, with its number. This is the existing Point of View rule.
- When the pages don't cover a part, it shows one line: "The pages reviewed don't cover this yet." On the admin's page it also links to Find evidence. The part doesn't vanish, because a missing part looks forgotten.

**Where they sit (first-time reader in mind):**
- **Risks** sits right under the Recommendation, open. A decision-maker reads the stance and what could go wrong together.
- The other four sit in one new fold, **"The market around it"**, after the use cases. Its hint names what's inside: "why customers want it · alternatives · who's building it · what's new".
- Everything else on the page stays where it is.

**Older Points of View:** a Point of View written before this change has none of the five parts. The page doesn't show empty headings for it: the parts appear once it is rewritten.

## Not in this piece of work

- Sector weights, an industry list in Setup, fixed value-chain stages, links between technologies, or a fabric ranking.
- A range of market estimates from several pages.
- Emails or alerts about hand changes.
- Watch metrics that decide adoption (the quality point in `pov-mapping.md`). That is a separate skill fix, raised later if Akshay wants it.
- Login to protected sites (advised against, 5 Nov).

## Decisions for Akshay before building

1. **Market figures already stored have no page words.** There are two options:
   - **(a)** keep showing them until each technology's next assessment, then the check applies;
   - **(b)** hide them now, so the card says "Checked from the next assessment".

   Pre-build test 1 shows how many of today's figures can actually be found on their page. **Recommendation:** decide after that test. If most are found, (a); if many aren't, (b).
2. **Bringing existing work up to date after the build** costs model calls. The cost is shown before each run:
   - Points of View are rewritten to gain the five parts;
   - re-assessing gives figures their page words, the growth rate and the use-case industry.

   **Recommendation:** rewrite the Points of View of the catalog technologies first, and re-assess only when Tata asks for a fresh edition.
3. **The industry list** in the use-case skill. Proposed: Banking and financial services; Healthcare and life sciences; Manufacturing and industrial; Retail and consumer; Media and entertainment; Government and public sector; Energy and utilities; Telecom and technology; Transport and logistics; Cross-industry. Akshay or Tata may change the wording.
