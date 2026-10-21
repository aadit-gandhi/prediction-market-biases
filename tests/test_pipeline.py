import numpy as np
import pandas as pd
import pytest

from pmbias import analysis as A
from pmbias import db
from pmbias.synthetic import make_synthetic


@pytest.fixture(scope="module")
def snaps_biased():
    m, p = make_synthetic(n_events=2000, slope=1.4, seed=1)
    con = db.connect(":memory:")
    db.init_db(con); db.load_markets(con, m); db.load_prices(con, p)
    return db.make_snapshots(con, 7, 3.0), con


def test_recovers_planted_slope(snaps_biased):
    s, _ = snaps_biased
    _, slope = A.calibration_slope(s)
    assert 1.25 < slope < 1.55


def test_null_world_slope_near_one():
    m, p = make_synthetic(n_events=2000, slope=1.0, seed=2)
    con = db.connect(":memory:")
    db.init_db(con); db.load_markets(con, m); db.load_prices(con, p)
    s = db.make_snapshots(con, 7, 3.0)
    _, slope = A.calibration_slope(s)
    assert 0.9 < slope < 1.1


def test_longshot_gap_negative_when_biased(snaps_biased):
    s, _ = snaps_biased
    assert A.mean_gap(s, lo=0.10) < 0      # longshots overpriced
    assert A.mean_gap(s, hi=0.90) > 0      # favorites underpriced


def test_snapshot_uses_only_pre_horizon_prices(snaps_biased):
    s, _ = snaps_biased
    assert (s["price_ts"] <= s["target_ts"]).all()   # no lookahead
    assert (s["stale_days"] <= 3.0).all()


def test_cluster_bootstrap_ci_contains_estimate(snaps_biased):
    s, _ = snaps_biased
    est = A.calibration_slope(s)[1]
    boots = A.cluster_bootstrap(s, lambda d: A.calibration_slope(d)[1], n_boot=100, seed=3)
    r = A.summarize(est, boots, null=1.0)
    assert r["ci_low"] < est < r["ci_high"]
    assert r["ci_low"] > 1.0                          # planted bias detected


def test_heaping_ratio_detects_planted_heap():
    rng = np.random.default_rng(0)
    prices = np.concatenate([rng.integers(40, 61, 5000), np.full(400, 50)])
    r = A.heaping_ratio(prices, targets=(50,)).iloc[0]["ratio"]
    assert r > 1.5


def test_holm_monotone_and_bounded():
    adj = A.holm({"a": 0.01, "b": 0.04, "c": 0.5})
    assert adj["a"] == pytest.approx(0.03) and adj["b"] == pytest.approx(0.08)
    assert all(0 <= v <= 1 for v in adj.values())


def test_jump_followthrough_sign():
    ts = pd.date_range("2025-01-01", periods=6)
    paths = pd.DataFrame(dict(platform="x", market_id="m", event_id="e", ts=ts,
                              price=[.30, .30, .45, .50, .50, .50], last_price=.3,
                              days_to_close=[30, 29, 28, 27, 26, 25]))
    ev = A.jump_followthrough(paths, jump=0.10, lookahead=1)
    assert len(ev) == 1 and ev["cont"].iloc[0] == pytest.approx(0.05)  # continuation after up-jump


def test_edge_after_costs_shrinks_edge():
    df = pd.DataFrame(dict(price=[.05] * 100, outcome=[0] * 98 + [1] * 2))
    e = A.edge_after_costs(df)["longshot_buy_no"]
    assert e["net"] < e["gross"]


def test_post_jump_gap_sign():
    ts = pd.date_range("2025-01-01", periods=6)
    base = dict(platform="x", market_id="m", event_id="e", ts=ts, last_price=.3,
                price=[.30, .30, .50, .50, .50, .50], days_to_close=[30, 29, 28, 27, 26, 25])
    up_but_no = pd.DataFrame({**base, "outcome": 0})   # price jumped up, event did not happen
    ev = A.jump_followthrough(up_but_no, jump=0.10, lookahead=1)
    assert ev["post_jump_gap"].iloc[0] < 0              # overreaction
