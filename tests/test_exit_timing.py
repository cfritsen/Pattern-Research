import pandas as pd
from patternlab.exit_timing import exit_day_mask


def test_marks_first_false_after_a_run():
    cond = pd.Series([True, True, True, False, False, True, False])
    ticker = pd.Series(["A"] * 7)
    bar_pos = pd.Series(range(7))
    mask = exit_day_mask(cond, ticker, bar_pos)
    assert mask.tolist() == [False, False, False, True, False, False, True]


def test_run_still_true_at_end_has_no_exit():
    cond = pd.Series([False, True, True, True])
    ticker = pd.Series(["A"] * 4)
    bar_pos = pd.Series(range(4))
    mask = exit_day_mask(cond, ticker, bar_pos)
    assert mask.tolist() == [False, False, False, False]


def test_separate_per_ticker():
    cond = pd.Series([True, False, True, False])
    ticker = pd.Series(["A", "A", "B", "B"])
    bar_pos = pd.Series([0, 1, 0, 1])
    mask = exit_day_mask(cond, ticker, bar_pos)
    assert mask.tolist() == [False, True, False, True]