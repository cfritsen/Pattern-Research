from __future__ import annotations
import numpy as np
import pandas as pd

ATR_N = 14


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    gain = _wilder(d.clip(lower=0), n)
    loss = _wilder((-d).clip(lower=0), n)
    return 100 * gain / (gain + loss)          # equals the usual 100 - 100/(1+RS)


def _streak(c: pd.Series) -> pd.Series:
    """Signed run length: +3 = third straight up close, -2 = second straight down close."""
    sgn = np.sign(c.diff()).fillna(0)
    grp = (sgn != sgn.shift()).cumsum()
    return sgn * (sgn.groupby(grp).cumcount() + 1)


def compute_features(df: pd.DataFrame, index_close: pd.Series | None = None) -> pd.DataFrame:
    """Every value at bar t uses only bars up to and including t.
    df needs adj_open/adj_high/adj_low/adj_close and volume (raw)."""
    o, h, l, c = df["adj_open"], df["adj_high"], df["adj_low"], df["adj_close"]
    vol = df["volume"].where(df["volume"] > 0)          # zero volume -> missing
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = _wilder(tr, ATR_N)

    f = pd.DataFrame(index=df.index)
    for n in (1, 3, 5, 10, 20):
        f[f"ret_{n}"] = c.pct_change(n, fill_method=None)
    for n in (20, 50, 200):
        f[f"dist_sma{n}_atr"] = (c - c.rolling(n).mean()) / atr
    f["rsi14"] = _rsi(c)
    macd = c.ewm(span=12, adjust=False, min_periods=12).mean() - \
           c.ewm(span=26, adjust=False, min_periods=26).mean()
    f["macd_hist_pct"] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / c
    f["atr_pct"] = atr / c
    f["range_comp_10"] = (h.rolling(10).max() - l.rolling(10).min()) / atr
    f["gap_pct"] = o / pc - 1

    rng = (h - l).where(h > l)                           # zero-range bars -> missing
    f["body_ratio"] = (c - o).abs() / rng
    f["upper_wick_ratio"] = (h - np.maximum(o, c)) / rng
    f["lower_wick_ratio"] = (np.minimum(o, c) - l) / rng
    f["close_loc"] = (c - l) / rng
    f["streak"] = _streak(c)

    # average of the 20 bars BEFORE t, so a volume spike doesn't dilute its own ratio
    f["vol_rel_20"] = vol / vol.rolling(20, min_periods=15).mean().shift(1)
    f["dow"] = df.index.dayofweek
    f["month"] = df.index.month

    if index_close is not None:
        idx_ret = index_close.pct_change(20, fill_method=None).reindex(df.index)
        f["rel_strength_20"] = c.pct_change(20, fill_method=None) - idx_ret

    # also serves as "drawdown from high" (same quantity over 252 bars)
    f["dist_52w_high"] = c / c.rolling(252).max() - 1
    f["dist_52w_low"] = c / c.rolling(252).min() - 1
    f["tradable"] = df["volume"] > 0
    return f