from datetime import date
import pandas as pd
from patternlab.clean import clean_prices

TODAY = date(2030, 1, 1)


def make(n):
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"volume": 1000, "adj_close": 1.0}, index=idx)


def test_trims_zero_volume_prehistory():
    df = make(300)
    df.iloc[:100, df.columns.get_loc("volume")] = 0
    out, notes = clean_prices(df, today=TODAY)
    assert notes["trimmed_prehistory"] == 100
    assert (out["volume"] > 0).all()


def test_sparse_zero_volume_is_kept():
    df = make(300)
    df.iloc[[50, 150, 250], df.columns.get_loc("volume")] = 0
    out, notes = clean_prices(df, today=TODAY)
    assert notes["trimmed_prehistory"] == 0
    assert len(out) == 300


def test_drops_incomplete_today_bar():
    df = make(10)
    last = df.index[-1].date()
    out, notes = clean_prices(df, today=last)
    assert notes["dropped_today"] == 1
    assert out.index[-1] < pd.Timestamp(last)


def test_start_override():
    out, _ = clean_prices(make(100), today=TODAY, start="2020-03-01")
    assert out.index[0] >= pd.Timestamp("2020-03-01")


def test_thin_trading_is_kept():
    df = make(300)
    df.iloc[:100:4, df.columns.get_loc("volume")] = 0   # ~25% zeros
    out, notes = clean_prices(df, today=TODAY)
    assert notes["trimmed_prehistory"] == 0    