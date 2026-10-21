# Cut-point check (plan 9, item 5)

The full stacked run (c1d0d08c9f43) against the 6 Oct run (6d0c41a2d13d), with the cut-points now on Weights & Grid: how soon [4.0, 7.0], how big [4.0, 7.0]. A score below the low cut-point is in the lowest band, above the high one in the highest. Only technology-fabric pairs with both scores count.

## How soon

- **Full run** (500): lowest 0.0 · 10% 2.5 · 25% 4.0 · median 5.5 · 75% 7.0 · 90% 8.0 · highest 9.0
- **6 Oct run** (220): lowest 1.0 · 10% 3.0 · 25% 5.0 · median 6.0 · 75% 7.5 · 90% 8.0 · highest 9.0

- Bands now, full run: near 99 (20%) · mid 297 (59%) · far 104 (21%)
- Bands, 6 Oct run: near 56 (25%) · mid 133 (60%) · far 31 (14%)
- Cut-points that would give the full run the 6 Oct share: [3.5, 7.0]

## How big

- **Full run** (399): lowest 1.0 · 10% 4.0 · 25% 5.0 · median 5.5 · 75% 6.5 · 90% 7.0 · highest 8.5
- **6 Oct run** (150): lowest 2.0 · 10% 4.0 · 25% 5.0 · median 6.0 · 75% 6.3 · 90% 7.5 · highest 8.5

- Bands now, full run: high 27 (7%) · mid 357 (89%) · low 15 (4%)
- Bands, 6 Oct run: high 16 (11%) · mid 130 (87%) · low 4 (3%)
- Cut-points that would give the full run the 6 Oct share: [3.5, 7.0]

## Priorities

- **Full run, cut-points as now** (397): P1 9 (2%) · P2 102 (26%) · P3 215 (54%) · P4 1 (0%) · P5 68 (17%) · P6 2 (1%)
- **6 Oct run** (136): P1 5 (4%) · P2 43 (32%) · P3 74 (54%) · P4 2 (1%) · P5 12 (9%) · P6 0 (0%)
- **Full run, with the matched cut-points**: P1 9 (2%) · P2 102 (26%) · P3 248 (62%) · P4 1 (0%) · P5 36 (9%) · P6 1 (0%)


## Reading (21 Oct)

- **The stacked engine didn't shift the scores.** Medians and spreads sit where the 6 Oct run's did (how soon 5.5 against 6.0, how big 5.5 against 6.0). Matching the 6 Oct share of each band would move only the low cut-points (4 → 3.5), and the priorities would change mostly between P3 and P5.
- **More technologies land far out (21% against 14%).** That's the wider set this time, 248 technologies including Tata's emerging ones, not the engine.
- **The real finding is "how big": 89% of placements fall in its middle band** (5–7), in both runs. So the priority mostly follows "how soon", and P1 stays rare (9 of 397). That's a question for calibration with Tata's past cases (November), not a cut-point fix now.
- **Decision: the cut-points stay at 4 and 7.** Weights & Grid can change them at any time, and Recompute re-places everything with no model call.
