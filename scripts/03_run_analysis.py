"""Run the pre-registered tests (see HYPOTHESES.md) and write tables, figures and results.json.

    python scripts/03_run_analysis.py --synthetic             # validate pipeline on planted-bias data
    python scripts/03_run_analysis.py --synthetic --synthetic-slope 1.0   # null world: should find nothing
    python scripts/03_run_analysis.py                         # real data from data/pm.duckdb
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pmbias import analysis as A
from pmbias import db
from pmbias.plots import calibration_plot
from pmbias.synthetic import make_synthetic

ap = argparse.ArgumentParser()
ap.add_argument("--synthetic", action="store_true")
ap.add_argument("--synthetic-slope", type=float, default=1.3)
ap.add_argument("--db", default="data/pm.duckdb")
ap.add_argument("--platform", default=None)
ap.add_argument("--horizon", type=int, default=7, help="days before close at which price is measured")
ap.add_argument("--max-stale", type=float, default=3.0)
ap.add_argument("--n-boot", type=int, default=1000)
ap.add_argument("--out", default="outputs")
args = ap.parse_args()
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)

if args.synthetic:
    markets, prices = make_synthetic(slope=args.synthetic_slope, horizon_days=args.horizon)
    con = db.connect(":memory:")
    db.init_db(con)
    db.load_markets(con, markets)
    db.load_prices(con, prices)
else:
    con = db.connect(args.db)

snaps = db.make_snapshots(con, args.horizon, args.max_stale)
snaps = snaps[snaps["price"].between(0.01, 0.99)]
paths = db.load_paths(con)
if args.platform:
    snaps = snaps[snaps["platform"] == args.platform]
    paths = paths[paths["platform"] == args.platform]
print(f"Snapshot sample: {len(snaps)} markets, {snaps['event_id'].nunique()} events")

res, pvals = {}, {}
nb = args.n_boot

# H1 calibration -------------------------------------------------------
tbl = A.calibration_table(snaps)
tbl.to_csv(out / "calibration_table.csv", index=False)
calibration_plot(tbl, str(out / "calibration.png"))
res["brier"] = A.brier_score(snaps["price"], snaps["outcome"])
a, b = A.calibration_slope(snaps)
boots = A.cluster_bootstrap(snaps, lambda d: A.calibration_slope(d)[1], n_boot=nb)
res["H1_calibration_slope"] = A.summarize(b, boots, null=1.0) | {"intercept": a}
pvals["H1_calibration_slope"] = res["H1_calibration_slope"]["p_boot"]

# H2 favorite-longshot -------------------------------------------------
for name, kw in (("H2_longshot_gap", dict(lo=0.10)), ("H2_favorite_gap", dict(hi=0.90))):
    est = A.mean_gap(snaps, **kw)
    boots = A.cluster_bootstrap(snaps, lambda d, kw=kw: A.mean_gap(d, **kw), n_boot=nb)
    res[name] = A.summarize(est, boots, null=0.0)
    pvals[name] = res[name]["p_boot"]

# H3 round-number heaping ----------------------------------------------
px = paths.dropna(subset=["last_price"])
heap = A.heaping_ratio(px["last_price"] * 100)
heap.to_csv(out / "heaping.csv", index=False)
est = float(heap.loc[heap["target"] == 50, "ratio"].iloc[0])
sub = px[["event_id", "last_price"]].reset_index(drop=True)
boots = A.cluster_bootstrap(
    sub, lambda d: A.heaping_ratio(d["last_price"] * 100, targets=(50,))["ratio"].iloc[0],
    n_boot=min(nb, 300))
res["H3_heaping_50c"] = A.summarize(est, boots, null=1.0)
pvals["H3_heaping_50c"] = res["H3_heaping_50c"]["p_boot"]

# H4 over/underreaction ------------------------------------------------
ev = A.jump_followthrough(paths)
res["H4_n_jumps"] = int(len(ev))
if len(ev) >= 30:
    boots = A.cluster_bootstrap(ev, lambda d: d["cont"].mean(), n_boot=nb)
    res["H4_continuation_DESCRIPTIVE_ONLY"] = A.summarize(ev["cont"].mean(), boots, null=0.0)
    if "post_jump_gap" in ev:  # the pre-registered H4 test
        boots = A.cluster_bootstrap(ev, lambda d: d["post_jump_gap"].mean(), n_boot=nb)
        res["H4_post_jump_gap"] = A.summarize(ev["post_jump_gap"].mean(), boots, null=0.0)
        pvals["H4_post_jump_gap"] = res["H4_post_jump_gap"]["p_boot"]

if args.synthetic:
    res["H4_note"] = ("NOT VALIDATED: the synthetic generator's late-horizon prices drift toward the outcome "
                      "(not a martingale), so H4 results on synthetic data are an artifact. Build a "
                      "martingale-based simulator (Week 6) before trusting H4 on real data.")
    pvals.pop("H4_post_jump_gap", None)

# Multiple-testing correction across the pre-registered family --------
res["holm_adjusted_p"] = A.holm(pvals)

# Costs ---------------------------------------------------------------
res["edge_after_costs"] = A.edge_after_costs(snaps)

(out / "results.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
