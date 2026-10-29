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

# VIX is the one non-ETF card. Its daily value is finalized a little after
# the stock market closes (S&P 500 options trade until 4:15 PM Eastern), so
# its "session still in progress" cutoff is later than the ETFs'.
VIX_TICKER = "^VIX"
VIX3M_TICKER = "^VIX3M"   # 3-month VIX, for the term-structure reading
VIX_CLOSE_MINUTES = 16 * 60 + 15

# Regime bands (conventional VIX levels -- descriptive labels, not advice).
VIX_CALM_BELOW = 15
VIX_NORMAL_BELOW = 20
VIX_STRESSED_AT = 30
# "Surging" = already Elevated AND today's close is at least this multiple
# of the average of the 20 closes before it.
VIX_SURGE_RATIO = 1.25
VIX_SURGE_LOOKBACK = 20
VIX_YEAR_BARS = 252


def _session_in_progress(now: datetime | None = None,
                         close_minutes: int = MARKET_CLOSE_HOUR * 60) -> bool:
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
    return now.hour * 60 + now.minute < close_minutes


def _pct_change(valid_closes: pd.Series, bars_back: int):
    if len(valid_closes) <= bars_back:
        return None
    prior = valid_closes.iloc[-1 - bars_back]
    if prior == 0 or pd.isna(prior):
        return None
    return float(valid_closes.iloc[-1] / prior - 1)


def classify_vix_regime(level: float, prior_avg: float | None) -> str:
    """Calm / Normal / Elevated / Surging / Stressed. Surging is Elevated
    plus a spike versus the recent average; Stressed overrides everything."""
    if level >= VIX_STRESSED_AT:
        return "Stressed"
    if level >= VIX_NORMAL_BELOW:
        if prior_avg and level >= VIX_SURGE_RATIO * prior_avg:
            return "Surging"
        return "Elevated"
    if level >= VIX_CALM_BELOW:
        return "Normal"
    return "Calm"


def _percentile_of_last(series: pd.Series, window: int | None = None):
    """Fraction of values (within the last `window`, or all) at or below the
    latest value. None if a full window isn't available yet."""
    if window is not None:
        if len(series) < window:
            return None
        series = series.iloc[-window:]
    if series.empty:
        return None
    return float((series <= series.iloc[-1]).mean())


def classify_term_structure(vix: float, vix3m: float | None) -> str | None:
    """'Inverted' when the 1-month VIX is at or above the 3-month VIX (the
    market is more worried about the near term than the longer term -- a
    classic stress signal); otherwise 'Normal'. None if no 3-month reading."""
    if vix3m is None or vix3m <= 0:
        return None
    return "Inverted" if vix >= vix3m else "Normal"


def compute_vix_card(valid: pd.Series, vix3m_valid: pd.Series | None = None) -> dict:
    """valid: VIX closes up to and including the shared as-of date.
    vix3m_valid: 3-month VIX closes, optional. Its value is used only if it
    exists for the SAME date as VIX's latest close -- never a stale one."""
    if valid.empty:
        return {"level": None, "regime": None, "term_structure": None, "week52_pct": None}
    level = float(valid.iloc[-1])
    vix3m = None
    if vix3m_valid is not None and valid.index[-1] in vix3m_valid.index:
        vix3m = float(vix3m_valid.loc[valid.index[-1]])
    prior = valid.iloc[-1 - VIX_SURGE_LOOKBACK:-1]
    prior_avg = float(prior.mean()) if len(prior) == VIX_SURGE_LOOKBACK else None
    return {
        "level": level,
        "regime": classify_vix_regime(level, prior_avg),
        "term_structure": classify_term_structure(level, vix3m),
        "week52_pct": _percentile_of_last(valid, VIX_YEAR_BARS),
    }


def _load_vol_series(cfg: dict, ticker: str, today, close_minutes: int):
    """Closes for a volatility index, dropping an unfinished 'today' bar.
    Returns None on any failure so these extras never break the page."""
    try:
        df, _ = get_prices(ticker, cfg, incremental=True)
        s = df["adj_close"].dropna()
        if (_session_in_progress(close_minutes=close_minutes) and not s.empty
                and s.index[-1].date() == today):
            s = s.iloc[:-1]
        return s
    except Exception:
        return None


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

    # VIX is fetched separately: a failure there must never take down the
    # four index cards.
    vix_valid = _load_vol_series(cfg, VIX_TICKER, today, VIX_CLOSE_MINUTES)
    vix3m_valid = _load_vol_series(cfg, VIX3M_TICKER, today, VIX_CLOSE_MINUTES)

    # The shared "as of" date is the EARLIEST of each ticker's own latest
    # valid date -- i.e. whichever ticker is most behind on adjustment
    # backfill sets the pace for all of them, so every card reports as of
    # the same date rather than silently mixing dates across the group.
    latest_dates = [v.index[-1] for v in valid_by_ticker.values() if not v.empty]
    if vix_valid is not None and not vix_valid.empty:
        latest_dates.append(vix_valid.index[-1])
    if not latest_dates:
        return {"as_of": None, "vix": None, "indices": [
            {"label": label, "ticker": ticker, "day": None, "month": None, "year": None}
            for label, ticker in INDEX_INSIGHT_TICKERS]}
    common_as_of = min(latest_dates)

    results = []
    for label, ticker in INDEX_INSIGHT_TICKERS:
        aligned = valid_by_ticker[ticker]
        aligned = aligned[aligned.index <= common_as_of]
        results.append({
            "label": label, "ticker": ticker,
            "day": _pct_change(aligned, 1),
            "month": _pct_change(aligned, 21),
            "year": _pct_change(aligned, 252),
        })
    vix_card = None
    if vix_valid is not None and not vix_valid.empty:
        vix_card = compute_vix_card(
            vix_valid[vix_valid.index <= common_as_of],
            None if vix3m_valid is None else vix3m_valid[vix3m_valid.index <= common_as_of])
    return {"as_of": str(common_as_of.date()), "indices": results, "vix": vix_card}