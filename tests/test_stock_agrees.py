import pandas as pd
from patternlab.watchlist import stock_agrees


def row(eff):
    return pd.Series({"effect_all": eff, "effect_flagged": eff,
                      "baseline_mean_all": 0.004, "baseline_mean_flagged": 0.004})


def test_bullish_pattern_negative_stock_filtered():
    assert not stock_agrees({"mean_fwd_return": -0.004}, row(0.01), "all")


def test_bearish_pattern_positive_stock_filtered():
    assert not stock_agrees({"mean_fwd_return": 0.002}, row(-0.01), "flagged")


def test_agreeing_and_no_stock_stats_kept():
    assert stock_agrees({"mean_fwd_return": 0.01}, row(0.01), "all")
    assert stock_agrees({"mean_fwd_return": -0.01}, row(-0.01), "all")
    assert stock_agrees(None, row(-0.01), "all")


def test_stock_edge_within_cost_is_hidden():
    # stock mean 0.45% vs baseline 0.4%: Edge 0.05%, cost 0.1% -> hidden
    assert not stock_agrees({"mean_fwd_return": 0.0045}, row(0.01), "all", cost=0.001)
    assert stock_agrees({"mean_fwd_return": 0.0045}, row(0.01), "all", cost=0.0)
    # bearish: stock mean -1% vs baseline 0.4% -> |edge| 1.4% clears the cost
    assert stock_agrees({"mean_fwd_return": -0.01}, row(-0.01), "all", cost=0.001)
