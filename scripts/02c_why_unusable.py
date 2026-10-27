import argparse
from pmbias import db

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="data/pm.duckdb")
ap.add_argument("--horizon", type=int, default=7)
ap.add_argument("--max-stale", type=float, default=3.0)
a = ap.parse_args()
h, s = a.horizon, a.max_stale

con = db.connect(a.db)
df = con.execute(f"""
WITH s AS (
  SELECT m.platform, m.market_id, m.close_time,
         m.close_time - INTERVAL {h} DAY AS target,
         MIN(p.ts) AS first_ts, MAX(p.ts) AS last_ts,
         MAX(CASE WHEN p.ts <= m.close_time - INTERVAL {h} DAY THEN p.ts END) AS last_before
  FROM markets m LEFT JOIN prices p ON p.platform = m.platform AND p.market_id = m.market_id
  GROUP BY m.platform, m.market_id, m.close_time
)
SELECT platform,
  CASE WHEN first_ts IS NULL THEN '1. no price rows at all'
       WHEN last_before IS NULL THEN '2. price history starts after the {h}-day target'
       WHEN date_diff('hour', last_before, target) / 24.0 > {s} AND last_ts <= target
            THEN '3. trading history ends early (>{s} days before target)'
       WHEN date_diff('hour', last_before, target) / 24.0 > {s}
            THEN '4. gap in prices around the target (thin market)'
       ELSE '5. usable' END AS reason,
  COUNT(*) AS markets
FROM s GROUP BY 1, 2 ORDER BY 1, 2
""").df()
print(df.to_string(index=False))
print("\nCase 3 usually means the market resolved or stopped trading before its scheduled close date.")
