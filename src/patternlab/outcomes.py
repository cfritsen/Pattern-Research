from __future__ import annotations
import numpy as np
import pandas as pd

HORIZONS = (1, 5, 10, 20, 63, 126, 252)


def compute_outcomes(close: pd.Series, horizons=HORIZONS) -> pd.DataFrame:
    """Forward return from the close at t to the close h bars later.
    Uses bar t and later only. The last h rows have no outcome (NaN)."""
    out = pd.DataFrame(index=close.index)
    for h in horizons:
        out[f"fwd_ret_{h}"] = close.shift(-h) / close - 1
    return out


def split_cutoff(first: pd.Timestamp, last: pd.Timestamp, frac: float = 0.70) -> pd.Timestamp:
    """Start of the calendar year nearest the frac point of the date range."""
    point = first + (last - first) * frac
    year = point.year + (1 if point.month >= 7 else 0)
    return pd.Timestamp(year=year, month=1, day=1)


def split_labels(index: pd.DatetimeIndex, cutoff: pd.Timestamp, horizons=HORIZONS) -> pd.DataFrame:
    """Per horizon: 0 = discovery, 1 = confirm, -1 = unusable.
    A discovery row is unusable if its outcome window ends on/after the cutoff
    (purge). Rows with no outcome (the last h bars) are also -1."""
    dates = index.to_series()
    lab = pd.DataFrame(index=index)
    for h in horizons:
        end = dates.shift(-h)                       # date of the bar the outcome ends on
        s = np.where(end.isna(), -1,
                     np.where(dates < cutoff, np.where(end < cutoff, 0, -1), 1))
        lab[f"split_{h}"] = s.astype("int8")
    return lab


def hit_flags(fwd: pd.Series, atr_pct: pd.Series, move_atr: float) -> tuple[pd.Series, pd.Series]:
    """1.0 if the forward return reached +/- move_atr * ATR%, else 0.0; NaN if unknown."""
    thr = move_atr * atr_pct
    ok = (fwd.notna() & thr.notna()).to_numpy()
    up = np.where(ok, (fwd >= thr).to_numpy().astype("float32"), np.nan)
    dn = np.where(ok, (fwd <= -thr).to_numpy().astype("float32"), np.nan)
    return (pd.Series(up, index=fwd.index, dtype="float32"),
            pd.Series(dn, index=fwd.index, dtype="float32"))