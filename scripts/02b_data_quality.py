"""Data-quality report. Prints COUNTS ONLY (no outcomes, no bias results), so running it does not
compromise the pre-registration. Use it to decide whether the sample is usable.

    python scripts/02b_data_quality.py --horizon 7 --max-stale 3
"""
import argparse

import pandas as pd

from pmbias import db

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="data/pm.duckdb")
ap.add_argument("--horizon", type=int, default=7)
ap.add_argument("--max-stale", type=float, default=3.0)
a = ap.parse_args()

con = db.connect(a.db)
q = lambda sql: con.execute(sql).df()

print("\n== Markets and events collected ==")
print(q("SELECT platform, COUNT(*) AS markets, COUNT(DISTINCT event_id) AS events FROM markets GROUP BY 1"))
print("\n== Markets per event (a few events dominating = trouble) ==")
print(q("""SELECT platform, MIN(n) AS min, MEDIAN(n) AS median, MAX(n) AS max FROM
          (SELECT platform, event_id, COUNT(*) AS n FROM markets GROUP BY 1,2) GROUP BY 1"""))
print("\n== Price rows by source ==")
print(q("SELECT platform, source, COUNT(*) AS rows FROM prices GROUP BY 1,2 ORDER BY 1,3 DESC"))

snaps = db.make_snapshots(con, a.horizon, a.max_stale)
print(f"\n== Usable sample (price >= {a.horizon} days before close, at most {a.max_stale} days stale) ==")
tot = q("SELECT platform, COUNT(*) AS markets_total FROM markets GROUP BY 1")
use = snaps.groupby("platform").agg(usable_markets=("market_id", "size"), usable_events=("event_id", "nunique")).reset_index()
rep = tot.merge(use, on="platform", how="left").fillna(0)
rep["share_usable"] = (rep["usable_markets"] / rep["markets_total"]).round(2)
print(rep)
if len(snaps):
    print("\nStaleness of chosen prices (days):")
    print(snaps["stale_days"].describe().round(2))
print("\nRule of thumb: you want hundreds of usable EVENTS, not just markets, before trusting any test.")
