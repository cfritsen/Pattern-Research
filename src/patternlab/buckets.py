from __future__ import annotations
import pandas as pd

CATEGORICAL = {"dow", "month"}
N_QUANTILES = 5


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