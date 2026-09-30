from __future__ import annotations
import numpy as np
import pandas as pd


def per_stock_breakdown(thin: pd.DataFrame, h0: int, min_n: int) -> pd.DataFrame:
    """Per-ticker n, mean forward return, hit rate, and effect vs. the pooled
    mean. Every ticker with at least one occurrence keeps its row -- n is an
    exact count and always shown. mean/hit_rate/effect are nulled out (not
    the row dropped) when n is below min_n, since those are averages that
    need a real sample size to mean anything, unlike a plain count."""
    g = thin.groupby("ticker")
    out = g[f"fwd_ret_{h0}"].agg(n="count", mean="mean")
    out["hit_rate"] = g["up_hit"].mean().reindex(out.index)
    out["effect"] = out["mean"] - thin[f"fwd_ret_{h0}"].mean()
    below = out["n"] < min_n
    out.loc[below, ["mean", "hit_rate", "effect"]] = np.nan
    return out