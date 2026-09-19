from __future__ import annotations
import pandas as pd


def load_snapshot(path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date_added"], dtype={"snapshot_date": str})


def in_index_flag(dates: pd.DatetimeIndex, date_added) -> pd.Series:
    """True for bars on or after the date the stock joined the index.
    A missing add date is treated as long-standing membership (all bars True)."""
    if pd.isna(date_added):
        return pd.Series(True, index=dates)
    return pd.Series(dates >= pd.Timestamp(date_added), index=dates)