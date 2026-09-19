from __future__ import annotations
import pandas as pd


def check_prices(ticker: str, df: pd.DataFrame, jump_threshold: float = 0.25) -> dict:
    gaps = df.index.to_series().diff().dt.days
    ret = df["adj_close"].pct_change()
    return {
        "ticker": ticker,
        "status": "fetched",
        "source": df["source"].iloc[-1],
        "first": df.index[0].date(),
        "last": df.index[-1].date(),
        "rows": len(df),
        "gaps_over_5d": int((gaps > 5).sum()),
        "longest_gap_days": int(gaps.max()) if len(df) > 1 else 0,
        "jumps_over_threshold": int((ret.abs() > jump_threshold).sum()),
        "zero_volume_bars": int((df["volume"] == 0).sum()),
        "nonpositive_prices": int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "high_below_low": int((df["high"] < df["low"]).sum()),
    }


def failed_row(ticker: str, status: str, note: str = "") -> dict:
    return {"ticker": ticker, "status": status, "note": note}