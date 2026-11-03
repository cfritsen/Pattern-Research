from __future__ import annotations
from datetime import date
from pathlib import Path
from patternlab.config import index_data_dir
from patternlab.session import last_completed_session_date
import pandas as pd

ZERO_WINDOW = 60
ZERO_FRAC = 0.50


def clean_prices(df: pd.DataFrame, last_complete: date | None = None,
                 start: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Rules: (1) drop bars from sessions that haven't completed (anything
    after the latest completed session, 4:15 PM Eastern -- see session.py;
    `last_complete` overrides it for tests),
    (2) apply a manual start date if given, (3) trim leading history where
    >=20% of a 60-bar window has zero volume (wrong-listing prehistory)."""
    notes = {"rows_in": len(df), "dropped_today": 0,
             "trimmed_prehistory": 0, "start_override": start}
    last_complete = last_complete or last_completed_session_date()

    keep = df.index <= pd.Timestamp(last_complete)
    notes["dropped_today"] = int((~keep).sum())
    df = df.loc[keep]

    if start:
        df = df.loc[df.index >= pd.Timestamp(start)]

    zero = df["volume"] == 0
    frac = zero.rolling(ZERO_WINDOW, min_periods=ZERO_WINDOW).mean()
    bad = (zero & (frac > ZERO_FRAC)).to_numpy()
    if bad.any():
        last_bad = len(bad) - 1 - int(bad[::-1].argmax())
        notes["trimmed_prehistory"] = last_bad + 1
        df = df.iloc[last_bad + 1:]

    notes["rows_out"] = len(df)
    return df, notes


def load_clean(ticker: str, cfg: dict) -> tuple[pd.DataFrame, dict]:
    df = pd.read_parquet(index_data_dir(cfg, "raw") / f"{ticker}.parquet")
    start = (cfg.get("start_overrides") or {}).get(ticker)
    return clean_prices(df, start=start)