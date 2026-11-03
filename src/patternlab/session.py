"""One definition of "a completed trading session", shared by fetching,
cleaning and Market Insights.

A session counts as complete from 4:15 PM America/New_York on a weekday (the
15 minutes after the 4:00 close cover VIX and late prints). Before that, or on
a weekend, the latest complete session is the previous weekday.

There is no holiday calendar. A holiday has no bar, so nothing needs
dropping; an early-close day is not treated as complete until 4:15 PM
Eastern (accepted limitation).
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

MARKET_TZ = ZoneInfo("America/New_York")
COMPLETE_MINUTES = 16 * 60 + 15


def last_completed_session_date(now: datetime | None = None) -> date:
    """Date of the most recent session that has finished. `now` defaults to the
    current time; a naive `now` is read as Eastern time."""
    if now is None:
        now = datetime.now(MARKET_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=MARKET_TZ)
    else:
        now = now.astimezone(MARKET_TZ)
    d = now.date()
    if now.weekday() < 5 and now.hour * 60 + now.minute >= COMPLETE_MINUTES:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def drop_incomplete(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Rows dated after the latest completed session removed."""
    return df.loc[df.index <= pd.Timestamp(last_completed_session_date(now))]
