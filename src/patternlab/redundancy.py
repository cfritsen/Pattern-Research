"""Redundancy analysis for the indicator sandbox: how much of a feature is already
explained by other features. Pure functions on a DataFrame; no file or network access."""
from __future__ import annotations
import numpy as np
import pandas as pd

# A candidate is REDUNDANT when it correlates at or above the same threshold M5 uses
# to prune near-duplicate feature pairs (config: corr_prune_threshold), or when the
# existing features together explain 85%+ of it. OVERLAPS is the grey zone.
R2_REDUNDANT = 0.85
RHO_OVERLAPS = 0.5
R2_OVERLAPS = 0.5


def to_ranks(df: pd.DataFrame) -> pd.DataFrame:
    return df.rank(pct=True)


def r_squared(y: pd.Series, X: pd.DataFrame) -> float:
    """R-squared of regressing y on the columns of X (with intercept), complete rows only."""
    data = pd.concat([y.rename("__y__"), X], axis=1).dropna()
    if len(data) < 50 or data["__y__"].std() == 0:
        return float("nan")
    A = np.column_stack([np.ones(len(data)), data.drop(columns="__y__").to_numpy(dtype="float64")])
    yy = data["__y__"].to_numpy(dtype="float64")
    beta, *_ = np.linalg.lstsq(A, yy, rcond=None)
    resid = yy - A @ beta
    return float(1 - resid.var() / yy.var())


def verdict(max_abs_rho: float, r2: float, prune_threshold: float) -> str:
    if max_abs_rho >= prune_threshold or (r2 == r2 and r2 >= R2_REDUNDANT):
        return "REDUNDANT"
    if max_abs_rho >= RHO_OVERLAPS or (r2 == r2 and r2 >= R2_OVERLAPS):
        return "OVERLAPS"
    return "NEW"


def candidate_report(existing: pd.DataFrame, candidates: pd.DataFrame, prune_threshold: float) -> pd.DataFrame:
    """One row per candidate: strongest single correlation with an existing feature (Spearman,
    via ranks), the three closest existing features, R-squared against ALL existing features
    together, and a verdict."""
    ex_r, ca_r = to_ranks(existing), to_ranks(candidates)
    rows = []
    for name in candidates.columns:
        rho = ex_r.corrwith(ca_r[name]).dropna()
        order = rho.abs().sort_values(ascending=False)
        top = order.index[:3]
        mx = float(order.iloc[0]) if len(order) else float("nan")
        r2 = r_squared(ca_r[name], ex_r)
        rows.append({
            "candidate": name,
            "max_abs_rho": round(mx, 3),
            "closest_feature": top[0] if len(top) else "",
            "closest_three": ", ".join(f"{t} ({rho[t]:+.2f})" for t in top),
            "r2_vs_all_existing": round(r2, 3),
            "verdict": verdict(mx, r2, prune_threshold),
            "rows_used": int(candidates[name].notna().sum()),
        })
    return pd.DataFrame(rows).sort_values("max_abs_rho", ascending=False).reset_index(drop=True)


def feature_pairs(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Every pair of columns with |Spearman| at or above the threshold."""
    c = to_ranks(df).corr()
    out = []
    cols = list(c.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            v = c.loc[a, b]
            if v == v and abs(v) >= threshold:
                out.append({"feature_a": a, "feature_b": b, "rho": round(float(v), 3)})
    return pd.DataFrame(out, columns=["feature_a", "feature_b", "rho"]).sort_values(
        "rho", key=lambda s: -s.abs()).reset_index(drop=True)


def explained_by_others(df: pd.DataFrame) -> pd.DataFrame:
    """For each column: R-squared against all the other columns. High = mostly
    reconstructable from the rest (a trim candidate), low = carries its own information."""
    r = to_ranks(df)
    rows = [{"feature": c, "r2_vs_others": round(r_squared(r[c], r.drop(columns=c)), 3)} for c in r.columns]
    return pd.DataFrame(rows).sort_values("r2_vs_others", ascending=False).reset_index(drop=True)


def _smc(corr: np.ndarray, idx: list[int]) -> np.ndarray:
    """R-squared of each variable on all the others, from a correlation matrix:
    1 - 1/(R^-1)_ii. Same answer as one regression per variable, in one inversion."""
    inv = np.linalg.pinv(corr[np.ix_(idx, idx)])
    return np.clip(1 - 1 / np.diag(inv), 0.0, 1.0)


def trim_order(df: pd.DataFrame, threshold: float = R2_REDUNDANT, forced=(), protected=(),
               max_remove: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Backward elimination. Repeatedly removes the feature the remaining features explain best,
    recomputing after every removal, until none reaches `threshold`.

    forced:    removed first, in the given order, regardless of their score (manual trims).
    protected: never removed automatically.
    max_remove: stop after this many removals in total (forced ones count).
    Returns (steps, remaining). `steps` has the order, each feature's R-squared against what
    was left at the moment it was removed, and the closest remaining features at that moment.
    """
    r = to_ranks(df).dropna()
    names = list(r.columns)
    corr = r.corr().to_numpy()
    for f in list(forced) + list(protected):
        if f not in names:
            raise ValueError(f"unknown feature {f!r}; available: {names}")
    live = list(range(len(names)))
    steps = []

    def remove(i: int, r2_i: float, reason: str) -> None:
        live.remove(i)
        rest = sorted(live, key=lambda j: -abs(corr[i, j]))[:3]
        steps.append({"step": len(steps) + 1, "feature": names[i], "r2_at_removal": round(float(r2_i), 3),
                      "reason": reason,
                      "closest_remaining": ", ".join(f"{names[j]} ({corr[i, j]:+.2f})" for j in rest)})

    for f in forced:
        i = names.index(f)
        remove(i, _smc(corr, live)[live.index(i)], "forced")
    prot = {names.index(f) for f in protected}
    while len(live) > 2 and (max_remove is None or len(steps) < max_remove):
        r2 = _smc(corr, live)
        order = [k for k in np.argsort(-r2) if live[k] not in prot]
        if not order or r2[order[0]] < threshold:
            break
        remove(live[order[0]], r2[order[0]], "auto")
    final = _smc(corr, live)
    remaining = pd.DataFrame({"feature": [names[i] for i in live], "r2_vs_others": np.round(final, 3)}) \
        .sort_values("r2_vs_others", ascending=False).reset_index(drop=True)
    return pd.DataFrame(steps, columns=["step", "feature", "r2_at_removal", "reason", "closest_remaining"]), remaining
