"""Synthetic prediction-market data with a KNOWN planted bias.

Use it to (a) run the entire pipeline before you have real data and (b) validate that the
estimators recover the planted bias. If a method can't find a bias you put there, it can't be
trusted to find one you didn't.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def make_synthetic(n_events: int = 2500, markets_per_event: int = 3, slope: float = 1.3,
                   horizon_days: int = 7, n_days: int = 30, seed: int = 0):
    """Return (markets_df, prices_df). True log-odds = slope * logit(price), so slope > 1 plants a
    favorite-longshot pattern and slope == 1 is perfectly calibrated."""
    rng = np.random.default_rng(seed)
    base = pd.Timestamp("2025-01-01")
    m_rows, p_rows = [], []
    for e in range(n_events):
        close = base + pd.Timedelta(days=int(rng.integers(40, 400)))
        for k in range(markets_per_event):
            mid = f"SYN-{e}-{k}"
            p_h = float(np.clip(rng.beta(0.8, 1.0), 0.02, 0.98))      # price at horizon
            p_h = round(p_h * 100) / 100
            lp = np.log(p_h / (1 - p_h))
            q = _sigmoid(slope * lp)                                      # true probability
            y = int(rng.random() < q)
            m_rows.append(dict(platform="synthetic", market_id=mid, event_id=f"EV-{e}", series_id="SYN",
                               question=mid, category=["politics", "sports", "economics"][e % 3],
                               open_time=close - pd.Timedelta(days=n_days), close_time=close,
                               outcome=y, volume=float(rng.integers(10, 5000)), aux_id=None))
            noise = np.cumsum(rng.normal(0, 0.25, n_days))[::-1]
            for d in range(n_days, -1, -1):                               # d = days before close
                if d >= horizon_days:
                    lpd = lp + noise[n_days - d] * (1 if d > horizon_days else 0)
                else:
                    target = 4.0 if y else -4.0
                    lpd = lp + (horizon_days - d) / horizon_days * 0.9 * (target - lp)
                px = float(np.clip(round(_sigmoid(lpd) * 100) / 100, 0.01, 0.99))
                p_rows.append(dict(platform="synthetic", market_id=mid,
                                   ts=close - pd.Timedelta(days=d) - pd.Timedelta(hours=1),
                                   price=px, last_price=px, bid=None, ask=None, volume=None))
    return pd.DataFrame(m_rows), pd.DataFrame(p_rows)
