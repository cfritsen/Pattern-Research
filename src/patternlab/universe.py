from __future__ import annotations
import pandas as pd

REQUIRED = ["ticker", "company", "data_ticker", "first_top10_year",
            "last_top10_year", "share_class_note", "data_status"]
VALID_STATUS = {"ok", "partial", "missing"}


def load_universe(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    absent = [c for c in REQUIRED if c not in df.columns]
    if absent:
        raise ValueError(f"Universe CSV missing columns: {absent}")
    for c in df.columns:
        df[c] = df[c].str.strip()
    # blank data_ticker means "same as ticker"
    df["data_ticker"] = df["data_ticker"].where(df["data_ticker"] != "", df["ticker"])
    bad = set(df["data_status"]) - VALID_STATUS
    if bad:
        raise ValueError(f"Invalid data_status values: {bad}")
    for c in ("first_top10_year", "last_top10_year"):
        df[c] = pd.to_numeric(df[c], errors="raise").astype(int)
    if (df["first_top10_year"] > df["last_top10_year"]).any():
        raise ValueError("first_top10_year is after last_top10_year for some rows")
    dups = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
    if dups:
        raise ValueError(f"Duplicate tickers: {dups}")
    return df


def top10_flag(dates: pd.DatetimeIndex, first_year: int, last_year: int) -> pd.Series:
    """True for bars in years first+1 .. last+1 (rankings are known at year-end)."""
    years = dates.year
    return pd.Series((years >= first_year + 1) & (years <= last_year + 1), index=dates)