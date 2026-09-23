from __future__ import annotations
import pandas as pd


def bucket_overlap_ratio(bucket_a: pd.Series, label_a: int, bucket_b: pd.Series,
                         label_b: int, scope: pd.Series) -> float:
    """observed co-occurrence rate / rate expected under independence, within
    `scope` (a given view + split). >1: co-occur more than chance. <1: less.
    ~1: independent. NaN if the scope is empty or a bucket never occurs in it."""
    a = (bucket_a == label_a) & scope
    b = (bucket_b == label_b) & scope
    n = int(scope.sum())
    if n == 0:
        return float("nan")
    p_a, p_b = a.sum() / n, b.sum() / n
    expected = p_a * p_b
    if expected == 0:
        return float("nan")
    return float((a & b).sum() / n / expected)