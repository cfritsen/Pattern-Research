
"""Indicator definitions added to the feature set after the redundancy-sandbox study
(scripts/indicator_sandbox.py). Every value at bar t uses only bars up to and including t.
candidates.py re-uses these so the sandbox and the pipeline share one definition."""
from __future__ import annotations
import numpy as np
import pandas as pd

WINDOW_1Y = 252
VIX_TICKER = "^VIX"


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    h, l, pc = df["adj_high"], df["adj_low"], df["adj_close"].shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def vol_ratio_5_20(df):
    """Short-term vs medium-term volatility: ATR(5) / ATR(20). Above 1 = volatility rising."""
    tr = true_range(df)
    return wilder(tr, 5) / wilder(tr, 20)


def vol_state_1y(df):
    """The stock's current ATR% relative to its OWN trailing-year average ATR%.
    Above 1 = more turbulent than usual for this stock; below 1 = quieter than usual."""
    atr_pct = wilder(true_range(df), 14) / df["adj_close"]
    return atr_pct / atr_pct.rolling(WINDOW_1Y, min_periods=200).mean()


def mom_12_1(df):
    """Return from 12 months ago to 1 month ago (skips the most recent month)."""
    c = df["adj_close"]
    return c.shift(21) / c.shift(WINDOW_1Y) - 1


def bars_since_extreme(c: pd.Series, pick) -> pd.Series:
    # reversed window: position 0 is the current bar, so the argmax/argmin position
    # is the number of bars since the latest high/low. Windows holding a NaN stay NaN.
    return c.rolling(WINDOW_1Y).apply(lambda x: pick(x[::-1]), raw=True)


def days_since_52w_low(df):
    return bars_since_extreme(df["adj_close"], np.argmin)


def adx_14(df):
    """Average Directional Index: trend STRENGTH (0-100), regardless of direction."""
    h, l = df["adj_high"], df["adj_low"]
    up, down = h.diff(), -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = wilder(true_range(df), 14)
    plus_di = 100 * wilder(plus_dm, 14) / atr
    minus_di = 100 * wilder(minus_dm, 14) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return wilder(dx, 14)


def cmf_20(df):
    """Chaikin money flow: volume-weighted close location over 20 bars (-1 to +1)."""
    h, l, c = df["adj_high"], df["adj_low"], df["adj_close"]
    vol = df["volume"].where(df["volume"] > 0)
    mfm = (((c - l) - (h - c)) / (h - l).where(h > l))
    return (mfm * vol).rolling(20, min_periods=15).sum() / vol.rolling(20, min_periods=15).sum()


# name -> function, computed per ticker from its own OHLCV
PER_TICKER = {f.__name__: f for f in (vol_ratio_5_20, vol_state_1y, mom_12_1, days_since_52w_low, adx_14, cmf_20)}

# computed once per index (not per ticker); every stock gets the same value on a given date
MARKET_FEATURES = ("mkt_dist_sma200", "vix_pct_252")


def market_features(proxy_close: pd.Series, vix_close: pd.Series | None) -> pd.DataFrame:
    """Date-level features, indexed by the index proxy's dates. The VIX column exists only
    when VIX history is supplied."""
    out = pd.DataFrame(index=proxy_close.index)
    out["mkt_dist_sma200"] = proxy_close / proxy_close.rolling(200).mean() - 1
    if vix_close is not None:
        v = vix_close.reindex(proxy_close.index).ffill()
        out["vix_pct_252"] = v.rolling(WINDOW_1Y, min_periods=200).rank(pct=True)
    return out


def load_vix_close(cfg: dict) -> pd.Series | None:
    """VIX closes: refreshes the cached ^VIX file if it can, falls back to the cache, and
    returns None (with a printed note) if neither works."""
    from patternlab.config import index_data_dir
    try:
        from patternlab.fetch import get_prices
        return get_prices(VIX_TICKER, cfg, incremental=True)[0]["adj_close"].dropna()
    except Exception as e:                                                 # noqa: BLE001
        path = index_data_dir(cfg, "raw") / f"{VIX_TICKER}.parquet"
        if path.exists():
            print(f"  (VIX refresh failed, using cached file: {e})")
            return pd.read_parquet(path)["adj_close"].dropna()
        print(f"  (VIX unavailable: {e}. vix_pct_252 will not be computed.)")
        return None
