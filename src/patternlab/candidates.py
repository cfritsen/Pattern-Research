"""Candidate indicators for the redundancy sandbox (scripts/indicator_sandbox.py).

These are NOT part of the feature set the search uses. They exist only so a new
indicator can be checked for overlap with the current features before anyone
decides to add it. Every value at bar t uses only bars up to and including t
(tests/test_candidates.py checks this for each one).

To try another indicator: write a function taking the OHLCV frame and returning a
Series, and add it to PER_TICKER.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from patternlab.indicators import (PER_TICKER as _PRODUCTION, WINDOW_1Y, adx_14, bars_since_extreme, cmf_20,
                                   days_since_52w_low, market_features, mom_12_1, vol_ratio_5_20, vol_state_1y)


def days_since_52w_high(df):
    return bars_since_extreme(df["adj_close"], np.argmax)


def stoch_k_14(df):
    """Stochastic %K: where the close sits inside the last 14 bars' high-low range (0-100)."""
    ll, hh = df["adj_low"].rolling(14).min(), df["adj_high"].rolling(14).max()
    return 100 * (df["adj_close"] - ll) / (hh - ll).where(hh > ll)


def boll_pctb_20(df):
    """Bollinger %B: position within the 20-bar, 2-standard-deviation band (0 = lower, 1 = upper)."""
    c = df["adj_close"]
    sd = c.rolling(20).std().where(lambda s: s > 0)
    return 0.5 + (c - c.rolling(20).mean()) / (4 * sd)


def boll_bandwidth_20(df):
    """Bollinger bandwidth: band width as a fraction of the 20-bar average (squeeze measure)."""
    c = df["adj_close"]
    return 4 * c.rolling(20).std() / c.rolling(20).mean()


PER_TICKER = {f.__name__: f for f in (
    vol_ratio_5_20, vol_state_1y, mom_12_1, days_since_52w_high, days_since_52w_low,
    adx_14, stoch_k_14, boll_pctb_20, boll_bandwidth_20, cmf_20)}
# (the ones also in indicators.PER_TICKER are in the production feature set now; the sandbox
#  skips any candidate whose name already exists as a feature)


def compute_candidates(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({name: fn(df) for name, fn in PER_TICKER.items()}, index=df.index)


market_candidates = market_features


def cross_sectional_rank(values_by_ticker: dict[str, pd.Series]) -> pd.DataFrame:
    """Per-date percentile rank of each ticker's value among all tickers that day.
    Returns a (date x ticker) frame."""
    return pd.DataFrame(values_by_ticker).rank(axis=1, pct=True)
