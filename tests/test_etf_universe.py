from pathlib import Path
import pandas as pd
import pytest

from patternlab import universe_fetch as uf
from patternlab.config import cost_for, DEFAULT_INDEX_COSTS
from patternlab.universe_fetch import get_universe, get_index_proxy, PROVIDERS, EXPECTED_COUNTS

REAL_LIST = Path(__file__).resolve().parent.parent / "data" / "universe"


def _list(folder, n=3, name="etf_candidates_2026-10-29.csv"):
    pd.DataFrame({"ticker": [f"E{i}" for i in range(n)], "group": ["Bonds"] * n,
                  "category": ["Core"] * n, "fundFamily": ["Fam"] * n}).to_csv(folder / name, index=False)


def test_etfs_is_a_registered_index_with_a_proxy_and_cost():
    assert "etfs" in PROVIDERS and "etfs" in EXPECTED_COUNTS
    assert get_index_proxy("etfs") == "SPY"
    assert cost_for({"index": "etfs"}) == DEFAULT_INDEX_COSTS["etfs"] == 0.0005


def test_loader_reads_the_newest_list_and_has_no_join_dates(tmp_path):
    _list(tmp_path, 3, "etf_candidates_2026-01-01.csv")
    _list(tmp_path, 5, "etf_candidates_2026-10-29.csv")
    df = uf.fetch_etfs(tmp_path)
    assert len(df) == 5 and df["date_added"].isna().all()
    assert list(df.columns) == ["ticker", "company", "sector", "date_added", "data_ticker"]
    assert df["sector"].iloc[0] == "Bonds"


def test_missing_list_is_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="No curated ETF list"):
        uf.fetch_etfs(tmp_path)


def test_snapshot_files_are_not_confused_with_the_list(tmp_path, monkeypatch):
    # the list is etf_candidates_*.csv and the saved snapshot is etfs_<date>.csv: distinct patterns
    folder = tmp_path / "universe"
    folder.mkdir()
    _list(folder, 70)
    monkeypatch.setattr(uf, "ETF_LIST_DIR", folder)
    monkeypatch.setitem(PROVIDERS, "etfs", lambda: uf.fetch_etfs(folder))
    cfg = {"index": "etfs", "data_dir": str(tmp_path)}
    first = get_universe(cfg)
    again = get_universe(cfg)                       # now read back from etfs_<date>.csv
    assert len(first) == len(again) == 70
    assert sorted(p.name for p in folder.glob("etfs_*.csv")) and not list(folder.glob("etfs_etf*"))


@pytest.mark.skipif(not list(REAL_LIST.glob("etf_candidates_*.csv")), reason="owner's ETF list not present")
def test_the_real_list_loads_and_passes_the_count_check():
    df = uf.fetch_etfs()
    uf.validate_snapshot(df, *EXPECTED_COUNTS["etfs"])
    assert df["ticker"].is_unique and "SPY" in set(df["ticker"])
