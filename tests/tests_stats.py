import numpy as np
import pandas as pd
import pytest
from patternlab.stats import thin_non_overlapping, cluster_bootstrap_pvalue, benjamini_hochberg, breadth
from patternlab.buckets import quantile_edges, apply_buckets, bucket_feature


def test_thinning_keeps_first_and_skips_within_horizon():
    dates = pd.RangeIndex(10)
    ticker = pd.Series(["A"] * 10)
    keep = thin_non_overlapping(dates, ticker, horizon=5)
    assert keep.tolist() == [True, False, False, False, False, True, False, False, False, False]


def test_thinning_is_per_ticker():
    dates = pd.RangeIndex(6)
    ticker = pd.Series(["A", "A", "A", "B", "B", "B"])
    keep = thin_non_overlapping(dates, ticker, horizon=3)
    assert keep.tolist() == [True, False, False, True, False, False]


def test_bootstrap_detects_a_real_shift():
    rng = np.random.default_rng(0)
    n = 400
    values = rng.normal(0.02, 0.01, n)          # true mean well above baseline 0
    dates = np.repeat(np.arange(50), 8)
    p, lo, hi = cluster_bootstrap_pvalue(values, dates, baseline=0.0, n_boot=500)
    assert p < 0.01
    assert lo > 0


def test_bootstrap_does_not_flag_pure_noise():
    rng = np.random.default_rng(1)
    n = 400
    values = rng.normal(0.0, 0.01, n)
    dates = np.repeat(np.arange(50), 8)
    p, lo, hi = cluster_bootstrap_pvalue(values, dates, baseline=0.0, n_boot=500)
    assert p > 0.05


def test_bh_controls_false_discoveries_on_pure_noise():
    rng = np.random.default_rng(2)
    pvals = rng.uniform(0, 1, 1000)              # all null: p-values are uniform
    passed = benjamini_hochberg(pvals, q=0.05)
    assert passed.sum() < 100                    # well under the ~50 expected by chance at 5%


def test_bh_passes_obvious_signal():
    pvals = np.array([0.001, 0.002, 0.5, 0.6, 0.7, 0.8])
    assert benjamini_hochberg(pvals, q=0.05)[:2].all()
    assert not benjamini_hochberg(pvals, q=0.05)[2:].any()


def test_breadth_all_positive():
    v = np.array([1, 2, 3, 4])
    t = np.array(["A", "A", "B", "B"])
    y = np.array([2020, 2020, 2021, 2021])
    s, y_ = breadth(v, t, y, baseline=0)
    assert s == 1.0 and y_ == 1.0


def test_quantile_edges_from_discovery_only():
    disc = pd.Series(range(100))
    edges = quantile_edges(disc, n=5)
    assert len(edges) == 4
    assert edges == sorted(edges)


def test_bucket_ignores_confirm_distribution():
    disc = pd.Series(range(100), dtype=float)
    is_disc = pd.Series([True] * 100)
    edges_disc_only, _ = bucket_feature(disc, is_disc)
    combined = pd.concat([disc, pd.Series(range(1000, 1100), dtype=float)], ignore_index=True)
    is_disc2 = pd.Series([True] * 100 + [False] * 100)
    edges_combined, edges_list = bucket_feature(combined, is_disc2)
    assert edges_combined.iloc[:100].tolist() == edges_disc_only.tolist()
    assert edges_combined.iloc[100:].max() == 4  # future extreme values fall in the top bucket, not a new one


def test_apply_buckets_handles_out_of_range():
    edges = [1.0, 2.0, 3.0]
    b = apply_buckets(pd.Series([-5.0, 1.5, 100.0]), edges)
    assert b.tolist() == [0, 1, 3]