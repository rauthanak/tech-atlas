# 10-million-page test, 24 Oct 2026 (interim)

Copy: 10,000,000 pages, 315,420 technologies, 600 collections over two years; 147 GB of data, 78 GB on disk,
5 GB of indexes. This Mac: Docker 12 GB; the copy's database cache 6 GB (no container caps). Stand-in model
(MODEL_PROVIDER=standin): the radar's own work timed, no model calls. Files: perf-10m-during-upkeep.txt,
perf-10m-during-collection.txt, e2e_scale.py.

## Background processes

| Process | Measured | Note |
|---|---|---|
| Generating the copy | 21 min | scale_copy.py |
| Building every index (API start) | 74 min | about 5 min per index; the API answers nothing until done |
| Briefing days, start-up catch-up | about 6 s a day (730 days ≈ 70 min alone) | 134 done in 3.8 h while everything else ran |
| Technologies' stored answers, full recount | 7,000 of 315,420 in 3.8 h (0.5 a second) | each technology re-reads its pages from disk; runs after every collection |
| Collection: crawl of 86 sources, 15 pages each | 15 min 41 s, 1,151 pages | real websites; reading by the stand-in |
| Collection: Organize | not finished after 5 h 20 min ("gathering") | reads every stored page each collection |
| Assessment of the 50 biggest technologies | 0 of 50 after 1 h 40 min | each dossier reads all 20,000+ pages of its technology |
| Points of View, publish, import, rename, Check again | not reached | behind the steps above |

## Screens (one call; five at once)

| Screen | During start-up upkeep | During the crawl |
|---|---|---|
| Briefing, a week / 30 days / all time | 0.02 s | 0.05–0.11 s |
| Briefing: To do | 0.57 s | 0.49 s |
| Technologies | 0.59 s | 0.46 s |
| A technology's pages (biggest) | 30.6 s | 35.6 s |
| Points of View | over 120 s | over 120 s |
| Status line (first call) | 6.0 s | 2.1 s |
| Leaders' view | 0.69 s | 0.11 s |

## Why

83% of each page record (26.6 KB on average) is the page's full text. At this size neither fits in memory, so
every step that reads pages reads them from disk, and five steps read many or all of them: Organize (every
page, every collection), the stored-answer recount (each technology's pages, all technologies after every
collection), an assessment's dossier (all of a technology's pages), a technology's page list, and the Points of
View list (pages of each technology written from an older assessment).
