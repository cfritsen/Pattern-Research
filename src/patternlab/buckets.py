from __future__ import annotations
import pandas as pd

CATEGORICAL = {"month"}
N_QUANTILES = 5

# Features with the same value for every stock on a given date. A condition on one of
# these selects the whole market on those dates, so measured against the same-day market
# mean (the significance test's baseline) its excess return is ~0 by construction:
# alone, or paired with another date-level feature, it cannot pass. Pairing it with a
# stock-level feature is the useful case (a stock-level pattern within a regime).
MARKET_LEVEL = {"mkt_dist_sma200", "vix_pct_252"}
DATE_LEVEL = CATEGORICAL | MARKET_LEVEL


def drop_date_level_pairs(pairs):
    """Remove feature pairs where BOTH features are date-level (guaranteed null results)."""
    return [p for p in pairs if not (p[0] in DATE_LEVEL and p[1] in DATE_LEVEL)]


def quantile_edges(discovery_values: pd.Series, n: int = N_QUANTILES) -> list[float]:
    """Bucket edges from discovery-period data only. Returns n-1 interior edges;
    the outer buckets extend to -inf/+inf so out-of-range future values still bucket."""
    x = discovery_values.dropna()
    qs = [i / n for i in range(1, n)]
    edges = x.quantile(qs).tolist()
    edges = sorted(set(round(e, 10) for e in edges))   # dedupe ties (sparse features)
    return edges


def apply_buckets(values: pd.Series, edges: list[float]) -> pd.Series:
    if not edges:
        return pd.Series(pd.NA, index=values.index, dtype="Int8")
    bounds = [float("-inf")] + edges + [float("inf")]
    labels = list(range(len(bounds) - 1))
    return pd.cut(values, bins=bounds, labels=labels, include_lowest=True).astype("Int8")


def bucket_feature(all_values: pd.Series, is_discovery: pd.Series) -> tuple[pd.Series, list[float]]:
    if all_values.name in CATEGORICAL:
        return all_values.astype("Int8"), []
    edges = quantile_edges(all_values[is_discovery])
    return apply_buckets(all_values, edges), edges