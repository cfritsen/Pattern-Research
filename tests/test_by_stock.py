import pandas as pd
from patternlab.by_stock import per_stock_breakdown


def test_below_min_n_keeps_row_but_nulls_stats():
    thin = pd.DataFrame({"ticker": ["AAA"] * 40 + ["BBB"] * 10,
                         "fwd_ret_5": [0.02] * 40 + [0.05] * 10,
                         "up_hit": [1.0] * 50})
    out = per_stock_breakdown(thin, 5, min_n=30)
    assert set(out.index) == {"AAA", "BBB"}
    assert out.loc["AAA", "n"] == 40 and out.loc["BBB", "n"] == 10
    assert pd.notna(out.loc["AAA", "mean"])
    assert pd.isna(out.loc["BBB", "mean"])
    assert pd.isna(out.loc["BBB", "hit_rate"]) and pd.isna(out.loc["BBB", "effect"])

def test_bearish_direction_uses_down_hit():
    import pandas as pd
    thin = pd.DataFrame({"ticker": ["A"] * 30, "fwd_ret_5": [-0.01] * 30,
                         "up_hit": [0.0] * 30, "down_hit": [1.0] * 30})
    assert per_stock_breakdown(thin, 5, min_n=30).loc["A", "hit_rate"] == 0.0
    assert per_stock_breakdown(thin, 5, min_n=30, direction=-1).loc["A", "hit_rate"] == 1.0
