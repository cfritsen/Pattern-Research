import pandas as pd
import pytest
from patternlab.fetch import get_prices, COLS


def make_cached_df(dates):
    df = pd.DataFrame({c: 1.0 for c in COLS[:-1]}, index=pd.DatetimeIndex(dates, name="date"))
    df["source"] = "yfinance"
    for c in ("adj_open", "adj_high", "adj_low"):
        df[c] = 1.0
    return df


def test_incremental_with_no_cache_does_a_full_fetch(tmp_path, monkeypatch):
    cfg = {"data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    calls = []

    def fake_fetch_from(ticker, start, use_stooq):
        calls.append(("full", start))
        df = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
        return df

    monkeypatch.setattr("patternlab.fetch._fetch_from", fake_fetch_from)
    df, meta = get_prices("TEST", cfg, incremental=True)
    assert calls == [("full", "2020-01-01")]
    assert len(df) == 3


def test_incremental_with_cache_only_fetches_new_bars(tmp_path, monkeypatch):
    cfg = {"data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
    path = tmp_path / "raw"
    path.mkdir()
    cached.to_parquet(path / "TEST.parquet")

    calls = []

    def fake_fetch_from(ticker, start, use_stooq):
        calls.append(start)
        return make_cached_df(pd.bdate_range("2020-01-06", periods=2))   # next business days

    monkeypatch.setattr("patternlab.fetch._fetch_from", fake_fetch_from)
    df, meta = get_prices("TEST", cfg, incremental=True)
    assert calls[0] == cached.index[-1].strftime("%Y-%m-%d").replace(
        cached.index[-1].strftime("%Y-%m-%d"), calls[0])  # start date is after last cached date
    assert len(df) == 5   # 3 cached + 2 new, no duplicates


def test_incremental_with_no_new_bars_returns_cache_unchanged(tmp_path, monkeypatch):
    cfg = {"data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
    path = tmp_path / "raw"
    path.mkdir()
    cached.to_parquet(path / "TEST.parquet")

    def fake_fetch_from(ticker, start, use_stooq):
        raise RuntimeError("TEST: yfinance: no data")

    monkeypatch.setattr("patternlab.fetch._fetch_from", fake_fetch_from)
    df, meta = get_prices("TEST", cfg, incremental=True)
    assert len(df) == 3
    assert meta["fetched_at"] is None   # no-op, not treated as a fresh fetch


def test_refresh_ignores_incremental_and_does_full_fetch(tmp_path, monkeypatch):
    cfg = {"data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
    path = tmp_path / "raw"
    path.mkdir()
    cached.to_parquet(path / "TEST.parquet")

    calls = []

    def fake_fetch_from(ticker, start, use_stooq):
        calls.append(start)
        return make_cached_df(pd.bdate_range("2020-01-01", periods=10))

    monkeypatch.setattr("patternlab.fetch._fetch_from", fake_fetch_from)
    df, meta = get_prices("TEST", cfg, refresh=True, incremental=True)
    assert calls == ["2020-01-01"]   # full start_date, not the cache's last date
    assert len(df) == 10


def test_incremental_skips_network_call_when_cache_already_current(tmp_path, monkeypatch):
    cfg = {"data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2024-06-01", periods=3))
    path = tmp_path / "raw"
    path.mkdir()
    cached.to_parquet(path / "TEST.parquet")

    # Pretend "now" is exactly the cache's last date -- so fetch_start
    # (last date + 1) is tomorrow, which should trigger the skip.
    monkeypatch.setattr("patternlab.fetch._today", lambda: cached.index[-1])

    calls = []
    monkeypatch.setattr("patternlab.fetch._fetch_from", lambda *a, **k: calls.append(a) or pd.DataFrame())

    df, meta = get_prices("TEST", cfg, incremental=True)
    assert calls == []
    assert len(df) == 3
    assert meta["fetched_at"] is None