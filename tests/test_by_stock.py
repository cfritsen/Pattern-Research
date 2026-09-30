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