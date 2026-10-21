# Do Prediction Markets Think Like Humans?

Testing behavioral biases (favorite-longshot, round-number anchoring, over/underreaction) in Kalshi and
Polymarket prices, with honest uncertainty and cost-adjusted effect sizes.

**Status:** scaffold complete; analysis code validated on synthetic data; live API loaders UNTESTED.
Research only. No trading, no advice.

## Quickstart (no API needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 10 tests
python scripts/03_run_analysis.py --synthetic                        # planted bias: should be detected
python scripts/03_run_analysis.py --synthetic --synthetic-slope 1.0  # no bias: should find nothing
```
Outputs land in `outputs/` (`results.json`, `calibration.png`, tables).

## Real data

```bash
python scripts/01_collect.py kalshi markets --max-markets 3000            # live tier
python scripts/01_collect.py kalshi markets --historical --max-markets 3000   # historical tier
python scripts/01_collect.py kalshi prices  --max-markets 1000
python scripts/01_collect.py polymarket markets --max-markets 3000
python scripts/01_collect.py polymarket prices  --max-markets 1000
python scripts/02_build_db.py
python scripts/03_run_analysis.py --horizon 7
```

**Before trusting any real-data number:** verify endpoints, field names, price units, rate limits and
terms of use in the Kalshi and Polymarket docs (see docstrings in `src/pmbias/kalshi.py` and
`polymarket.py`). Kalshi separates live and historical data, so pull both tiers. Spot-check ~20 markets
by hand against the website. Check the fee formula in `analysis.kalshi_fee` against the current fee schedule.

## Layout

```
src/pmbias/   kalshi.py, polymarket.py (loaders) | db.py (DuckDB + SQL snapshots) |
              analysis.py (tests) | synthetic.py (planted-bias simulator) | plots.py
scripts/      01_collect -> 02_build_db -> 03_run_analysis
tests/        pipeline + statistics tests
HYPOTHESES.md pre-registered tests (lock before looking at results)
```

## Method in one paragraph
For each resolved binary market, take the last price at least `horizon` days before close (flagging stale
quotes). Compare prices to outcomes with calibration curves, Brier score and a logistic calibration slope
(H1), tail gaps (H2), heaping at round prices (H3), and post-jump calibration (H4). Uncertainty comes from
an event-clustered bootstrap, p-values are Holm-adjusted across the pre-registered family, and every
effect is re-expressed net of an assumed fee and half-spread.

## Limitations (keep this section honest and growing)
- Platform samples depend on API ordering and survivorship; document the rule used.
- Prices are bid/ask midpoints or last trades from daily candles, not an order-book reconstruction.
- H4 is not validated by the synthetic data (not a martingale); build a proper simulator first.
- Fee and spread parameters are assumptions.

## Roadmap (8 weeks)
- [ ] W1 verify APIs + terms, lock HYPOTHESES.md
- [ ] W2-3 collect, clean, spot-check, document sampling rule
- [ ] W4 H1/H2 on real data + blog post 1
- [ ] W5 H3
- [ ] W6 martingale simulator, then H4; robustness (time split, horizons, stale filters)
- [ ] W7 costs, limitations, draft report
- [ ] W8 polish, one-pager, blog posts 2-3
