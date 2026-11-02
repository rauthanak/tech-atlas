# Vertical search, and pages per source: specification (v1)

**Status: approved and built on 1 Nov; live; 516 tests pass. Differences from this plan are listed at the end of the master plan.**

The design and implementation plan is `implementation-plan.md` in this folder. The portal's part of it is `../../../../../tech-lens/docs/2026-11-01/vertical-search/v1/implementation-plan.md`.

## Why

The radar gathers evidence in one direction only.

- **Horizontal (what it does today).** A collection goes to each source and reads up to the page budget. Technologies emerge from whatever it read. It never asks a source "give me everything about QKD". The data sources (OpenAlex, patents) work the same way: they run a fixed list of saved searches that an admin typed, and the page budget is split across them. OpenAlex papers has 20 saved searches, so it reads about 7 papers per search per collection, oldest first.
- **Vertical (missing).** Nothing goes from a technology to the sources. Find evidence comes closest, but it runs one web search for one gap and reads at most 5 pages. It doesn't use the radar's own sources, it searches under one name only, and it can't count.

So the radar is good at noticing technologies and weak at going deep on one. Abhishek's test cases show where that matters:
- "Is PQC Act or Plan?" turns on how fast adoption and research are growing;
- QRNG has thin evidence;
- a technology held under two names has its evidence split.

A second, smaller gap: every source gets the same page budget (150). A large trade site and a single event page are treated alike. Also, a fixed limit in the crawler stops any website at about 120 pages, whatever the budget says.

## What we build

### S1. Pages per source

- Each source gets an optional **Pages per collection** on its edit page (Setup › Sources). Left blank, it uses the default in Setup › Settings (150 today).
- It works for websites and data sources alike. For a data source, its saved searches share it, as they share the default today.
- Order of priority: a test run's own page limit (used only for tests), then the source's number, then the default.
- The run preview's estimate adds up each source's own budget. A run's report judges "not read to the end" against each source's own budget.
- It is a configuration change like any other: it is listed on Setup › Changes and kept as a default from there.

### S2. Crawl depth and links per level, in Setup

- **Today.** A crawl goes level by level: the start pages, then the links on them, then the links on those, up to 8 levels. At each level it keeps at most 15 links, picked by the AI as the most promising. So a website can never give more than about 1 + 8 × 15 ≈ 121 pages. 121 of the 133 websites in the 1 Nov run stopped there, with links still waiting. The 8 is fixed in the server's `.env` and the 15 in the code, so neither can be seen or changed in the portal.
- **After.** Setup › Settings gets two settings beside the page budget:
  - **Levels of links to follow:** 8 by default.
  - **Links kept per level:** **Automatic** by default, or a fixed number.
- **Automatic** shares the pages left across the levels left, and never keeps fewer than 15. With 149 pages left over 8 levels it keeps 19 per level, so a website reaches 150. With a budget of 300 it keeps about 38. Any page budget can be reached.
- **A fixed number** is used as given. If a page budget can't be reached with it, the form says so wherever that budget is entered (the default, or a source's own): "With 8 levels and 15 links per level, a website reaches at most 121 pages. Choose Automatic, or raise links per level to 19, to reach 150." Saving is still allowed. The source's row shows the same warning.
- **Either way, the form shows how a website will be read:** "Reads up to 150 pages, up to 8 levels deep, about 19 links per level."
- Neither setting changes which links are picked, only how many and how deep.
- A run records both in its crawl settings, like the page budget, so a past run shows what it used.

### S3. Find evidence becomes a vertical search

One button still, **Find evidence**, in the same places: on the technology, and beside each gap (a measure it couldn't score, a use case without a size, a fabric without a use case). Clicking it opens a small panel with three choices, each with a default. A person who just clicks **Find** gets a sensible search.

| Choice | Default | What the person can do |
|---|---|---|
| **What to look for** | From the gap clicked (as today); from the technology's button, "everything about it" | Nothing to type. The search always uses all of the technology's names |
| **Where to look** | Every place that can be searched now | Untick places. The places are below |
| **How many per place** | 5 | Choose 5, 10 or 20, or Other for any number from 1 to 50 |

**The places.** They are built from the radar's own sources, so they change as sources are added or switched on and off.

| Place | How it's searched | Gives |
|---|---|---|
| **Research papers** (OpenAlex) | A one-off search by the technology's names, most-cited first, over the last three years | Papers, read like any page |
| **Research grants** (OpenAlex) | A one-off search, newest first | Grants, read like any page |
| **Patents** (Espacenet) | A one-off search, newest first | Patent documents, read like any page |
| **Research and patent counts** (the trends sources) | The counts query, by the technology's names | One page of yearly counts: papers, citations, countries, grants, patent filings. This answers "how big, and is it growing" |
| **The radar's websites** | A web search limited to the addresses of the radar's switched-on websites | Pages from the trade press, labs and blogs the radar already trusts |
| **The whole web** | A web search, as today | Pages from anywhere |

US federal job postings are offered as counts too. A data source whose saved searches aren't words, such as SEC filings and company job boards (both searched by company), is shown greyed out with why.

- **A place that can't be searched is shown greyed out, with why.** For example: "needs the patent-office keys (see the Deployment Guide)", "switched off: its site asks crawlers not to read it", "licensed: off until Tata gives access", "no web search set up".
- **A source that isn't on the radar isn't offered.** The panel links to Add source, so it is added the normal way first. Then it collects in every collection, not just this once.
- **Before it runs, the panel shows the cost:** about N pages to read (one model call each) and M web searches.
- **Nothing is added to any source's saved searches.** A vertical search is a one-off.

**While it runs and after.** The panel reports per place: pages found, pages new, filed, set aside by a Can ignore rule, or not read, and why. A place that found nothing says so. The pages are saved like any collected page:
- under the source they came from (Research papers, a radar website), or under "Web search";
- marked as found by this search;
- filed under the technology.

**What it re-judges.**
- From a gap: only the judgement behind that gap, as today.
- From the technology's button ("everything about it"): its evidence is judged again (one Classify call, as today). It is not assessed automatically. It shows as having new pages since its last assessment, as with any new page, and Assess lists it. The panel's last line says so and links to it.

**No daily budget** (Akshay, 1 Nov). The person decides in the panel, seeing the cost before pressing Find: how many places, how many pages per place, the searches and model calls that makes. The setting "Find evidence: searches per day" is removed from Setup › Settings and the seeding data, as "No silent caps" asks.

**Fairness rule.** A vertical search starts from a technology the radar already holds. No one types a technology's name into it. That keeps Abhishek's test cases fair: the radar has to find a technology before anyone can search deeper on it.

### S4. Write Points of View waits for Assess

- **Today.** While an assessment run is going, Write them is still offered. Pressing it writes the Points of View that are ready, and the last few then need another run. A technology still being assessed could get a Point of View from a half-finished assessment, with some fabrics new and some old.
- **After.**
  - While an assessment run is going, Write them is greyed out with the reason: "Waits for the assessment run to finish (308 of 311)."
  - The server refuses it too, with the same reason, so it holds even if two people use the portal at once.
  - Writing a single Point of View from a technology's page is unaffected.

### S5. Small fixes

- The run page's progress line says "308 of 311 technologys". It will say "technologies".
- Organize says "Merged 12,981 names from every page collected so far". In a normal collection it merges only the names on the new pages (9,009 pages on 1 Nov). It will say "Merged 12,981 names from the 9,009 new pages", and keep "from every page collected so far" for a full re-organize.

### S6. Publish to leaders on the Operations page

- **Today.** Step 6 of the run page says "Publish on the Briefing →", and the person has to go to another page to finish the process.
- **After.** Step 6 carries the Publish button itself. It is the same action as on the Briefing: the same panel (what leaders will see change, the edition's name) and the same confirmation. The Briefing keeps its button too.
- Publish is refused while an assessment run is going, as today. The button is greyed out with that reason.

## What we don't build

- No search of a site's own search box, and no new crawler. The radar's websites are searched through the web search, limited to their addresses.
- No automatic vertical search across all technologies. It is a person's action, with its cost shown. A later version can offer it for the technologies due for assessment.
- No new place that isn't a radar source.
- No change to how collections pick sources, or to the skills.

## Decisions for Akshay

1. **Name:** decided (Akshay, 1 Nov): keep "Find evidence".
2. **From the technology's button, judge its evidence again and put it on Assess's list, rather than assessing it at once?** Agreed (Akshay, 1 Nov), on condition that assessing one technology on its own stays possible. It does: the technology's page keeps **Assess now** (or **Assess anyway** when its evidence is thin). Once it's assessed it has no new pages since its assessment, so it leaves Assess's list by itself.
3. **Daily budget:** decided (Akshay, 1 Nov): no daily cap. The person sees the cost in the panel and decides there.
4. **How many per place:** decided (Akshay, 1 Nov): 5, 10, 20 or Other. Other opens a box for any number from 1 to 50 (the limit is shown beside it).
5. **Crawl depth and links per level:** decided (Akshay, 1 Nov): a hybrid of both ways. See S2.

## Things to test before building S3

- **Web search limited to the radar's websites.** The model's web search takes a list of allowed addresses. We have about 110 websites. Check that a list that long is accepted (or split it into a few searches), and that smaller sites come back at all.
- **OpenAlex allowance with the key.** One vertical search of research papers and counts makes about 6 OpenAlex requests. Check what that uses of the $1 daily allowance.

## Documents to update when built

Business process (cards and flowchart: Find evidence's new choices; "Write them" waits for Assess; Publish from the Operations page), technical architecture (Find evidence reads the radar's data sources), Product Guide, Administrator's Training Manual (Find evidence panel, Pages per collection, screenshots), Deployment Guide (the link depth moves from `.env` to Setup › Settings), client change log.
