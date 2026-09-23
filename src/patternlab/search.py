from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from patternlab.buckets import bucket_feature
from patternlab.stats import thin_non_overlapping, cluster_bootstrap_pvalue, breadth

MIN_OCCURRENCES = 300
MIN_PER_STOCK = 30
COST = 0.001


def load_panel(cfg: dict, uni: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    h0 = cfg["horizon"]
    feat_dir = Path(cfg["data_dir"]) / "features"
    out_dir = Path(cfg["data_dir"]) / "outcomes"
    feature_cols = [c for c in pd.read_parquet(feat_dir / f"{uni['data_ticker'].iloc[0]}.parquet").columns
                    if c not in ("tradable", "in_index")]
    frames = []
    for t in uni["data_ticker"]:
        f = pd.read_parquet(feat_dir / f"{t}.parquet")
        o = pd.read_parquet(out_dir / f"{t}.parquet", columns=[f"fwd_ret_{h0}", f"split_{h0}",
                                                                "up_hit", "down_hit", "tradable", "in_index"])
        df = f[feature_cols].join(o)
        df["ticker"] = t
        frames.append(df)
    panel = pd.concat(frames)
    # bar_pos = position in each ticker's full bar sequence, computed BEFORE the
    # tradable filter so it matches how forward-return horizons were counted in
    # outcomes.py (which runs on the full cleaned series, not just tradable bars).
    panel["bar_pos"] = panel.groupby("ticker").cumcount()
    panel = panel[panel["tradable"]].copy()
    panel["date"] = panel.index
    panel["year"] = panel["date"].dt.year
    panel.reset_index(drop=True, inplace=True)
    return panel, feature_cols


def build_buckets(panel: pd.DataFrame, feature_cols: list[str], is_disc: pd.Series) -> tuple[pd.DataFrame, dict]:
    frames, edges = {}, {}
    for col in feature_cols:
        if col.startswith(("fwd_ret_", "split_")):
            continue
        b, e = bucket_feature(panel[col], is_disc)
        frames[col] = b
        edges[col] = e
    return pd.DataFrame(frames), edges


def evaluate_condition(sub: pd.DataFrame, market: pd.DataFrame, view: str, h0: int, cost: float) -> dict | None:
    n = len(sub)
    if n < MIN_OCCURRENCES:
        return None
    keep = thin_non_overlapping(sub["bar_pos"], sub["ticker"], h0)
    thin = sub[keep]

    fwd = thin[f"fwd_ret_{h0}"].astype(float)
    dates_np = thin["date"].to_numpy()
    stock_baseline = market.reindex(thin["date"])["fwd_ret"].to_numpy()
    excess = fwd.to_numpy() - stock_baseline
    valid = ~np.isnan(excess)
    excess, dates_np = excess[valid], dates_np[valid]
    if len(excess) < MIN_OCCURRENCES // 2:
        return None

    raw_baseline_mean = float(market["fwd_ret"].mean())
    p, lo, hi = cluster_bootstrap_pvalue(excess, dates_np, baseline=0.0)
    s_frac, y_frac = breadth(fwd.to_numpy(), thin["ticker"].to_numpy(), thin["year"].to_numpy(), raw_baseline_mean)

    mh = thin["up_hit"].notna()
    return dict(
        n_occurrences=int(n), n_thinned=int(len(thin)),
        mean_fwd_return=float(fwd.mean()), baseline_mean=raw_baseline_mean,
        hit_rate=float(thin.loc[mh, "up_hit"].mean()) if mh.any() else float("nan"),
        baseline_hit_rate=float("nan"),
        effect=float(fwd.mean()) - raw_baseline_mean,
        p_value=p, ci_low=lo, ci_high=hi,
        breadth_stocks=s_frac, breadth_years=y_frac,
    )