import numpy as np
import pandas as pd

from patternlab.db import connect
from patternlab.stock_baselines import (compute_stock_baselines, ensure_stock_baselines,
                                        load_stock_baselines, MIN_BASELINE_DAYS)
from patternlab.watchlist import stock_agrees, stock_edge


def _setup(tmp_path, days=400):
    cfg = {"data_dir": str(tmp_path), "index": "sp500", "horizon": 5}
    out = tmp_path / "sp500" / "outcomes"
    out.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-01", periods=days)
    # AAA drifts +1% per 5 days on every day, BBB only +0.2%, SHORT has too little history
    pd.DataFrame({"fwd_ret_5": 0.01, "tradable": True}, index=dates).to_parquet(out / "AAA.parquet")
    pd.DataFrame({"fwd_ret_5": 0.002, "tradable": True}, index=dates).to_parquet(out / "BBB.parquet")
    pd.DataFrame({"fwd_ret_5": 0.05, "tradable": True}, index=dates[:50]).to_parquet(out / "SHORT.parquet")
    uni = pd.DataFrame({"data_ticker": ["AAA", "BBB", "SHORT"],
                        "date_added": [pd.NaT, dates[200], pd.NaT]})
    return cfg, uni, dates


def test_each_stock_gets_its_own_baseline(tmp_path):
    cfg, uni, dates = _setup(tmp_path)
    df = compute_stock_baselines(cfg, uni, 5).set_index(["ticker", "view"])
    assert abs(df.loc[("AAA", "all"), "mean_fwd_return"] - 0.01) < 1e-12
    assert abs(df.loc[("BBB", "all"), "mean_fwd_return"] - 0.002) < 1e-12
    assert df.loc[("BBB", "flagged"), "n"] == 400 - 200            # only days since it joined the index
    assert pd.isna(df.loc[("SHORT", "all"), "mean_fwd_return"])    # under MIN_BASELINE_DAYS days


def test_ensure_builds_once_and_rebuilds_when_outcomes_change(tmp_path):
    cfg, uni, dates = _setup(tmp_path)
    conn = connect(cfg)
    ensure_stock_baselines(cfg, uni, conn)
    got = load_stock_baselines(conn)
    assert ("AAA", "all") in got and ("SHORT", "all") not in got
    assert abs(load_stock_baselines(conn, "BBB")[("BBB", "all")] - 0.002) < 1e-12

    # a newer outcome file triggers a rebuild
    import os, time
    p = tmp_path / "sp500" / "outcomes" / "BBB.parquet"
    pd.DataFrame({"fwd_ret_5": 0.004, "tradable": True}, index=dates).to_parquet(p)
    os.utime(p, (time.time() + 10, time.time() + 10))
    ensure_stock_baselines(cfg, uni, conn)
    assert abs(load_stock_baselines(conn, "BBB")[("BBB", "all")] - 0.004) < 1e-12


def test_edge_and_agreement_use_the_stocks_own_baseline():
    prow = pd.Series({"effect_all": 0.01, "baseline_mean_all": 0.004})
    # stock mean 1.0%: against the market's 0.4% it clears a 0.3% cost, against its own 0.9% baseline it does not
    assert stock_agrees({"mean_fwd_return": 0.01, "baseline": None}, prow, "all", 0.003)
    assert not stock_agrees({"mean_fwd_return": 0.01, "baseline": 0.009}, prow, "all", 0.003)
    assert abs(stock_edge({"mean_fwd_return": 0.01, "baseline": 0.002}, prow, "all", 0.001) - 0.007) < 1e-12
    assert abs(stock_edge({"mean_fwd_return": 0.01, "baseline": None}, prow, "all", 0.001) - 0.005) < 1e-12
