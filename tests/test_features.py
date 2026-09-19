import numpy as np
import pandas as pd
import pytest
from patternlab.features import compute_features, _rsi, _streak


def synth(n=600, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    close = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    df = pd.DataFrame({"adj_open": open_, "adj_high": high, "adj_low": low,
                       "adj_close": close, "volume": rng.integers(1_000, 100_000, n)}, index=idx)
    idxc = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n))), index=idx)
    return df, idxc


def prefix_equal(fn, df, idxc, k) -> bool:
    full = fn(df, idxc)
    part = fn(df.iloc[:k + 1], idxc.iloc[:k + 1])
    try:
        pd.testing.assert_frame_equal(full.iloc[:k + 1], part, rtol=1e-9, atol=1e-12)
        return True
    except AssertionError:
        return False


@pytest.mark.parametrize("k", [260, 400, 550])
def test_truncating_the_future_does_not_change_features(k):
    df, idxc = synth()
    assert prefix_equal(compute_features, df, idxc, k)


@pytest.mark.parametrize("k", [260, 400, 550])
def test_corrupting_the_future_does_not_change_features(k):
    df, idxc = synth()
    base = compute_features(df, idxc)
    df2, idx2 = df.copy(), idxc.copy()
    rng = np.random.default_rng(1)
    m = len(df) - k - 1
    for col in ["adj_open", "adj_high", "adj_low", "adj_close"]:
        df2.iloc[k + 1:, df2.columns.get_loc(col)] *= rng.uniform(0.5, 2.0, m)
    df2.iloc[k + 1:, df2.columns.get_loc("volume")] = 0
    idx2.iloc[k + 1:] *= rng.uniform(0.5, 2.0, m)
    changed = compute_features(df2, idx2)
    pd.testing.assert_frame_equal(base.iloc[:k + 1], changed.iloc[:k + 1], rtol=1e-9, atol=1e-12)


def test_the_detector_catches_a_deliberate_leak():
    """Proves the tests above can fail: a feature that peeks 5 bars ahead must be flagged."""
    def leaky(df, idxc):
        f = compute_features(df, idxc)
        f["leak"] = df["adj_close"].shift(-5) / df["adj_close"] - 1
        return f
    df, idxc = synth()
    assert not prefix_equal(leaky, df, idxc, 400)


def test_rsi_is_100_on_a_pure_uptrend():
    assert _rsi(pd.Series(np.arange(1, 60, dtype=float))).iloc[-1] == pytest.approx(100.0)


def test_streak_counts():
    s = pd.Series([10, 11, 12, 11, 10, 10, 11], dtype=float)
    assert _streak(s).tolist() == [0, 1, 2, -1, -2, 0, 1]


def test_volume_ratio_excludes_the_current_bar():
    df, _ = synth()
    f = compute_features(df)
    t = 100
    expected = df["volume"].iloc[t] / df["volume"].iloc[t - 20:t].mean()
    assert f["vol_rel_20"].iloc[t] == pytest.approx(expected)


def test_zero_volume_is_missing_and_not_tradable():
    df, _ = synth()
    df.iloc[200, df.columns.get_loc("volume")] = 0
    f = compute_features(df)
    assert np.isnan(f["vol_rel_20"].iloc[200])
    assert not f["tradable"].iloc[200]


def test_close_location_is_between_zero_and_one():
    df, _ = synth()
    assert compute_features(df)["close_loc"].dropna().between(0, 1).all()