import sqlite3
import pandas as pd
from patternlab.config import cost_for, validate_config, ConfigError
from patternlab.reports import net_edge


def test_cost_for_defaults_and_overrides():
    assert cost_for({"index": "sp500"}) == 0.001
    assert cost_for({"index": "sp400"}) == 0.002
    assert cost_for({"index": "sp600"}) == 0.003
    assert cost_for({"index": "sp600", "index_costs": {"sp600": 0.005}}) == 0.005
    assert cost_for({"index": "other", "cost": 0.0007}) == 0.0007


def test_net_return_costs_a_long_and_credits_a_short():
    from patternlab.reports import net_return
    assert abs(net_return(0.01, 0.006, 0.001) - 0.009) < 1e-12      # bullish: Return - cost
    assert abs(net_return(-0.01, -0.014, 0.001) - (-0.009)) < 1e-12  # bearish: fall shrinks by the cost
    assert net_return(0.01, float("nan"), 0.001) == 0.01            # no direction: unchanged


def test_net_edge_keeps_sign_and_never_crosses_zero():
    assert abs(net_edge(0.01, 0.001) - 0.009) < 1e-12
    assert abs(net_edge(-0.01, 0.001) - (-0.009)) < 1e-12
    assert net_edge(0.0005, 0.001) == 0.0
    assert net_edge(float("nan"), 0.001) != net_edge(float("nan"), 0.001)   # NaN stays NaN


def test_index_costs_validated():
    import pytest
    from patternlab.config import validate_config
    base = {"index_costs": {"sp500": -1}}
    with pytest.raises(ConfigError):
        validate_config(base)


def test_per_stock_view_hides_edges_within_cost(tmp_path):
    from patternlab.db import connect, insert_run, get_or_create_pattern
    from patternlab.reports import stock_view
    conn = connect({"data_dir": str(tmp_path), "index": "sp500"})
    run = insert_run(conn, {"horizon": 5}, "v", "snap")
    pid = get_or_create_pattern(conn, "x in bucket 0", [{"feature": "x", "bucket": 0}])
    for view, mean in (("all", 0.0125), ("flagged", 0.0045)):    # baseline 0.4% -> Edge 0.85% / 0.05%
        conn.execute("INSERT INTO pattern_results_by_stock (pattern_id, run_id, ticker, view, horizon, split, n, "
                     "mean_fwd_return, hit_rate, effect) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (pid, run, "AAA", view, 5, "full", 40, mean, 0.5, 0.0))
    conn.commit()
    ctx = pd.DataFrame({"description": ["x in bucket 0"], "baseline_mean_all": [0.004],
                        "baseline_mean_flagged": [0.004], "best_single_all": [None], "best_single_flagged": [None],
                        "overlap_ratio": [1.0], "top3_year_share": [0.2], "mean_excl_top3": [0.01],
                        "reference_mean": [0.01]}, index=[pid])
    out = stock_view(conn, "AAA", ctx, 10, cost=0.001)
    r = out.iloc[0]
    assert abs(r["edge_all"] - 0.0075) < 1e-9          # 0.85% net of 0.1%
    assert abs(r["mean_fwd_return_all"] - 0.0115) < 1e-9                              # 1.25% - 0.1% cost
    assert abs((r["mean_fwd_return_all"] - r["baseline_mean_all"]) - r["edge_all"]) < 1e-9
    assert pd.isna(r["edge_flagged"]) and pd.isna(r["mean_fwd_return_flagged"])   # 0.05% <= cost: hidden
    assert len(stock_view(conn, "AAA", ctx, 10, cost=0.02)) == 0                  # nothing clears 2%


def test_per_stock_view_uses_the_stocks_own_baseline(tmp_path):
    from patternlab.db import connect, insert_run, get_or_create_pattern
    from patternlab.reports import stock_view
    conn = connect({"data_dir": str(tmp_path), "index": "sp500"})
    run = insert_run(conn, {"horizon": 5}, "v", "snap")
    pid = get_or_create_pattern(conn, "x in bucket 0", [{"feature": "x", "bucket": 0}])
    for view in ("all", "flagged"):
        conn.execute("INSERT INTO pattern_results_by_stock (pattern_id, run_id, ticker, view, horizon, split, n, "
                     "mean_fwd_return, hit_rate, effect) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (pid, run, "AAA", view, 5, "full", 40, 0.0125, 0.5, 0.0))
    conn.execute("INSERT INTO stock_baselines VALUES ('AAA','all',5,500,0.010,1.0)")    # drifts up anyway
    conn.commit()                                                                          # no row for 'flagged'
    ctx = pd.DataFrame({"description": ["x in bucket 0"], "baseline_mean_all": [0.004],
                        "baseline_mean_flagged": [0.004], "best_single_all": [None], "best_single_flagged": [None],
                        "overlap_ratio": [1.0], "top3_year_share": [0.2], "mean_excl_top3": [0.01],
                        "reference_mean": [0.01]}, index=[pid])
    r = stock_view(conn, "AAA", ctx, 10, cost=0.001).iloc[0]
    assert abs(r["baseline_mean_all"] - 0.010) < 1e-12 and abs(r["edge_all"] - (0.0125 - 0.010 - 0.001)) < 1e-9
    assert abs(r["baseline_mean_flagged"] - 0.004) < 1e-12        # no own baseline: falls back to the market's
