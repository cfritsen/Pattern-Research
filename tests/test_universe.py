import pandas as pd
import pytest
from patternlab.universe import in_index_flag
from patternlab.universe_fetch import to_data_ticker, validate_snapshot


def test_flag_starts_on_add_date():
    dates = pd.bdate_range("2019-12-25", "2020-01-10")
    f = in_index_flag(dates, pd.Timestamp("2020-01-02"))
    assert not f["2019-12-31"]
    assert f["2020-01-02"]


def test_missing_add_date_treated_as_member():
    dates = pd.bdate_range("2000-01-03", "2000-01-14")
    assert in_index_flag(dates, pd.NaT).all()


def test_ticker_conversion():
    assert to_data_ticker("BRK.B") == "BRK-B"
    assert to_data_ticker(" AAPL ") == "AAPL"


def test_validate_rejects_short_table():
    df = pd.DataFrame({"ticker": [f"T{i}" for i in range(50)]})
    with pytest.raises(RuntimeError):
        validate_snapshot(df)