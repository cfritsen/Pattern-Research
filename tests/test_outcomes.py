import numpy as np
import pandas as pd
import pytest
from patternlab.outcomes import (HORIZONS, compute_outcomes, hit_flags,
                                 split_cutoff, split_labels)


def close_series(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)


def test_forward_return_matches_hand_calculation():
    c = close_series()
    t = 100
    assert compute_outcomes(c)["fwd_ret_5"].iloc[t] == pytest.approx(c.iloc[t + 5] / c.iloc[t] - 1)


def test_last_h_rows_have_no_outcome():
    o = compute_outcomes(close_series())
    for h in HORIZONS:
        assert o[f"fwd_ret_{h}"].iloc[-h:].isna().all()
        assert o[f"fwd_ret_{h}"].iloc[:-h].notna().all()


def test_outcome_ignores_the_past():
    c = close_series()
    t = 100
    c2 = c.copy()
    c2.iloc[:t] *= 3
    pd.testing.assert_series_equal(compute_outcomes(c).iloc[t], compute_outcomes(c2).iloc[t])


def test_outcome_ignores_bars_beyond_its_horizon():
    c = close_series()
    t = 100
    c2 = c.copy()
    c2.iloc[t + 6:] *= 3
    assert compute_outcomes(c)["fwd_ret_5"].iloc[t] == compute_outcomes(c2)["fwd_ret_5"].iloc[t]


def test_cutoff_lands_on_a_year_start():
    assert split_cutoff(pd.Timestamp("1996-01-02"), pd.Timestamp("2026-09-17")) == pd.Timestamp("2018-01-01")
    assert split_cutoff(pd.Timestamp("2000-01-03"), pd.Timestamp("2020-01-03")) == pd.Timestamp("2014-01-01")


def test_split_labels_purge_the_boundary():
    idx = pd.bdate_range("2017-12-01", "2018-02-28")
    s = split_labels(idx, pd.Timestamp("2018-01-01"), horizons=(5,))["split_5"]
    assert s.loc["2017-12-15"] == 0        # outcome ends 2017-12-22
    assert s.loc["2017-12-27"] == -1       # outcome window crosses the cutoff
    assert s.loc["2018-01-02"] == 1
    assert s.iloc[-1] == -1                # no outcome available


def test_hit_flags():
    fwd = pd.Series([0.03, -0.03, 0.01, np.nan])
    atr = pd.Series([0.02] * 4)
    up, dn = hit_flags(fwd, atr, 1.0)
    assert up.tolist()[:3] == [1.0, 0.0, 0.0] and np.isnan(up.iloc[3])
    assert dn.tolist()[:3] == [0.0, 1.0, 0.0] and np.isnan(dn.iloc[3])