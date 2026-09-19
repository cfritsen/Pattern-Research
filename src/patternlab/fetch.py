from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

COLS = ["open", "high", "low", "close", "adj_close", "volume"]


def _from_yfinance(ticker: str, start: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(ticker).history(start=start, auto_adjust=False, actions=False)
    if df.empty or "Adj Close" not in df.columns:
        raise ValueError(f"yfinance returned no usable data for {ticker}")
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Adj Close": "adj_close",
                            "Volume": "volume"})
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[COLS]


def _from_stooq(ticker: str, start: str) -> pd.DataFrame:
    # Best effort. Stooq is split-adjusted but NOT dividend-adjusted.
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    df = pd.read_csv(url, parse_dates=["Date"])
    if df.empty or "Close" not in df.columns:
        raise ValueError(f"Stooq returned no usable data for {ticker}")
    df = df.rename(columns=str.lower).set_index("date")
    df.index.name = None
    df["adj_close"] = df["close"]
    df = df.loc[df.index >= pd.Timestamp(start)]
    return df[COLS]


def _finalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="last")].sort_index().copy()
    df.index.name = "date"
    factor = df["adj_close"] / df["close"]          # dividend + split adjustment
    for c in ("open", "high", "low"):
        df[f"adj_{c}"] = df[c] * factor
    df["source"] = source
    return df


def get_prices(ticker: str, cfg: dict, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Return (dataframe, meta). Uses the parquet cache unless refresh=True."""
    raw_dir = Path(cfg["data_dir"]) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{ticker.replace('/', '_')}.parquet"

    if path.exists() and not refresh:
        df = pd.read_parquet(path)
        return df, _meta(df, fetched_at=None)

    errors = []
    df = None
    try:
        df = _finalize(_from_yfinance(ticker, cfg["start_date"]), "yfinance")
    except Exception as e:
        errors.append(f"yfinance: {e}")
        if cfg.get("use_stooq_fallback", True):
            try:
                df = _finalize(_from_stooq(ticker, cfg["start_date"]), "stooq")
            except Exception as e2:
                errors.append(f"stooq: {e2}")
    if df is None:
        raise RuntimeError(f"{ticker}: " + " | ".join(errors))

    df.to_parquet(path)
    return df, _meta(df, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _meta(df: pd.DataFrame, fetched_at: str | None) -> dict:
    return {
        "source": str(df["source"].iloc[-1]),
        "fetched_at": fetched_at,
        "rows": int(len(df)),
        "first": str(df.index[0].date()),
        "last": str(df.index[-1].date()),
        "last_adj_close": round(float(df["adj_close"].iloc[-1]), 4),
    }


def data_version(manifest: dict) -> str:
    """Short fingerprint of what's in the cache. Changes if any data changes."""
    core = {t: {k: v for k, v in m.items() if k != "fetched_at"}
            for t, m in sorted(manifest.items())}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:12]