import numpy as np
import pandas as pd
from patternlab.search import load_panel


def test_load_panel_skips_tickers_without_data(tmp_path, capsys):
    cfg = {"index": "x", "data_dir": str(tmp_path), "horizon": 5}
    fdir, odir = tmp_path / "x" / "features", tmp_path / "x" / "outcomes"
    fdir.mkdir(parents=True); odir.mkdir(parents=True)
    ix = pd.bdate_range("2020-01-01", periods=10)
    pd.DataFrame({"rsi": np.arange(10.0), "tradable": True}, index=ix).to_parquet(fdir / "AAA.parquet")
    pd.DataFrame({"fwd_ret_5": 0.01, "split_5": 0, "up_hit": 1.0, "down_hit": 0.0, "tradable": True},
                 index=ix).to_parquet(odir / "AAA.parquet")
    uni = pd.DataFrame({"data_ticker": ["BAD", "AAA"], "date_added": [pd.NaT, pd.NaT]})   # BAD failed upstream
    panel, cols = load_panel(cfg, uni)
    assert set(panel["ticker"]) == {"AAA"} and cols == ["rsi"]
    assert "BAD" in capsys.readouterr().out
