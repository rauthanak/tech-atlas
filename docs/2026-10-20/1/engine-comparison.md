# Engine comparison (plan 9, item 5)

**Written 20 Oct 2026.** Both engines ran on the same model (Anthropic claude-haiku-5-5) and the same pages, so only the engine differs.
- **Stacked:** one technology call (the fabric choice, the measures judged for the technology as a whole, metrics to watch, and domain, TRL and availability), then one call per relevant fabric for that fabric's measures.
- **Per measure:** one call per measure per fabric, plus the fabric choice and metrics to watch, each sending the full evidence.

The sample: 12 technologies on the stacked engine (run `3f40a14a2cbb`) and 6 of them on the per-measure engine (run `9c9da9803221`), one of each kind: P1 (Data centers), P2 (5G, Contact center as a service), P3 (YANG data modeling), P5 (DOCSIS 4.0), and held (Post-quantum cryptography). The per-measure baseline was kept to 6 to hold its cost down (it uses about 12 times the tokens).

## First try: five measures judged for the technology as a whole

As agreed in 3b: addressable market, growth, use-case breadth, maturity (TRL) and commercial adoption, once per technology.

- Scores differed from per-measure by **1.31 on average** (median 1.0); 65 of 95 within one point.
- **Two measures differed a lot, always upward:** commercial adoption **+3.25** and use-case breadth **+2.92**. Maturity agreed (+0.08).
- **Why:** judged for the technology as a whole, 5G's commercial adoption is worldwide; judged in a fabric, it's adoption in Tata's IoT or network business. Higher adoption raises "how soon", so priorities moved up a step or two (P3 → P2, P5 → P3, P6 → P3).
- Priority the same in 4 of 12 pairs.

## The change: commercial adoption and use-case breadth judged per fabric

Both moved to "Scored per fabric" (Setup › Measures, seeded). This costs no extra calls: they ride in the fabric call that runs anyway. Then the same 6 technologies were re-assessed on the stacked engine (run `8523a82bc5b6`).

### Stacked (after the change) against Per measure


Technologies: 6; technology-fabric pairs in both: 13; measures compared: 130 (Tata's two measures left out: the stacked engine doesn't ask the model for them).

| | Stacked | Per measure |
|---|---|---|
| Fabrics chosen, same as the other | 3 of 6 technologies | |
| Measures scored | 121 of 130 (93%) | 101 of 130 (78%) |
| Model calls (these technologies) | 19 | 204 |
| Tokens sent | 519,852 | 4,287,124 |
| Tokens at the full price (reused at a tenth, stored at 1.25) | 367,485 | 4,287,124 |
| Tokens written back | 102,155 | 281,713 |

Where both scored a measure (101): the scores differ by 1.04 on average (median 1.0); 77 of 101 are within one point.

Priority the same in 6 of 13 pairs; horizon the same in 9 of 13.

Average difference by measure (where both scored it):

- addressable-market: 1.86 over 7
- capability-gap: 1.33 over 9
- commercial-adoption: 1.33 over 9
- deliverability: 1.00 over 8
- fabric-fit: 0.85 over 13
- growth: 0.62 over 13
- maturity-trl: 0.54 over 13
- portfolio-adjacency: 0.62 over 13
- right-to-play: 1.00 over 3
- use-case-breadth: 1.77 over 13


## Decision

- **The stacked engine is switched on** (Scoring method › Weights & Grid, seeded), with commercial adoption and use-case breadth scored per fabric. Addressable market, growth and maturity stay per technology.
- **Why:** like for like it takes 19 calls instead of 204 and about 12 times fewer tokens at the full price; it scores more measures (93% against 78%); and its scores sit about one point from the per-measure engine's, with no measure more than two points off on average.
- **Still to watch:** priorities match in 6 of 13 pairs. A priority moves when a score crosses a cut-point (4 and 7), so a one-point difference can change it. After the full run, the cut-points on Weights & Grid should be checked against the spread of scores; Recompute applies a change at no model cost.
- **The per-measure engine stays available** as the other choice on Weights & Grid, until you've read this.
