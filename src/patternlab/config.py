from __future__ import annotations
import re
from pathlib import Path
import yaml

VALID_HORIZONS = (1, 5, 10, 20, 63, 126, 252)

REQUIRED_KEYS = [
    "index", "data_dir", "report_dir", "start_date",
    "use_stooq_fallback", "jump_threshold", "pause_seconds",
    "horizon", "move_atr", "discovery_frac", "cost",
    "corr_prune_threshold", "test_all_buckets",
]


class ConfigError(ValueError):
    """Raised for an invalid or missing config.yaml setting. The message
    names the offending key and says what a valid value looks like, so a
    hand-edit mistake fails loudly at startup instead of deep in a script."""


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    validate_config(cfg, path)
    return cfg


def validate_config(cfg: dict, path: str = "config.yaml") -> None:
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ConfigError(f"{path}: missing required setting(s): {', '.join(missing)}")

    if cfg["horizon"] not in VALID_HORIZONS:
        raise ConfigError(
            f"{path}: horizon={cfg['horizon']!r} is not one of the pre-computed horizons "
            f"{VALID_HORIZONS} (see outcomes.py). Pick one of these.")

    for key in ("discovery_frac", "corr_prune_threshold"):
        v = cfg[key]
        if not isinstance(v, (int, float)) or not (0 < v < 1):
            raise ConfigError(f"{path}: {key}={v!r} must be a number between 0 and 1 (exclusive).")

    if not isinstance(cfg["move_atr"], (int, float)) or cfg["move_atr"] <= 0:
        raise ConfigError(f"{path}: move_atr={cfg['move_atr']!r} must be a positive number.")

    if not isinstance(cfg["cost"], (int, float)) or cfg["cost"] < 0:
        raise ConfigError(
            f"{path}: cost={cfg['cost']!r} must be zero or a positive number "
            f"(a fraction of price, e.g. 0.001 = 0.1% round-trip).")

    if not isinstance(cfg["jump_threshold"], (int, float)) or cfg["jump_threshold"] <= 0:
        raise ConfigError(f"{path}: jump_threshold={cfg['jump_threshold']!r} must be a positive number.")

    if not isinstance(cfg["pause_seconds"], (int, float)) or cfg["pause_seconds"] < 0:
        raise ConfigError(f"{path}: pause_seconds={cfg['pause_seconds']!r} must be zero or positive.")

    for key in ("test_all_buckets", "use_stooq_fallback"):
        if not isinstance(cfg[key], bool):
            raise ConfigError(f"{path}: {key}={cfg[key]!r} must be true or false.")

    from patternlab.universe_fetch import PROVIDERS, get_index_proxy
    if cfg["index"] not in PROVIDERS:
        raise ConfigError(
            f"{path}: index={cfg['index']!r} has no registered loader. "
            f"Available: {sorted(PROVIDERS)}.")
    try:
        get_index_proxy(cfg["index"])
    except ValueError as e:
        raise ConfigError(f"{path}: {e}") from e

    overrides = cfg.get("start_overrides") or {}
    if not isinstance(overrides, dict):
        raise ConfigError(f"{path}: start_overrides must be a mapping of TICKER: \"YYYY-MM-DD\".")
    for ticker, date_str in overrides.items():
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(date_str)):
            raise ConfigError(
                f"{path}: start_overrides[{ticker!r}]={date_str!r} must be a YYYY-MM-DD date string.")


def ensure_dirs(cfg: dict) -> None:
    for key in ("data_dir", "report_dir"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)


def manifest_path(cfg: dict) -> Path:
    return Path(cfg["data_dir"]) / f"manifest_{cfg['index']}.json"


def report_dir_for(cfg: dict) -> Path:
    d = Path(cfg["report_dir"]) / cfg["index"]
    d.mkdir(parents=True, exist_ok=True)
    return d