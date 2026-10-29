from datetime import datetime
import pandas as pd
import pytest
from patternlab.market_insights import (
    classify_vix_regime, classify_term_structure, compute_vix_card, _session_in_progress, MARKET_TZ,
    VIX_CLOSE_MINUTES)


@pytest.mark.parametrize("level,prior,expected", [
    (12.0, 12.0, "Calm"),
    (15.0, 15.0, "Normal"),
    (19.9, 19.9, "Normal"),
    (22.0, 21.0, "Elevated"),     # elevated and steady
    (22.0, 16.0, "Surging"),      # elevated and well above recent average
    (22.0, None, "Elevated"),     # not enough history to call a surge
    (18.0, 10.0, "Normal"),       # big jump, but not elevated yet -> not "Surging"
    (35.0, 34.0, "Stressed"),
    (35.0, 20.0, "Stressed"),     # Stressed overrides Surging
])
def test_regime(level, prior, expected):
    assert classify_vix_regime(level, prior) == expected


def test_vix_card_percentiles_and_regime():
    s = pd.Series(range(1, 301), dtype=float)       # latest value is the max
    card = compute_vix_card(s)
    assert card["week52_pct"] == 1.0
    assert card["level"] == 300.0 and card["regime"] == "Stressed"


def test_vix_card_52_week_needs_a_full_year():
    card = compute_vix_card(pd.Series([14.0] * 100))
    assert card["week52_pct"] is None
    assert card["regime"] == "Calm"


def test_vix_card_empty():
    assert compute_vix_card(pd.Series([], dtype=float))["regime"] is None


def test_vix_cutoff_is_415_not_400():
    at = lambda h, m: datetime(2026, 10, 29, h, m, tzinfo=MARKET_TZ)   # a Thursday
    assert not _session_in_progress(at(16, 5))                          # ETFs: session done at 4:00
    assert _session_in_progress(at(16, 5), VIX_CLOSE_MINUTES)           # VIX: still in progress
    assert not _session_in_progress(at(16, 20), VIX_CLOSE_MINUTES)


def test_term_structure_labels():
    assert classify_term_structure(16.0, 19.0) == "Normal"      # usual: 3-month above 1-month
    assert classify_term_structure(25.0, 22.0) == "Inverted"
    assert classify_term_structure(20.0, 20.0) == "Inverted"    # equal counts as inverted
    assert classify_term_structure(16.0, None) is None
    assert classify_term_structure(16.0, 0.0) is None


def test_vix_card_term_structure_needs_matching_date():
    idx = pd.bdate_range("2026-10-20", periods=5)
    vix = pd.Series([18, 18, 18, 18, 24.0], index=idx)
    same_day = pd.Series([20, 20, 20, 20, 21.0], index=idx)
    assert compute_vix_card(vix, same_day)["term_structure"] == "Inverted"
    stale = same_day.iloc[:-1]                                   # no reading for VIX's latest date
    assert compute_vix_card(vix, stale)["term_structure"] is None
    assert compute_vix_card(vix)["term_structure"] is None
