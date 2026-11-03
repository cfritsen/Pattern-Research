from datetime import date, datetime

import pandas as pd

from patternlab.session import MARKET_TZ, last_completed_session_date, drop_incomplete


def at(y, mo, d, h, m):
    return datetime(y, mo, d, h, m, tzinfo=MARKET_TZ)


def test_weekday_before_415_is_previous_weekday():
    assert last_completed_session_date(at(2026, 11, 3, 10, 0)) == date(2026, 11, 2)   # Tue morning -> Mon


def test_weekday_at_400_is_not_yet_complete():
    assert last_completed_session_date(at(2026, 11, 2, 16, 0)) == date(2026, 10, 30)  # Mon 4:00 -> Fri
    assert last_completed_session_date(at(2026, 11, 2, 16, 14)) == date(2026, 10, 30)


def test_weekday_at_415_is_complete():
    assert last_completed_session_date(at(2026, 11, 2, 16, 15)) == date(2026, 11, 2)
    assert last_completed_session_date(at(2026, 11, 2, 21, 50)) == date(2026, 11, 2)


def test_monday_morning_and_weekend_resolve_to_friday():
    assert last_completed_session_date(at(2026, 11, 2, 9, 0)) == date(2026, 10, 30)
    assert last_completed_session_date(at(2026, 11, 1, 12, 0)) == date(2026, 10, 30)  # Sunday
    assert last_completed_session_date(at(2026, 10, 31, 20, 0)) == date(2026, 10, 30)  # Saturday


def test_other_timezone_is_converted_to_eastern():
    # 9:50 PM Pacific on Mon Nov 2 is 12:50 AM Eastern Tue Nov 3 -> Monday is complete.
    from zoneinfo import ZoneInfo
    pt = datetime(2026, 11, 2, 21, 50, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert last_completed_session_date(pt) == date(2026, 11, 2)
    # 12:30 PM Pacific on Mon is 3:30 PM Eastern -> Monday not complete yet.
    pt = datetime(2026, 11, 2, 12, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert last_completed_session_date(pt) == date(2026, 10, 30)


def test_naive_now_is_read_as_eastern():
    assert last_completed_session_date(datetime(2026, 11, 2, 17, 0)) == date(2026, 11, 2)


def test_drop_incomplete_removes_only_newer_bars():
    df = pd.DataFrame({"x": 1}, index=pd.to_datetime(["2026-10-29", "2026-10-30", "2026-11-02"]))
    out = drop_incomplete(df, at(2026, 11, 2, 13, 0))
    assert list(out.index) == list(pd.to_datetime(["2026-10-29", "2026-10-30"]))
    out = drop_incomplete(df, at(2026, 11, 2, 16, 20))
    assert len(out) == 3
