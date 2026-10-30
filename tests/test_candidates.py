import numpy as np
import pandas as pd
import pytest
from patternlab.candidates import (PER_TICKER, compute_candidates, cross_sectional_rank,
                                   market_candidates)


def _ohlcv(n=700, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n)))
    o = c * (1 + rng.normal(0, 0.004, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.005, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.005, n)))
    return pd.DataFrame({"adj_open": o, "adj_high": h, "adj_low": l, "adj_close": c,
                         "volume": rng.integers(1_000, 50_000, n).astype(float)},
                        index=pd.bdate_range("2018-01-01", periods=n))


@pytest.mark.parametrize("name", list(PER_TICKER))
def test_no_lookahead(name):
    """The value at bar t must not change when every later bar is removed."""
    df = _ohlcv()
    full = PER_TICKER[name](df)
    for k in (400, 520):
        cut = PER_TICKER[name](df.iloc[:k])
        a, b = full.iloc[k - 1], cut.iloc[k - 1]
        assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b), (name, k)


def test_bounded_indicators_stay_in_range():
    c = compute_candidates(_ohlcv())
    assert c["stoch_k_14"].dropna().between(0, 100).all()
    assert c["adx_14"].dropna().between(0, 100).all()
    assert c["cmf_20"].dropna().between(-1, 1).all()
    assert c["boll_bandwidth_20"].dropna().gt(0).all()
    assert c["days_since_52w_high"].dropna().between(0, 251).all()


def test_days_since_extremes_on_a_steady_climb():
    n = 300
    c = np.linspace(100, 200, n)
    df = pd.DataFrame({"adj_open": c, "adj_high": c, "adj_low": c, "adj_close": c,
                       "volume": 1000.0}, index=pd.bdate_range("2019-01-01", periods=n))
    out = compute_candidates(df)
    assert out["days_since_52w_high"].iloc[-1] == 0          # today is the high
    assert out["days_since_52w_low"].iloc[-1] == 251         # the low is the oldest bar in the window


def test_market_candidates_have_no_lookahead_and_handle_missing_vix():
    idx = pd.bdate_range("2018-01-01", periods=600)
    px = pd.Series(100 + np.arange(600) * 0.1, index=idx)
    vix = pd.Series(15 + np.sin(np.arange(600) / 20) * 5, index=idx)
    full = market_candidates(px, vix)
    cut = market_candidates(px.iloc[:450], vix.iloc[:450])
    assert full["vix_pct_252"].iloc[449] == pytest.approx(cut["vix_pct_252"].iloc[449])
    assert full["mkt_dist_sma200"].iloc[449] == pytest.approx(cut["mkt_dist_sma200"].iloc[449])
    assert "vix_pct_252" not in market_candidates(px, None).columns


def test_cross_sectional_rank_is_per_date():
    idx = pd.bdate_range("2020-01-01", periods=3)
    r = cross_sectional_rank({"A": pd.Series([1.0, 3.0, 2.0], index=idx),
                              "B": pd.Series([2.0, 2.0, 1.0], index=idx)})
    assert r.loc[idx[0], "A"] < r.loc[idx[0], "B"]
    assert r.loc[idx[1], "A"] > r.loc[idx[1], "B"]
