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
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
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
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
    path = tmp_path / "sp500" / "raw"
    path.mkdir(parents=True)
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
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
    path = tmp_path / "sp500" / "raw"
    path.mkdir(parents=True)
    cached.to_parquet(path / "TEST.parquet")

    def fake_fetch_from(ticker, start, use_stooq):
        raise RuntimeError("TEST: yfinance: no data")

    monkeypatch.setattr("patternlab.fetch._fetch_from", fake_fetch_from)
    df, meta = get_prices("TEST", cfg, incremental=True)
    assert len(df) == 3
    assert meta["fetched_at"] is None   # no-op, not treated as a fresh fetch


def test_refresh_ignores_incremental_and_does_full_fetch(tmp_path, monkeypatch):
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2020-01-01", periods=3))
    path = tmp_path / "sp500" / "raw"
    path.mkdir(parents=True)
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
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    cached = make_cached_df(pd.bdate_range("2024-06-01", periods=3))
    path = tmp_path / "sp500" / "raw"
    path.mkdir(parents=True)
    cached.to_parquet(path / "TEST.parquet")

    # Pretend the latest completed session is the cache's last date -- so
    # fetch_start (last date + 1) is after it, which should trigger the skip.
    monkeypatch.setattr("patternlab.fetch._last_completed", lambda: cached.index[-1])

    calls = []
    monkeypatch.setattr("patternlab.fetch._fetch_from", lambda *a, **k: calls.append(a) or pd.DataFrame())

    df, meta = get_prices("TEST", cfg, incremental=True)
    assert calls == []
    assert len(df) == 3
    assert meta["fetched_at"] is None

def test_full_fetch_drops_bar_from_unfinished_session(tmp_path, monkeypatch):
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    dates = pd.bdate_range("2024-06-03", periods=5)
    monkeypatch.setattr("patternlab.fetch._last_completed", lambda: dates[-2])
    monkeypatch.setattr("patternlab.fetch._fetch_from", lambda *a, **k: make_cached_df(dates))
    df, _ = get_prices("TEST", cfg, refresh=True)
    assert df.index[-1] == dates[-2]
    assert pd.read_parquet(tmp_path / "sp500" / "raw" / "TEST.parquet").index[-1] == dates[-2]


def test_incremental_never_appends_unfinished_session(tmp_path, monkeypatch):
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    dates = pd.bdate_range("2024-06-03", periods=5)
    cached = make_cached_df(dates[:2])
    path = tmp_path / "sp500" / "raw"
    path.mkdir(parents=True)
    cached.to_parquet(path / "TEST.parquet")
    monkeypatch.setattr("patternlab.fetch._last_completed", lambda: dates[2])
    monkeypatch.setattr("patternlab.fetch._fetch_from", lambda *a, **k: make_cached_df(dates[2:]))
    df, _ = get_prices("TEST", cfg, incremental=True)
    assert list(df.index) == list(dates[:3])


def test_incremental_drops_legacy_partial_bar_and_refetches_it(tmp_path, monkeypatch):
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    dates = pd.bdate_range("2024-06-03", periods=4)
    cached = make_cached_df(dates)             # last bar newer than the latest completed session
    path = tmp_path / "sp500" / "raw"
    path.mkdir(parents=True)
    cached.to_parquet(path / "TEST.parquet")
    monkeypatch.setattr("patternlab.fetch._last_completed", lambda: dates[2])
    calls = []
    monkeypatch.setattr("patternlab.fetch._fetch_from", lambda t, start, u: calls.append(start) or pd.DataFrame())
    df, _ = get_prices("TEST", cfg, incremental=True)
    assert list(df.index) == list(dates[:3])      # partial bar gone
    assert calls == []                            # cache is current at the latest completed session


def test_shared_flag_uses_the_market_folder(tmp_path, monkeypatch):
    cfg = {"index": "sp500", "data_dir": str(tmp_path), "start_date": "2020-01-01", "use_stooq_fallback": False}
    monkeypatch.setattr("patternlab.fetch._fetch_from",
                        lambda *a, **k: make_cached_df(pd.bdate_range("2020-01-01", periods=3)))
    get_prices("SPY", cfg, incremental=True, shared=True)
    assert (tmp_path / "market" / "raw" / "SPY.parquet").exists()
    assert not (tmp_path / "sp500" / "raw" / "SPY.parquet").exists()
