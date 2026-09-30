from __future__ import annotations
import pandas as pd


def year_breakdown(thin: pd.DataFrame, h0: int) -> tuple[float, float]:
    """(top3_year_share, mean_fwd_return excluding the top-3-occurrence years),
    for an already-thinned occurrence set. High top3_year_share means the
    pooled effect may be driven by a few episodes rather than a broadly
    recurring pattern -- see the M5 April finding for a real example."""
    by_year = thin.groupby("year")[f"fwd_ret_{h0}"].agg(["count", "mean"]).sort_values("count", ascending=False)
    if len(by_year) == 0:
        return float("nan"), float("nan")
    top3_share = float(by_year["count"].head(3).sum() / by_year["count"].sum())
    rest_years = by_year.iloc[3:].index
    rest = thin[thin["year"].isin(rest_years)][f"fwd_ret_{h0}"]
    mean_excl = float(rest.mean()) if len(rest) else float("nan")
    return top3_share, mean_excl