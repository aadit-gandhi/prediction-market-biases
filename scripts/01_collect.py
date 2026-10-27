"""Collect raw data from a platform into data/raw/ (cached and resumable).

Examples:
    python scripts/01_collect.py kalshi markets --max-markets 50
    python scripts/01_collect.py kalshi markets --max-markets 500 --close-after 2026-01-01 --close-before 2026-03-01
    python scripts/01_collect.py kalshi prices --max-markets 20
    python scripts/01_collect.py polymarket markets --max-markets 50
    python scripts/01_collect.py polymarket prices --max-markets 20

ELIGIBILITY RULES (document these in your write-up; they are decided by market structure, never by outcomes):
  * resolved yes/no only
  * excluded ticker prefixes (default KXMVE = Kalshi multivariate/combo markets)
  * lifetime >= --min-duration-days (default 10), because the analysis needs a price
    `horizon` days (default 7) before close, and a market must exist that long
"""
import argparse
import json
import math
from pathlib import Path

import pandas as pd

from pmbias import kalshi, polymarket

RAW = Path("data/raw")


def _epoch(d):
    return int(pd.Timestamp(d, tz="UTC").timestamp()) if d else None


def _iter_kalshi(a, filters):
    """Iterate markets, once per requested series (or once with no series filter)."""
    for series in (a.series or [None]):
        f = dict(filters)
        if series:
            f["series_ticker"] = series
        yield from kalshi.iter_markets(historical=a.historical, max_markets=a.max_scan, **f)


def _windows(after, before, days):
    """Split [after, before) into consecutive windows of `days` days (ISO timestamps)."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    start, end, out = pd.Timestamp(after, tz="UTC"), pd.Timestamp(before, tz="UTC"), []
    while start < end:
        nxt = min(start + pd.Timedelta(days=days), end)
        out.append((start.strftime(fmt), nxt.strftime(fmt)))
        start = nxt
    return out


def _iter_polymarket(a, filters):
    """Query one date window at a time so each stays under the API's pagination limit."""
    if a.close_after and a.close_before:
        for i, (lo, hi) in enumerate(_windows(a.close_after, a.close_before, a.window_days)):
            f = dict(filters, end_date_min=lo, end_date_max=hi)
            for m in polymarket.iter_markets(max_markets=a.max_scan, **f):
                m["_window"] = i
                yield m
    else:
        yield from polymarket.iter_markets(max_markets=a.max_scan, **filters)


def collect_markets(a) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    tier = "_hist" if a.historical else ""
    out = RAW / f"{a.platform}_markets{tier}.jsonl"
    if a.platform == "kalshi":
        filters = {}
        if a.close_after:
            filters["min_close_ts"] = _epoch(a.close_after)
        if a.close_before:
            filters["max_close_ts"] = _epoch(a.close_before)
        for kv in (a.param or []):  # pass-through API filters, e.g. --param mve_filter=exclude
            k, _, v = kv.partition("=")
            filters[k] = v
        it = _iter_kalshi(a, filters)
        norm = kalshi.normalize_market
    else:
        filters = {}
        if a.close_after:   # Gamma wants ISO timestamps
            filters["end_date_min"] = a.close_after + "T00:00:00Z"
        if a.close_before:
            filters["end_date_max"] = a.close_before + "T00:00:00Z"
        for kv in (a.param or []):  # e.g. --param volume_num_min=5000
            k, _, v = kv.partition("=")
            filters[k] = v
        it = _iter_polymarket(a, filters)
        norm = polymarket.normalize_market

    drops = dict(not_binary_or_unresolved=0, excluded_prefix=0, bad_dates=0, too_short=0, low_volume=0,
                 event_cap=0, window_cap=0)
    per_event, per_window = {}, {}
    n_win = (len(_windows(a.close_after, a.close_before, a.window_days))
             if a.platform == "polymarket" and a.close_after and a.close_before else 1)
    win_cap = a.per_window or (math.ceil(a.max_markets / n_win) if n_win > 1 else 0)  # spread sample over time
    kept = seen = 0
    sample = []
    with out.open("w") as f:
        for m in it:
            seen += 1
            if len(sample) < 3:
                sample.append(m)
            row = norm(m)
            if row is None:
                drops["not_binary_or_unresolved"] += 1
                continue
            if any(str(row["market_id"]).upper().startswith(p.upper()) for p in a.exclude_prefix):
                drops["excluded_prefix"] += 1
                continue
            dur = (pd.Timestamp(row["close_time"]) - pd.Timestamp(row["open_time"])).total_seconds() / 86400
            if pd.isna(dur):
                drops["bad_dates"] += 1
                continue
            if dur < a.min_duration_days:
                drops["too_short"] += 1
                continue
            if a.min_volume and (row.get("volume") or 0) < a.min_volume:
                drops["low_volume"] += 1
                continue
            w = m.get("_window")
            if win_cap and w is not None and per_window.get(w, 0) >= win_cap:
                drops["window_cap"] += 1
                continue
            if a.max_per_event and per_event.get(row["event_id"], 0) >= a.max_per_event:
                drops["event_cap"] += 1
                continue
            per_event[row["event_id"]] = per_event.get(row["event_id"], 0) + 1
            if w is not None:
                per_window[w] = per_window.get(w, 0) + 1
            f.write(json.dumps(row, default=str) + "\n")
            kept += 1
            if kept >= a.max_markets:
                break
    (RAW / f"{a.platform}_sample_raw.json").write_text(json.dumps(sample, indent=2, default=str))
    print(f"{a.platform}: scanned {seen}, kept {kept} -> {out}")
    print(f"  distinct events kept: {len(per_event)}")
    print(f"  dropped: {drops}")
    print(f"  raw examples saved to data/raw/{a.platform}_sample_raw.json (open it to see the real field names)")


def collect_prices(a) -> None:
    files = sorted(RAW.glob(f"{a.platform}_markets*.jsonl"))
    if not files:
        raise SystemExit("Run the 'markets' step first.")
    markets = pd.concat([pd.read_json(f, lines=True, dtype=False) for f in files]).head(a.max_markets)
    cache = RAW / f"{a.platform}_prices"
    cache.mkdir(exist_ok=True)
    empty = failed = done = 0
    for m in markets.itertuples(index=False):
        path = cache / f"{m.market_id}.json"
        if path.exists():  # resumable
            continue
        try:
            if a.platform == "kalshi":
                start = int(pd.Timestamp(m.open_time).timestamp())
                end = int(pd.Timestamp(m.close_time).timestamp())
                candles = kalshi.fetch_candles(m.market_id, m.series_id, start, end, 1440)
                if not candles:  # older markets live in the historical tier
                    candles = kalshi.fetch_candles(m.market_id, m.series_id, start, end, 1440, historical=True)
                rows = kalshi.normalize_candles(m.market_id, candles)
            else:
                if not m.aux_id:
                    continue
                rows = polymarket.normalize_history(m.market_id, polymarket.fetch_history(m.aux_id))
        except Exception as e:  # keep going; log failures for your data-quality notes
            failed += 1
            print(f"  skip {m.market_id}: {e}")
            continue
        path.write_text(json.dumps(rows, default=str))
        done += 1
        empty += (len(rows) == 0)
    print(f"{a.platform}: fetched {done} price histories ({empty} empty, {failed} failed)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", choices=["kalshi", "polymarket"])
    ap.add_argument("step", choices=["markets", "prices"])
    ap.add_argument("--max-markets", type=int, default=50, help="number of KEPT markets to collect")
    ap.add_argument("--max-scan", type=int, default=20000, help="most markets to scan while looking for eligible ones")
    ap.add_argument("--historical", action="store_true", help="Kalshi only: pull the historical tier")
    ap.add_argument("--max-per-event", type=int, default=0,
                    help="cap markets per event (0 = no cap); prevents one event from filling the sample")
    ap.add_argument("--window-days", type=int, default=30, help="Polymarket: size of each date window")
    ap.add_argument("--per-window", type=int, default=0,
                    help="Polymarket: cap kept markets per window (0 = auto, spreads --max-markets evenly)")
    ap.add_argument("--min-volume", type=float, default=0)
    ap.add_argument("--min-duration-days", type=float, default=10)
    ap.add_argument("--exclude-prefix", nargs="*", default=["KXMVE"])
    ap.add_argument("--series", nargs="*", help="Kalshi: only these series tickers (e.g. KXBALANCESHEET)")
    ap.add_argument("--param", action="append", help="extra API filter key=value (repeatable); "
                    "an unsupported one will make the API return an error, which is harmless")
    ap.add_argument("--close-after", help="only markets closing after this date, e.g. 2026-01-01 (both platforms)")
    ap.add_argument("--close-before", help="only markets closing before this date (both platforms)")
    a = ap.parse_args()
    collect_markets(a) if a.step == "markets" else collect_prices(a)
