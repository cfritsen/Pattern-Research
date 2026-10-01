import pytest
from patternlab.config import validate_config, ConfigError, REQUIRED_KEYS

GOOD = {
    "index": "sp500", "data_dir": "data", "report_dir": "reports",
    "start_date": "1996-01-01",
    "use_stooq_fallback": True, "jump_threshold": 0.25, "pause_seconds": 0.5,
    "start_overrides": {"JCI": "2007-07-02"},
    "horizon": 5, "move_atr": 1.0, "discovery_frac": 0.7, "cost": 0.001,
    "corr_prune_threshold": 0.7, "test_all_buckets": False,
}


def test_valid_config_passes():
    validate_config(dict(GOOD))


def test_missing_key_rejected():
    cfg = dict(GOOD)
    del cfg["cost"]
    with pytest.raises(ConfigError, match="cost"):
        validate_config(cfg)


def test_bad_horizon_rejected():
    cfg = dict(GOOD, horizon=7)
    with pytest.raises(ConfigError, match="horizon"):
        validate_config(cfg)


def test_discovery_frac_out_of_range_rejected():
    cfg = dict(GOOD, discovery_frac=1.5)
    with pytest.raises(ConfigError, match="discovery_frac"):
        validate_config(cfg)


def test_negative_cost_rejected():
    cfg = dict(GOOD, cost=-0.001)
    with pytest.raises(ConfigError, match="cost"):
        validate_config(cfg)


def test_unknown_index_rejected():
    cfg = dict(GOOD, index="nasdaq_made_up")
    with pytest.raises(ConfigError, match="index"):
        validate_config(cfg)


def test_bad_start_override_date_rejected():
    cfg = dict(GOOD, start_overrides={"JCI": "not-a-date"})
    with pytest.raises(ConfigError, match="start_overrides"):
        validate_config(cfg)


def test_all_required_keys_covered_by_good_fixture():
    assert set(REQUIRED_KEYS) <= set(GOOD)