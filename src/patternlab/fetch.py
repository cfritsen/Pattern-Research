from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

COLS = ["open", "high", "low", "close", "adj_close", "volume"]


def _today() -> pd.Timestamp:
    """Separated out so tests can monkeypatch 'now' without touching real time."""
    return pd.Timestamp.now().normalize()


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


def _fetch_from(ticker: str, start: str, use_stooq_fallback: bool) -> pd.DataFrame:
    errors = []
    try:
        return _finalize(_from_yfinance(ticker, start), "yfinance")
    except Exception as e:
        errors.append(f"yfinance: {e}")
        if use_stooq_fallback:
            try:
                return _finalize(_from_stooq(ticker, start), "stooq")
            except Exception as e2:
                errors.append(f"stooq: {e2}")
    raise RuntimeError(f"{ticker}: " + " | ".join(errors))


def get_prices(ticker: str, cfg: dict, refresh: bool = False, incremental: bool = False) -> tuple[pd.DataFrame, dict]:
    """Return (dataframe, meta).

    refresh=False, incremental=False (default): use the parquet cache as-is
        if it exists; otherwise fetch full history.
    refresh=True: ignore the cache and fetch the ticker's full history fresh
        -- this is also what re-derives dividend/split adjustment correctly
        across the whole series (see "Full Discovery" in the spec).
    incremental=True: fetch only bars after the cache's last date and append
        them -- cheap, but does NOT re-derive adjustment for bars already in
        the cache, so a dividend/split since the last fetch can leave old
        cached bars' adj_close slightly stale until the next refresh=True
        run. This is "Fetch New" -- bounded, accepted drift, per the spec.
        If no cache exists yet, behaves exactly like a full fetch. If the
        cache is already current (its last bar is today or later), no
        network call is made at all -- asking yfinance for a future start
        date doesn't error locally, it round-trips to the server first and
        THEN errors, which is slow and noisy across hundreds of tickers.
    refresh and incremental are mutually exclusive; refresh wins if both are
    somehow passed True.
    """
    raw_dir = Path(cfg["data_dir"]) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{ticker.replace('/', '_')}.parquet"
    use_stooq = cfg.get("use_stooq_fallback", True)

    if path.exists() and not refresh and not incremental:
        df = pd.read_parquet(path)
        return df, _meta(df, fetched_at=None)

    if path.exists() and incremental and not refresh:
        cached = pd.read_parquet(path)
        last_cached_date = cached.index[-1]
        fetch_start_ts = last_cached_date + pd.Timedelta(days=1)

        if fetch_start_ts > _today():
            # Cache already includes a bar dated today or later -- nothing
            # could possibly be newer yet. Skip the network call entirely.
            return cached, _meta(cached, fetched_at=None)

        fetch_start = fetch_start_ts.strftime("%Y-%m-%d")
        try:
            new_df = _fetch_from(ticker, fetch_start, use_stooq)
        except RuntimeError:
            # A genuine fetch error on a legitimately-due date. Treat as a
            # no-op rather than failing the whole run -- the next scheduled
            # fetch will try again.
            return cached, _meta(cached, fetched_at=None)
        if new_df.empty:
            return cached, _meta(cached, fetched_at=None)
        combined = pd.concat([cached, new_df])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        combined.to_parquet(path)
        return combined, _meta(combined, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # refresh=True, or no cache exists at all: full fetch from cfg's start_date.
    df = _fetch_from(ticker, cfg["start_date"], use_stooq)
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