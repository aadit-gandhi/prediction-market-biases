"""Statistical tests for behavioral biases in prediction-market prices.

Conventions: prices are probabilities in [0, 1]; outcome is 1 if YES resolved else 0.
All uncertainty is estimated with a CLUSTER bootstrap (resampling whole events), because
contracts within one event are strongly correlated and a naive bootstrap overstates confidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_EDGES = [0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 1.0]


# ---------- H1: calibration ----------
def logit(p, eps: float = 1e-3):
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    return np.log(p / (1 - p))


def brier_score(p, y) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def calibration_table(df: pd.DataFrame, price_col: str = "price", outcome_col: str = "outcome",
                      edges: list[float] | None = None) -> pd.DataFrame:
    """Binned price vs realized frequency. gap = freq - mean_price (negative => price too high)."""
    bins = pd.cut(df[price_col], edges or DEFAULT_EDGES, include_lowest=True).rename("bin")
    g = df.groupby(bins, observed=True).agg(
        n=(outcome_col, "size"), mean_price=(price_col, "mean"), freq=(outcome_col, "mean"))
    g["gap"] = g["freq"] - g["mean_price"]
    g["se"] = np.sqrt(g["freq"] * (1 - g["freq"]) / g["n"])
    g = g.reset_index()
    g["bin"] = g["bin"].astype(str)
    return g


def fit_logit(x: np.ndarray, y: np.ndarray, iters: int = 50) -> np.ndarray:
    """Logistic regression y ~ a + b*x by IRLS. Returns (a, b). Fast enough to bootstrap thousands of times."""
    X = np.column_stack([np.ones_like(x, dtype=float), x])
    beta = np.zeros(2)
    for _ in range(iters):
        mu = 1.0 / (1.0 + np.exp(-(X @ beta)))
        W = mu * (1 - mu) + 1e-9
        H = X.T @ (X * W[:, None]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, X.T @ (y - mu))
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def calibration_slope(df: pd.DataFrame) -> tuple[float, float]:
    """Regress outcome on logit(price). Perfect calibration: intercept 0, slope 1.

    slope > 1: realized probabilities more extreme than prices (longshots overpriced,
               favorites underpriced => favorite-longshot pattern)
    slope < 1: prices more extreme than realized probabilities (overconfidence).
    """
    a, b = fit_logit(logit(df["price"].to_numpy()), df["outcome"].to_numpy(dtype=float))
    return float(a), float(b)


# ---------- H2: favorite-longshot ----------
def mean_gap(df: pd.DataFrame, lo: float | None = None, hi: float | None = None) -> float:
    """Mean(outcome - price) for contracts with price <= lo (longshots) or >= hi (favorites)."""
    if lo is not None:
        d = df[df["price"] <= lo]
    elif hi is not None:
        d = df[df["price"] >= hi]
    else:
        d = df
    return float((d["outcome"] - d["price"]).mean()) if len(d) else np.nan


# ---------- H3: round-number anchoring (heaping) ----------
def heaping_ratio(prices_cents, targets=(25, 50, 75), width: int = 2) -> pd.DataFrame:
    """Count at each round price vs the mean count at neighboring cent values (ratio ~1 => no heaping)."""
    arr = pd.Series(np.round(np.asarray(prices_cents, dtype=float)).astype(int))
    counts = arr.value_counts()
    rows = []
    for t in targets:
        nb = [counts.get(t + k, 0) for k in range(-width, width + 1) if k != 0]
        base = float(np.mean(nb))
        rows.append(dict(target=t, count=int(counts.get(t, 0)), neighbor_mean=base,
                         ratio=float(counts.get(t, 0) / base) if base > 0 else np.nan))
    return pd.DataFrame(rows)


# ---------- H4: over/underreaction ----------
def jump_followthrough(paths: pd.DataFrame, jump: float = 0.10, lookahead: int = 1,
                       min_price: float = 0.03, max_price: float = 0.97,
                       min_days_left: float = 2.0) -> pd.DataFrame:
    """After a one-step price jump >= `jump`, signed follow-through over the next `lookahead` steps.

    cont = sign(jump) * subsequent change.  cont > 0: continuation (underreaction);
    cont < 0: reversal (overreaction). Steps are observations, not calendar days, so state that in the write-up.
    Excludes the final days before close, where prices converge to 0/1 mechanically.
    """
    g = paths.sort_values(["platform", "market_id", "ts"]).copy()
    grp = g.groupby(["platform", "market_id"])["price"]
    g["d"] = g["price"] - grp.shift(1)
    g["fwd"] = grp.shift(-lookahead) - g["price"]
    keep = (g["d"].abs() >= jump) & g["fwd"].notna() & g["price"].between(min_price, max_price)
    if "days_to_close" in g:
        keep &= g["days_to_close"] >= lookahead + min_days_left
    ev = g[keep].copy()
    ev["cont"] = np.sign(ev["d"]) * ev["fwd"]
    if "outcome" in ev:
        # Cleaner overreaction test: right after a jump, is the price still calibrated?
        # post_jump_gap < 0 => the post-jump price was too extreme in the jump's direction (overreaction);
        # > 0 => the price had not moved enough (underreaction). Unlike `cont`, this is not
        # confounded by genuine news continuing to arrive.
        ev["post_jump_gap"] = np.sign(ev["d"]) * (ev["outcome"] - ev["price"])
    return ev


# ---------- uncertainty ----------
def cluster_bootstrap(df: pd.DataFrame, fn, cluster_col: str = "event_id",
                      n_boot: int = 1000, seed: int = 0) -> np.ndarray:
    """Resample whole clusters (events) with replacement; return fn(resampled_df) for each draw."""
    df = df.reset_index(drop=True)
    groups = df.groupby(cluster_col).indices
    keys = np.array(list(groups.keys()), dtype=object)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(keys), len(keys))
        idx = np.concatenate([groups[keys[j]] for j in pick])
        out[i] = fn(df.iloc[idx])
    return out


def summarize(est: float, boots: np.ndarray, null: float = 0.0, alpha: float = 0.05) -> dict:
    b = boots[~np.isnan(boots)]
    lo, hi = np.percentile(b, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    p = 2 * min((b <= null).mean(), (b >= null).mean())
    p = float(min(max(p, 1 / (len(b) + 1)), 1.0))
    return dict(est=float(est), ci_low=float(lo), ci_high=float(hi), p_boot=p, n_boot=int(len(b)))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values (controls family-wise error across your pre-registered tests)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, adj, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return adj


# ---------- costs ----------
def kalshi_fee(price, coef: float = 0.07):
    """Approximate per-contract taker fee in dollars: coef * p * (1-p).
    ASSUMPTION: check Kalshi's current fee schedule and update `coef` before reporting any net numbers."""
    p = np.asarray(price, dtype=float)
    return coef * p * (1 - p)


def edge_after_costs(df: pd.DataFrame, lo: float = 0.10, hi: float = 0.90,
                     fee_coef: float = 0.07, half_spread: float = 0.01) -> dict:
    """Per-contract edge of a hypothetical bias-following rule, gross and after fee + half-spread.

    longshots (price <= lo): buy NO  => profit = price - outcome
    favorites (price >= hi): buy YES => profit = outcome - price
    Research analysis only: no trading is implied.
    """
    low, high = df[df["price"] <= lo], df[df["price"] >= hi]
    out = {}
    for name, d, gross in (("longshot_buy_no", low, low["price"] - low["outcome"]),
                           ("favorite_buy_yes", high, high["outcome"] - high["price"])):
        cost = kalshi_fee(d["price"]) + half_spread
        out[name] = dict(n=int(len(d)), gross=float(gross.mean()) if len(d) else np.nan,
                         net=float((gross - cost).mean()) if len(d) else np.nan)
    return out
