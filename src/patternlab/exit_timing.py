from __future__ import annotations
import numpy as np
import pandas as pd


def exit_day_mask(condition: pd.Series, ticker: pd.Series, bar_pos: pd.Series) -> pd.Series:
    """True on the first bar where `condition` is False immediately after a
    run where it was True -- i.e. 'the pattern just stopped being true'.
    A run still True at the end of a ticker's data has no exit bar (nothing
    to measure) and is correctly excluded, not counted as an exit."""
    df = pd.DataFrame({"cond": condition.to_numpy(), "ticker": ticker.to_numpy(),
                       "bar_pos": bar_pos.to_numpy()}, index=condition.index)
    df = df.sort_values(["ticker", "bar_pos"])
    prev_true = df.groupby("ticker")["cond"].shift(1).fillna(False)
    is_exit = (~df["cond"]) & prev_true
    return is_exit.reindex(condition.index).fillna(False)