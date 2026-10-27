"""Kalshi public market-data loader.

VERIFY IN WEEK 1 against https://docs.kalshi.com : endpoint paths, field names,
price units (cents vs dollars), rate limits and terms of use. Kalshi splits data
into a live tier and a historical tier: markets that settled before the
`market_settled_ts` cutoff (see GET /historical/cutoff) are only available under
/historical/... endpoints, so collect from BOTH tiers.
"""
from __future__ import annotations

from typing import Iterator

import pandas as pd

from .http import get_json

BASE = "https://api.elections.kalshi.com/trade-api/v2"


def iter_markets(historical: bool = False, max_markets: int | None = None, **filters) -> Iterator[dict]:
    """Yield raw market dicts, following cursor pagination."""
    path = "/historical/markets" if historical else "/markets"
    params = {"limit": 1000, **filters}
    if not historical:
        params.setdefault("status", "settled")
    n, cursor = 0, None
    while True:
        if cursor:
            params["cursor"] = cursor
        data = get_json(BASE + path, params)
        for m in data.get("markets", []):
            yield m
            n += 1
            if max_markets and n >= max_markets:
                return
        cursor = data.get("cursor")
        if not cursor:
            return


def fetch_candles(ticker: str, series_ticker: str | None, start_ts: int, end_ts: int,
                  period_interval: int = 1440, historical: bool = False) -> list[dict]:
    """Candlesticks for one market. period_interval is in minutes (1440 = daily)."""
    if historical:
        path = f"/historical/markets/{ticker}/candlesticks"
    else:
        path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
    data = get_json(BASE + path, {"start_ts": int(start_ts), "end_ts": int(end_ts),
                                  "period_interval": period_interval})
    return data.get("candlesticks", [])


def normalize_market(m: dict) -> dict | None:
    """Raw Kalshi market -> standard schema row. Returns None if not a clean yes/no resolution."""
    result = (m.get("result") or "").lower()
    if result not in ("yes", "no"):
        return None
    event = m.get("event_ticker")
    return dict(
        platform="kalshi",
        market_id=m["ticker"],
        event_id=event or m["ticker"],
        series_id=event.split("-")[0] if event else None,
        question=m.get("title"),
        category=m.get("category"),
        open_time=m.get("open_time"),
        close_time=m.get("close_time") or m.get("expiration_time"),
        outcome=1 if result == "yes" else 0,
        volume=_num(m.get("volume") if m.get("volume") is not None else m.get("volume_fp")),
        aux_id=None,
    )


def _num(x):
    """Volume may arrive as an int, a numeric string (fixed-point fields), or be missing."""
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _cents(block: dict | None, key: str = "close") -> float | None:
    """Read a price from a candle sub-block; tolerate cents ('close') or dollars ('close_dollars')."""
    if not block:
        return None
    v = block.get(key)
    if v is not None:
        return float(v)
    d = block.get(f"{key}_dollars")
    return None if d is None else float(d) * 100.0


def normalize_candles(ticker: str, candles: list[dict], max_spread: float = 0.10) -> list[dict]:
    """Candles -> rows with price in dollars (0-1), choosing the most trustworthy price available.

    Priority: (1) bid/ask midpoint, but ONLY if the book is tight (spread <= max_spread);
              (2) last trade inside the period; (3) last trade before the period (carried forward);
              otherwise skip. A 1c bid / 99c ask midpoint (50c) is an empty book, not a price.
    `source` records which rule produced the price so robustness checks can restrict to the best ones.
    """
    rows = []
    for c in candles:
        last = _cents(c.get("price"))
        prev = _cents(c.get("price"), "previous")
        bid, ask = _cents(c.get("yes_bid")), _cents(c.get("yes_ask"))
        tight = (bid is not None and ask is not None and bid > 0 and ask > bid
                 and (ask - bid) <= max_spread * 100)
        if tight:
            px, src = (bid + ask) / 2, "mid"
        elif last is not None:
            px, src = last, "trade"
        elif prev is not None:
            px, src = prev, "prev_trade"
        else:
            continue
        vol = c.get("volume") if c.get("volume") is not None else c.get("volume_fp")
        rows.append(dict(
            platform="kalshi", market_id=ticker,
            ts=pd.to_datetime(c["end_period_ts"], unit="s"),
            price=px / 100.0,
            last_price=None if last is None else last / 100.0,
            bid=None if bid is None else bid / 100.0,
            ask=None if ask is None else ask / 100.0,
            volume=_num(vol), source=src,
        ))
    return rows
