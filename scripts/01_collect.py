"""Collect raw data from a platform into data/raw/ (cached and resumable).

Examples:
    python scripts/01_collect.py kalshi markets --max-markets 3000
    python scripts/01_collect.py kalshi markets --historical --max-markets 3000
    python scripts/01_collect.py kalshi prices --max-markets 1000
    python scripts/01_collect.py polymarket markets --max-markets 3000
    python scripts/01_collect.py polymarket prices --max-markets 1000

SAMPLING WARNING: API order is not random. Record exactly how you select markets in your
README, and prefer a documented rule (e.g. all settled markets above a volume floor) to
"whatever came first".
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from pmbias import kalshi, polymarket

RAW = Path("data/raw")


def collect_markets(platform: str, max_markets: int, historical: bool, min_volume: float) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    tier = "_hist" if historical else ""
    out = RAW / f"{platform}_markets{tier}.jsonl"
    it = (kalshi.iter_markets(historical=historical, max_markets=max_markets)
          if platform == "kalshi" else polymarket.iter_markets(max_markets=max_markets))
    norm = kalshi.normalize_market if platform == "kalshi" else polymarket.normalize_market
    kept = seen = 0
    with out.open("w") as f:
        for m in it:
            seen += 1
            row = norm(m)
            if row is None or (row.get("volume") or 0) < min_volume:
                continue
            f.write(json.dumps(row, default=str) + "\n")
            kept += 1
    print(f"{platform}: saw {seen} markets, kept {kept} clean binary resolved markets -> {out}")


def collect_prices(platform: str, max_markets: int) -> None:
    files = sorted(RAW.glob(f"{platform}_markets*.jsonl"))
    if not files:
        raise SystemExit("Run the 'markets' step first.")
    markets = pd.concat([pd.read_json(f, lines=True, dtype=False) for f in files]).head(max_markets)
    cache = RAW / f"{platform}_prices"
    cache.mkdir(exist_ok=True)
    for i, m in enumerate(markets.itertuples(index=False), 1):
        path = cache / f"{m.market_id}.json"
        if path.exists():  # resumable
            continue
        try:
            if platform == "kalshi":
                start = int(pd.Timestamp(m.open_time).timestamp())
                end = int(pd.Timestamp(m.close_time).timestamp())
                candles = kalshi.fetch_candles(m.market_id, m.series_id, start, end, 1440)
                rows = kalshi.normalize_candles(m.market_id, candles)
            else:
                if not m.aux_id:
                    continue
                rows = polymarket.normalize_history(m.market_id, polymarket.fetch_history(m.aux_id))
        except Exception as e:  # keep going; log failures for your data-quality notes
            print(f"  skip {m.market_id}: {e}")
            continue
        path.write_text(json.dumps(rows, default=str))
        if i % 50 == 0:
            print(f"  {i}/{len(markets)} markets")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", choices=["kalshi", "polymarket"])
    ap.add_argument("step", choices=["markets", "prices"])
    ap.add_argument("--max-markets", type=int, default=1000)
    ap.add_argument("--historical", action="store_true", help="Kalshi only: pull the historical tier")
    ap.add_argument("--min-volume", type=float, default=0)
    a = ap.parse_args()
    if a.step == "markets":
        collect_markets(a.platform, a.max_markets, a.historical, a.min_volume)
    else:
        collect_prices(a.platform, a.max_markets)
