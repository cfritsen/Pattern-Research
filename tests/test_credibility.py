import numpy as np
import pandas as pd

from patternlab.reports import return_matches_edge, direction_ok, passes_direction_filter


def row(ret, effect, confirm=None, baseline=0.004):
    """A context row with both views filled the same way."""
    d = {}
    for v in ("all", "flagged"):
        d[f"mean_fwd_return_{v}"] = ret
        d[f"effect_{v}"] = effect
        d[f"baseline_mean_{v}"] = baseline
        d[f"confirm_mean_fwd_return_{v}"] = np.nan if confirm is None else confirm
    return pd.Series(d)


def test_return_and_edge_agree():
    assert return_matches_edge(0.012, 0.008)        # bullish: rose, and more than the market
    assert return_matches_edge(-0.006, -0.010)      # bearish: fell, and more than the market


def test_small_positive_return_with_negative_edge_is_filtered():
    # rose 0.1% while the market averaged 0.4%: Edge -0.3%. Not a credible result either way.
    assert not return_matches_edge(0.001, -0.003)


def test_small_negative_return_with_positive_edge_is_filtered():
    # possible only when the baseline is negative: fell 0.1% while the market fell 0.4%
    assert not return_matches_edge(-0.001, 0.003)


def test_missing_values_do_not_filter():
    assert return_matches_edge(np.nan, 0.01) and return_matches_edge(0.01, np.nan)


def test_direction_ok_and_watchlist_filter_use_the_rule():
    bad = row(0.001, -0.003, confirm=0.0005)
    assert not direction_ok(bad, "all") and not passes_direction_filter(bad)
    good = row(0.012, 0.008, confirm=0.010)
    assert direction_ok(good, "all") and passes_direction_filter(good)
    bearish = row(-0.006, -0.010, confirm=-0.008)
    assert direction_ok(bearish, "all") and passes_direction_filter(bearish)
