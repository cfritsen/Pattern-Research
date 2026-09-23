from __future__ import annotations
import pandas as pd


def spearman_matrix(panel: pd.DataFrame, features: list[str], is_discovery: pd.Series) -> pd.DataFrame:
    """Spearman (rank) correlation between raw feature values, discovery period
    only. Outlier-resistant vs. Pearson -- appropriate given fat-tailed return
    data (dot-com, 2008, COVID all showed 25-100%+ single-day moves)."""
    return panel.loc[is_discovery, features].corr(method="spearman")


def prune_pairs(rho: pd.DataFrame, threshold: float) -> tuple[list[tuple[str, str]], list[tuple[str, str, float]]]:
    """Returns (pairs_to_test, pruned_pairs_with_rho). A pair is pruned when
    |Spearman rho| exceeds threshold -- treated as carrying mostly the same
    information (e.g. ret_3 vs ret_10, which overlap by construction)."""
    feats = list(rho.columns)
    keep, pruned = [], []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            a, b = feats[i], feats[j]
            r = rho.loc[a, b]
            if pd.isna(r):
                continue
            (pruned if abs(r) > threshold else keep).append(
                (a, b, float(r)) if abs(r) > threshold else (a, b))
    return keep, pruned