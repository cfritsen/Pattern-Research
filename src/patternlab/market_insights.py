from __future__ import annotations
import pandas as pd
from patternlab.fetch import get_prices

INDEX_INSIGHT_TICKERS = [
    ("S&P 500", "SPY"),
    ("Dow Jones", "DIA"),
    ("Nasdaq", "QQQ"),
    ("Russell 2000", "IWM"),
]


def _pct_change(valid_closes: pd.Series, bars_back: int):
    if len(valid_closes) <= bars_back:
        return None
    prior = valid_closes.iloc[-1 - bars_back]
    if prior == 0 or pd.isna(prior):
        return None
    return float(valid_closes.iloc[-1] / prior - 1)


def compute_market_insights(cfg: dict) -> dict:
    valid_by_ticker: dict[str, pd.Series] = {}
    for _, ticker in INDEX_INSIGHT_TICKERS:
        df, _ = get_prices(ticker, cfg, incremental=True)
        valid_by_ticker[ticker] = df["adj_close"].dropna()

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