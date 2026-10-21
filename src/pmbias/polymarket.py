"""Polymarket public market-data loader (Gamma API for markets, CLOB API for price history).

VERIFY IN WEEK 1 against https://docs.polymarket.com : endpoint paths, query params,
field names, rate limits and terms of use. These were written from memory and are
UNTESTED against the live service. Known quirk to check: price history for resolved
markets can be sparse at fine granularity, so start with daily fidelity.
"""
from __future__ import annotations

import json
from typing import Iterator

import pandas as pd

from .http import get_json

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def iter_markets(max_markets: int | None = None, page: int = 500) -> Iterator[dict]:
    n, offset = 0, 0
    while True:
        data = get_json(GAMMA + "/markets", {"closed": "true", "limit": page, "offset": offset})
        if not data:
            return
        for m in data:
            yield m
            n += 1
            if max_markets and n >= max_markets:
                return
        offset += page


def _j(x):
    """Gamma returns some list fields as JSON-encoded strings."""
    if isinstance(x, str):
        return json.loads(x)
    return x or []


def normalize_market(m: dict) -> dict | None:
    outcomes = [str(o).lower() for o in _j(m.get("outcomes"))]
    prices = [float(p) for p in _j(m.get("outcomePrices"))]
    if outcomes != ["yes", "no"] or len(prices) != 2:
        return None
    if max(prices) < 0.99:  # unresolved, voided or 50/50 split: drop
        return None
    tokens = _j(m.get("clobTokenIds"))
    events = m.get("events") or []
    return dict(
        platform="polymarket",
        market_id=str(m["id"]),
        event_id=str(events[0]["id"]) if events else str(m.get("conditionId", m["id"])),
        series_id=None,
        question=m.get("question"),
        category=m.get("category"),
        open_time=m.get("startDate"),
        close_time=m.get("endDate"),  # scheduled end; may differ from actual resolution time. Document this.
        outcome=1 if prices[0] >= 0.99 else 0,
        volume=m.get("volumeNum", m.get("volume")),
        aux_id=tokens[0] if tokens else None,  # YES-outcome token id, needed for price history
    )


def fetch_history(token_id: str, fidelity: int = 1440) -> list[dict]:
    data = get_json(CLOB + "/prices-history", {"market": token_id, "interval": "max", "fidelity": fidelity})
    return data.get("history", [])


def normalize_history(market_id: str, history: list[dict]) -> list[dict]:
    return [dict(platform="polymarket", market_id=market_id,
                 ts=pd.to_datetime(h["t"], unit="s"), price=float(h["p"]),
                 last_price=float(h["p"]), bid=None, ask=None, volume=None) for h in history]
