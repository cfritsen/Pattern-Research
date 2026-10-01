import pytest
from patternlab.universe_fetch import get_index_proxy


def test_get_index_proxy_known_index():
    assert get_index_proxy("sp500") == "SPY"


def test_get_index_proxy_unknown_index_raises():
    with pytest.raises(ValueError, match="No proxy ticker registered"):
        get_index_proxy("not_a_real_index")