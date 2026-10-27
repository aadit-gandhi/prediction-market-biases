"""DuckDB layer: standard schema, loaders, and the SQL that builds analysis snapshots."""
from __future__ import annotations

import duckdb
import pandas as pd

MARKET_COLS = ["platform", "market_id", "event_id", "series_id", "question", "category",
               "open_time", "close_time", "outcome", "volume", "aux_id"]
PRICE_COLS = ["platform", "market_id", "ts", "price", "last_price", "bid", "ask", "volume", "source"]

SCHEMA = """
CREATE OR REPLACE TABLE markets (
    platform VARCHAR, market_id VARCHAR, event_id VARCHAR, series_id VARCHAR,
    question VARCHAR, category VARCHAR, open_time TIMESTAMP, close_time TIMESTAMP,
    outcome INTEGER, volume DOUBLE, aux_id VARCHAR);
CREATE OR REPLACE TABLE prices (
    platform VARCHAR, market_id VARCHAR, ts TIMESTAMP, price DOUBLE,
    last_price DOUBLE, bid DOUBLE, ask DOUBLE, volume DOUBLE, source VARCHAR);
"""


def connect(path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path)


def init_db(con) -> None:
    con.execute(SCHEMA)


def _prep(df: pd.DataFrame, cols: list[str], time_cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c not in df:
            df[c] = None
    for c in time_cols:  # store naive UTC timestamps
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce").dt.tz_localize(None)
    return df[cols]


def load_markets(con, df: pd.DataFrame) -> None:
    df = _prep(df, MARKET_COLS, ["open_time", "close_time"]).drop_duplicates(["platform", "market_id"])
    con.register("_m", df)
    con.execute("INSERT INTO markets SELECT * FROM _m")
    con.unregister("_m")


def load_prices(con, df: pd.DataFrame) -> None:
    df = _prep(df, PRICE_COLS, ["ts"]).drop_duplicates(["platform", "market_id", "ts"])
    con.register("_p", df)
    con.execute("INSERT INTO prices SELECT * FROM _p")
    con.unregister("_p")


def make_snapshots(con, horizon_days: int = 7, max_stale_days: float = 3.0) -> pd.DataFrame:
    """One row per market: the last known price at least `horizon_days` before close.

    `stale_days` records how old that price was relative to the target time, so stale
    quotes in thin markets can be filtered or studied rather than silently trusted.
    """
    h, s = int(horizon_days), float(max_stale_days)
    con.execute(f"""
    CREATE OR REPLACE TABLE snapshots AS
    WITH cand AS (
        SELECT m.platform, m.market_id, m.event_id, m.series_id, m.category, m.outcome, m.volume,
               p.price, p.ts AS price_ts, m.close_time - INTERVAL {h} DAY AS target_ts,
               ROW_NUMBER() OVER (PARTITION BY m.platform, m.market_id ORDER BY p.ts DESC) AS rn
        FROM markets m
        JOIN prices p ON p.platform = m.platform AND p.market_id = m.market_id
        WHERE p.ts <= m.close_time - INTERVAL {h} DAY
    )
    SELECT platform, market_id, event_id, series_id, category, outcome, volume, price, price_ts, target_ts,
           date_diff('hour', price_ts, target_ts) / 24.0 AS stale_days,
           {h} AS horizon_days
    FROM cand
    WHERE rn = 1 AND date_diff('hour', price_ts, target_ts) / 24.0 <= {s}
    """)
    return con.execute("SELECT * FROM snapshots").df()


def load_paths(con) -> pd.DataFrame:
    """Full price paths joined to market metadata, with days remaining until close."""
    return con.execute("""
        SELECT p.platform, p.market_id, m.event_id, m.outcome, p.ts, p.price, p.last_price,
               date_diff('hour', p.ts, m.close_time) / 24.0 AS days_to_close
        FROM prices p JOIN markets m ON m.platform = p.platform AND m.market_id = p.market_id
        ORDER BY p.platform, p.market_id, p.ts
    """).df()
