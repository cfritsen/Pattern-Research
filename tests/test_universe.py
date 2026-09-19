import pandas as pd
import pytest
from patternlab.universe import load_universe, top10_flag

HEADER = "ticker,company,data_ticker,first_top10_year,last_top10_year,share_class_note,data_status\n"


def write(tmp_path, body):
    p = tmp_path / "u.csv"
    p.write_text(HEADER + body)
    return str(p)


def test_blank_data_ticker_falls_back(tmp_path):
    df = load_universe(write(tmp_path, "AAA,Aaa Co,,2000,2005,,ok\n"))
    assert df.loc[0, "data_ticker"] == "AAA"


def test_bad_status_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_universe(write(tmp_path, "AAA,Aaa Co,,2000,2005,,maybe\n"))


def test_years_reversed_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_universe(write(tmp_path, "AAA,Aaa Co,,2005,2000,,ok\n"))


def test_flag_starts_year_after_first_ranking():
    dates = pd.bdate_range("1999-12-01", "2003-01-31")
    f = top10_flag(dates, first_year=2000, last_year=2001)
    assert not f["2000-12-29"]          # ranked at end of 2000, not flagged yet
    assert f["2001-01-02"]              # flagged from the next year
    assert f["2002-12-31"]              # last year + 1 still flagged
    assert not f["2003-01-02"]