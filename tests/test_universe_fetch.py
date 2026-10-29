import pytest
from patternlab.universe_fetch import get_index_proxy


def test_get_index_proxy_known_index():
    assert get_index_proxy("sp500") == "SPY"


def test_get_index_proxy_unknown_index_raises():
    with pytest.raises(ValueError, match="No proxy ticker registered"):
        get_index_proxy("not_a_real_index")

def test_sp400_provider_parses_table_and_has_no_join_dates(monkeypatch):
    import io
    from patternlab import universe_fetch as uf
    html = ("<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>"
            "<tr><td>AA</td><td>Alcoa</td><td>Materials</td></tr>"
            "<tr><td>MOG.A</td><td>Moog</td><td>Industrials</td></tr></table>")

    class R:
        text = html
        def raise_for_status(self): pass
    monkeypatch.setattr(uf.requests, "get", lambda *a, **k: R())
    df = uf.fetch_sp400()
    assert list(df["data_ticker"]) == ["AA", "MOG-A"]
    assert df["date_added"].isna().all()
    assert uf.get_index_proxy("sp400") == "MDY"
    assert "sp400" in uf.PROVIDERS and uf.EXPECTED_COUNTS["sp400"] == (380, 420)
    assert uf.fetch_sp600().shape == df.shape            # same table layout, same parser
    assert uf.get_index_proxy("sp600") == "IJR"
    assert "sp600" in uf.PROVIDERS and uf.EXPECTED_COUNTS["sp600"] == (570, 630)
