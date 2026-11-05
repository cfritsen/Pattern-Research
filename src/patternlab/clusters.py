"""Group passed patterns that fire on mostly the same days.

Many passed patterns are one effect seen through different measurements (for
example every "the stock just fell" feature). This groups them for reporting.
It changes nothing in the search or the statistics: every pattern keeps its own
numbers and case counts.

Method: for each pattern, the set of discovery-period rows (stock-days, All Data
view) where it fires. Two patterns are similar when their Jaccard overlap
(shared days / days in either) is at least CLUSTER_JACCARD. Greedy, strongest
first: the pattern with the largest |effect| leads a group; each next pattern
joins the lead it overlaps most (if any reaches the threshold), else leads a
group of its own. Joining only ever compares to leads, so a long chain of
loosely similar patterns can't merge into one big group.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

CLUSTER_JACCARD = 0.5
_POP = np.array([bin(i).count("1") for i in range(256)], dtype=np.int64)


def pack(mask: np.ndarray) -> np.ndarray:
    """Boolean mask -> packed bits (8 rows per byte)."""
    return np.packbits(np.asarray(mask, dtype=bool))


def _count(packed: np.ndarray) -> int:
    return int(_POP[packed].sum())


def jaccard(a: np.ndarray, b: np.ndarray, count_a: int | None = None, count_b: int | None = None) -> float:
    ca = _count(a) if count_a is None else count_a
    cb = _count(b) if count_b is None else count_b
    inter = int(_POP[a & b].sum())
    union = ca + cb - inter
    return inter / union if union else 0.0


def cluster_patterns(packed: dict[int, np.ndarray], strength: dict[int, float],
                     threshold: float = CLUSTER_JACCARD) -> pd.DataFrame:
    """packed: pattern_id -> packed day mask (same length for all).
    strength: pattern_id -> |effect| (larger leads). Returns one row per pattern:
    pattern_id, cluster_id (the lead's pattern_id), is_lead, cluster_size, jaccard
    (overlap with its lead; 1.0 for a lead)."""
    order = sorted(packed, key=lambda p: (-float(strength.get(p, 0.0) or 0.0), p))
    counts = {p: _count(packed[p]) for p in order}
    leads: list[int] = []
    assign: dict[int, tuple[int, float]] = {}
    for p in order:
        best, best_j = None, 0.0
        for lead in leads:
            j = jaccard(packed[p], packed[lead], counts[p], counts[lead])
            if j >= threshold and j > best_j:
                best, best_j = lead, j
        if best is None:
            leads.append(p)
            assign[p] = (p, 1.0)
        else:
            assign[p] = (best, best_j)
    out = pd.DataFrame([(p, c, p == c, j) for p, (c, j) in assign.items()],
                       columns=["pattern_id", "cluster_id", "is_lead", "jaccard"])
    out["cluster_size"] = out.groupby("cluster_id")["pattern_id"].transform("size")
    return out.sort_values(["cluster_id", "is_lead", "jaccard"], ascending=[True, False, False]).reset_index(drop=True)
