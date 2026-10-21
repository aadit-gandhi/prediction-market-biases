"""Load cached raw files into DuckDB (data/pm.duckdb) using the standard schema."""
import json
from pathlib import Path

import pandas as pd

from pmbias import db

RAW = Path("data/raw")

con = db.connect("data/pm.duckdb")
db.init_db(con)

mk = [pd.read_json(f, lines=True, dtype=False) for f in sorted(RAW.glob("*_markets*.jsonl"))]
markets = pd.concat(mk, ignore_index=True)
db.load_markets(con, markets)

rows = []
for f in RAW.glob("*_prices/*.json"):
    rows.extend(json.loads(f.read_text()))
prices = pd.DataFrame(rows)
db.load_prices(con, prices)

print(con.execute("SELECT platform, COUNT(*) AS markets FROM markets GROUP BY 1").df())
print(con.execute("SELECT platform, COUNT(*) AS price_rows FROM prices GROUP BY 1").df())
