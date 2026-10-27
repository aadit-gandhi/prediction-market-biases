"""List Kalshi series so you can pick long-dated, non-daily ones for --series.

    python scripts/00_list_series.py --exclude-frequency daily weekly
    python scripts/00_list_series.py --category Economics

VERIFY: the /series endpoint and its field names (ticker, title, category, frequency) were written from
memory of the docs and are untested. If this errors, browse kalshi.com instead: the series ticker is
visible in each market's URL and ticker.
"""
import argparse

from pmbias.http import get_json
from pmbias.kalshi import BASE

ap = argparse.ArgumentParser()
ap.add_argument("--category")
ap.add_argument("--exclude-frequency", nargs="*", default=[])
ap.add_argument("--max-print", type=int, default=200)
a = ap.parse_args()

data = get_json(BASE + "/series", {"category": a.category} if a.category else None)
rows = data.get("series") or []
skip = {f.lower() for f in a.exclude_frequency}
shown = 0
for s in rows:
    t = str(s.get("ticker", ""))
    if t.upper().startswith("KXMVE") or str(s.get("frequency", "")).lower() in skip:
        continue
    print(f"{t} | {s.get('frequency')} | {s.get('category')} | {s.get('title')}")
    shown += 1
    if shown >= a.max_print:
        break
print(f"\n{shown} series shown (of {len(rows)} returned)")
