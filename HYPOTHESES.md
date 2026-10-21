# Pre-registered hypotheses

**Lock this file before looking at real results.** Commit it to git with a date. If you add or change
a test later, record it under "Deviations" instead of editing the originals. This is what protects the
project from the "you ran 40 tests and reported the 3 that worked" objection.

Primary measurement: market price `horizon` days before close (default 7), last observation within
`max_stale` days (default 3). Unit of analysis: one contract. Standard errors: cluster bootstrap by event.
Family of tests for multiple-comparison correction (Holm): H1, H2-longshot, H2-favorite, H3, H4.

| ID | Hypothesis | Statistic | Null | Reading |
|----|-----------|-----------|------|---------|
| H1 | Prices are calibrated | Slope of logistic regression of outcome on logit(price) | slope = 1 | >1: realized odds more extreme than prices (favorite-longshot pattern). <1: prices overconfident |
| H2a | Longshots (price <= 10c) are overpriced | mean(outcome - price) | 0 | negative supports FLB |
| H2b | Favorites (price >= 90c) are underpriced | mean(outcome - price) | 0 | positive supports FLB |
| H3 | Trade prices heap at round numbers | count at 50c / mean count at 48,49,51,52c | ratio = 1 | >1 supports anchoring on round numbers |
| H4 | Prices overreact to large jumps | mean of sign(jump) * (outcome - post-jump price) | 0 | negative = overreaction, positive = underreaction |

Secondary / exploratory (report as exploratory, no significance claims): differences by category, by
platform, by volume tercile, by horizon (1, 3, 7, 14 days).

## Economic significance
After each test, ask whether a rule exploiting the bias would survive fees and half-spread
(`analysis.edge_after_costs`). A statistically real bias that costs more than it pays is still a finding.

## Known threats (address each in the write-up)
- Selection: which markets does the API return? Document the sampling rule.
- Correlated contracts: handled by the event-cluster bootstrap; check that `event_id` is meaningful on each platform.
- Stale/thin prices: `stale_days` and volume filters; show results are robust to them.
- Resolution ambiguity and early-resolving markets.
- Time-varying market quality (platforms matured; consider a pre/post split as a robustness check).
- Lookahead: tests assert every snapshot price is timestamped before the target time.
- H3 uses trade prices; bid/ask midpoints cannot show heaping.
- H4 needs a martingale-based simulator to validate the test (the current synthetic generator cannot).

## Deviations
(none yet)
