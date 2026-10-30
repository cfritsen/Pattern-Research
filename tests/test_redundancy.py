import numpy as np
import pandas as pd
import pytest
from patternlab.redundancy import (candidate_report, explained_by_others, feature_pairs, r_squared,
                                   to_ranks, trim_order, verdict)


def _frame(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    a, b = rng.normal(size=n), rng.normal(size=n)
    return pd.DataFrame({"a": a, "b": b}), a, b, rng


def test_duplicate_candidate_is_flagged_redundant():
    ex, a, b, rng = _frame()
    cand = pd.DataFrame({"twin": a * 2 + rng.normal(0, 0.05, len(a)), "indep": rng.normal(size=len(a))})
    rep = candidate_report(ex, cand, prune_threshold=0.7).set_index("candidate")
    assert rep.loc["twin", "verdict"] == "REDUNDANT" and rep.loc["twin", "closest_feature"] == "a"
    assert rep.loc["indep", "verdict"] == "NEW"


def test_combination_of_features_is_caught_by_r2_even_when_each_correlation_is_modest():
    ex, a, b, rng = _frame()
    cand = pd.DataFrame({"blend": a + b + rng.normal(0, 0.05, len(a))})
    rep = candidate_report(ex, cand, prune_threshold=0.9).set_index("candidate")   # |rho| ~0.7 each < 0.9
    assert rep.loc["blend", "r2_vs_all_existing"] > 0.9
    assert rep.loc["blend", "verdict"] == "REDUNDANT"


def test_r_squared_basic_and_too_little_data():
    ex, a, b, rng = _frame()
    assert r_squared(pd.Series(a), ex[["a"]]) > 0.99
    assert abs(r_squared(pd.Series(rng.normal(size=len(a))), ex)) < 0.05
    assert np.isnan(r_squared(pd.Series([1.0, 2.0, 3.0]), pd.DataFrame({"x": [1.0, 2.0, 3.0]})))


def test_pairs_and_explained_by_others():
    ex, a, b, rng = _frame()
    ex["a_copy"] = a + rng.normal(0, 0.05, len(a))
    pairs = feature_pairs(ex, 0.7)
    assert set(pairs.iloc[0][["feature_a", "feature_b"]]) == {"a", "a_copy"}
    ex_by = explained_by_others(ex).set_index("feature")
    assert ex_by.loc["a", "r2_vs_others"] > 0.9 and ex_by.loc["b", "r2_vs_others"] < 0.05


def test_verdict_thresholds():
    assert verdict(0.2, 0.1, 0.7) == "NEW"
    assert verdict(0.55, 0.1, 0.7) == "OVERLAPS"
    assert verdict(0.2, 0.6, 0.7) == "OVERLAPS"
    assert verdict(0.75, 0.1, 0.7) == "REDUNDANT"
    assert verdict(0.2, float("nan"), 0.7) == "NEW"


def _trim_frame(n=4000, seed=1):
    rng = np.random.default_rng(seed)
    a, b, d = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
    return pd.DataFrame({"a": a, "a_twin": a + rng.normal(0, 0.05, n), "b": b, "d": d})


def test_trim_removes_one_of_a_duplicate_pair_then_stops():
    steps, remaining = trim_order(_trim_frame())
    assert len(steps) == 1 and steps.loc[0, "feature"] in {"a", "a_twin"}
    assert steps.loc[0, "r2_at_removal"] > 0.95
    assert set(remaining["feature"]) == {"a", "a_twin", "b", "d"} - {steps.loc[0, "feature"]}
    assert remaining["r2_vs_others"].max() < 0.05          # after the removal nothing overlaps


def test_trim_score_matches_a_direct_regression():
    df = _trim_frame()
    steps, _ = trim_order(df, forced=["a_twin"])
    direct = r_squared(to_ranks(df)["a_twin"], to_ranks(df).drop(columns="a_twin"))
    assert steps.loc[0, "reason"] == "forced" and steps.loc[0, "r2_at_removal"] == pytest.approx(direct, abs=0.01)


def test_trim_protected_and_max_remove_and_unknown_names():
    df = _trim_frame()
    steps, _ = trim_order(df, protected=["a", "a_twin"])
    assert len(steps) == 0                                   # the only overlap is protected
    steps, _ = trim_order(df, forced=["b"], max_remove=1)
    assert list(steps["feature"]) == ["b"]                   # forced counts toward the limit; no auto step added
    with pytest.raises(ValueError):
        trim_order(df, forced=["nope"])


def test_trim_recomputes_after_each_removal():
    rng = np.random.default_rng(5)
    a = rng.normal(size=4000)
    df = pd.DataFrame({"a": a, "b": a + rng.normal(0, 0.3, 4000), "c": a + rng.normal(0, 0.3, 4000),
                       "x": rng.normal(size=4000)})
    steps, remaining = trim_order(df, threshold=0.8)
    # b and c each look explained by a AND each other at first; once one goes, the other is no longer "redundant"
    assert 1 <= len(steps) <= 2 and "x" in set(remaining["feature"])
