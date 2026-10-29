from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from patternlab.fetch import get_prices

INDEX_INSIGHT_TICKERS = [
    ("S&P 500", "SPY"),
    ("Dow Jones", "DIA"),
    ("Nasdaq", "QQQ"),
    ("Russell 2000", "IWM"),
]

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_CLOSE_HOUR = 16  # 4:00 PM Eastern, regular session close


def _session_in_progress(now: datetime | None = None) -> bool:
    """True if a data row dated "today" could be a partial, mid-session
    price rather than a completed session's close. This is a research
    tool built on daily bars, not a live quote feed -- Market Insights
    should report the most recently COMPLETED session, never a number
    that's still moving.

    Doesn't account for market holidays or early-close days: a holiday
    has no new data row to begin with, so it's harmless here; an early
    close (e.g. the day after Thanksgiving) would be misjudged as still
    in progress until 4pm even though the session already settled --
    a known, minor limitation rather than a full holiday calendar.
    """
    now = now or datetime.now(MARKET_TZ)
    if now.weekday() >= 5:  # Saturday/Sunday -- no session to be "in progress"
        return False
    return now.hour < MARKET_CLOSE_HOUR


def _pct_change(valid_closes: pd.Series, bars_back: int):
    if len(valid_closes) <= bars_back:
        return None
    prior = valid_closes.iloc[-1 - bars_back]
    if prior == 0 or pd.isna(prior):
        return None
    return float(valid_closes.iloc[-1] / prior - 1)


def compute_market_insights(cfg: dict) -> dict:
    drop_today = _session_in_progress()
    today = datetime.now(MARKET_TZ).date()

    valid_by_ticker: dict[str, pd.Series] = {}
    for _, ticker in INDEX_INSIGHT_TICKERS:
        df, _ = get_prices(ticker, cfg, incremental=True)
        valid = df["adj_close"].dropna()
        # Today's session isn't over yet -- don't let a partial, still-moving
        # price masquerade as a completed bar.
        if drop_today and not valid.empty and valid.index[-1].date() == today:
            valid = valid.iloc[:-1]
        valid_by_ticker[ticker] = valid

    # The shared "as of" date is the EARLIEST of each ticker's own latest
    # valid date -- i.e. whichever ticker is most behind on adjustment
    # backfill sets the pace for all of them, so every card reports as of
    # the same date rather than silently mixing dates across the group.
    latest_dates = [v.index[-1] for v in valid_by_ticker.values() if not v.empty]
    if not latest_dates:
        return {"as_of": None, "indices": [
            {"label": label, "ticker": ticker, "day": None, "week": None, "month": None}
            for label, ticker in INDEX_INSIGHT_TICKERS]}
    common_as_of = min(latest_dates)

    results = []
    for label, ticker in INDEX_INSIGHT_TICKERS:
        aligned = valid_by_ticker[ticker]
        aligned = aligned[aligned.index <= common_as_of]
        results.append({
            "label": label, "ticker": ticker,
            "day": _pct_change(aligned, 1),
            "week": _pct_change(aligned, 5),
            "month": _pct_change(aligned, 21),
        })
    return {"as_of": str(common_as_of.date()), "indices": results}