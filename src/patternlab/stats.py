from __future__ import annotations
import numpy as np
import pandas as pd

RNG_SEED = 12345
N_BOOTSTRAP = 2000


def thin_non_overlapping(bar_pos, ticker, horizon: int) -> np.ndarray:
    """Boolean mask keeping the first occurrence per ticker, then any later
    occurrence whose bar_pos is at least `horizon` actual trading bars after
    the last kept occurrence's bar_pos (not `horizon` OCCURRENCES later --
    that was a bug in the original version: it under-thinned occurrences that
    followed shortly, by occurrence count, after a separate burst elsewhere
    in the ticker's history, even when the two were far apart in real time)."""
    pos = np.asarray(bar_pos)
    tick = np.asarray(ticker)
    df = pd.DataFrame({"pos": pos, "ticker": tick})
    keep = np.zeros(len(tick), dtype=bool)
    for _, idx in df.groupby("ticker").groups.items():
        idx = np.asarray(idx)
        order = idx[np.argsort(pos[idx])]
        last_kept_pos = -10**9
        for i in order:
            if pos[i] - last_kept_pos >= horizon:
                keep[i] = True
                last_kept_pos = pos[i]
    return keep


def bh_qvalues(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values (q-values), monotone by construction."""
    n = len(pvals)
    if n == 0:
        return np.array([])
    order = np.argsort(pvals)
    ranked = pvals[order]
    raw_q = ranked * n / np.arange(1, n + 1)
    q_sorted = np.minimum.accumulate(raw_q[::-1])[::-1]
    q_sorted = np.clip(q_sorted, 0, 1)
    out = np.empty(n)
    out[order] = q_sorted
    return out


def cluster_bootstrap_pvalue(values: np.ndarray, dates: np.ndarray, baseline: float,
                              n_boot: int = N_BOOTSTRAP, seed: int = RNG_SEED) -> tuple[float, float, float]:
    """Two-sided p-value for mean(values) != baseline, resampling by calendar
    date (not by row), since same-day observations across stocks are correlated
    (Section 7: 'stocks move together'). Returns (p_value, ci_low, ci_high) on
    the mean, via percentile bootstrap of date-cluster means."""
    df = pd.DataFrame({"v": values, "d": dates})
    day_means = df.groupby("d")["v"].mean()
    day_counts = df.groupby("d")["v"].size()
    days = day_means.index.to_numpy()
    means = day_means.to_numpy()
    weights = day_counts.to_numpy()
    if len(days) < 2:
        return 1.0, float("nan"), float("nan")

    rng = np.random.default_rng(seed)
    n = len(days)
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, n, n)
        boot_means[b] = np.average(means[pick], weights=weights[pick])

    observed = np.average(means, weights=weights)
    centered = boot_means - boot_means.mean() + observed
    p = 2 * min((centered >= baseline).mean(), (centered <= baseline).mean())
    p = min(1.0, p)
    lo, hi = np.percentile(boot_means, [2.5, 97.5])
    return float(p), float(lo), float(hi)


def benjamini_hochberg(pvals: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Returns a boolean pass/fail array at FDR level q."""
    n = len(pvals)
    if n == 0:
        return np.array([], dtype=bool)
    order = np.argsort(pvals)
    ranked = pvals[order]
    thresh = (np.arange(1, n + 1) / n) * q
    below = ranked <= thresh
    if not below.any():
        return np.zeros(n, dtype=bool)
    cutoff_rank = np.max(np.where(below)[0])
    pass_sorted = np.zeros(n, dtype=bool)
    pass_sorted[:cutoff_rank + 1] = True
    passed = np.zeros(n, dtype=bool)
    passed[order] = pass_sorted
    return passed


def breadth(values: np.ndarray, ticker: np.ndarray, year: np.ndarray, baseline: float) -> tuple[float, float]:
    """Fraction of stocks with mean(values) > baseline, and fraction of years likewise."""
    df = pd.DataFrame({"v": values, "t": ticker, "y": year})
    by_stock = df.groupby("t")["v"].mean()
    by_year = df.groupby("y")["v"].mean()
    stock_frac = float((by_stock > baseline).mean()) if len(by_stock) else float("nan")
    year_frac = float((by_year > baseline).mean()) if len(by_year) else float("nan")
    return stock_frac, year_frac