from __future__ import annotations
import os
import re
from pathlib import Path
import yaml

VALID_HORIZONS = (1, 5, 10, 20, 63, 126, 252)

# Assumed round-trip trading cost per index, as a fraction of price (0.001 = 0.1%).
# Judgment-based starting points: wider bid/ask spreads and more price impact as
# companies get smaller. Override per index with `index_costs` in config.yaml or
# on the Settings page. `cost` is only the fallback for an index with no entry here.
DEFAULT_INDEX_COSTS = {"sp500": 0.001, "sp400": 0.002, "sp600": 0.003, "etfs": 0.0005}


def cost_for(cfg: dict) -> float:
    """The assumed trading cost for cfg's index."""
    index = cfg.get("index")
    own = (cfg.get("index_costs") or {}).get(index)
    if own is None:
        own = DEFAULT_INDEX_COSTS.get(index)
    return float(own if own is not None else cfg.get("cost", 0.001))

REQUIRED_KEYS = [
    "index", "data_dir", "report_dir", "start_date",
    "use_stooq_fallback", "jump_threshold", "pause_seconds",
    "horizon", "move_atr", "discovery_frac", "cost",
    "corr_prune_threshold", "test_all_buckets", "multithreading",
    "disabled_features"
]


class ConfigError(ValueError):
    """Raised for invalid or missing config.yaml settings. Collects every
    problem found, not just the first, so a form can show them all at once."""


# A running job sets this to its own frozen copy of the settings (see jobs.py), so
# changing the index or saving Settings in the GUI cannot change a job that is
# already running. Unset means: read config.yaml as usual.
JOB_CONFIG_ENV = "PATTERNLAB_CONFIG"


def load_config(path: str = "config.yaml") -> dict:
    path = os.environ.get(JOB_CONFIG_ENV) or path
    cfg = read_raw_config(path)
    validate_config(cfg, path)
    return cfg


def read_raw_config(path: str = "config.yaml") -> dict:
    """Loads config.yaml without validating -- lets a Settings UI display
    and fix an invalid file instead of crashing on load."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict, path: str = "config.yaml") -> None:
    """Validates before writing -- never persists an invalid config.
    NOTE: this rewrites the whole file via yaml.safe_dump, which does not
    preserve comments -- any hand-written explanatory comments in the file
    are lost once it's saved from here."""
    validate_config(cfg, path)
    ordered = {k: cfg[k] for k in REQUIRED_KEYS if k in cfg}
    if "start_overrides" in cfg:
        ordered["start_overrides"] = cfg["start_overrides"]
    if "index_costs" in cfg:
        ordered["index_costs"] = cfg["index_costs"]
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(ordered, f, default_flow_style=False, sort_keys=False)


def validate_config(cfg: dict, path: str = "config.yaml") -> None:
    errors = []

    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        errors.append(f"missing required setting(s): {', '.join(missing)}")

    if "horizon" in cfg and cfg["horizon"] not in VALID_HORIZONS:
        errors.append(
            f"horizon={cfg['horizon']!r} is not one of the pre-computed horizons "
            f"{VALID_HORIZONS} (see outcomes.py). Pick one of these.")

    for key in ("discovery_frac", "corr_prune_threshold"):
        if key in cfg:
            v = cfg[key]
            if not isinstance(v, (int, float)) or not (0 < v < 1):
                errors.append(f"{key}={v!r} must be a number between 0 and 1 (exclusive).")

    if "move_atr" in cfg and (not isinstance(cfg["move_atr"], (int, float)) or cfg["move_atr"] <= 0):
        errors.append(f"move_atr={cfg['move_atr']!r} must be a positive number.")

    if "cost" in cfg and (not isinstance(cfg["cost"], (int, float)) or cfg["cost"] < 0):
        errors.append(
            f"cost={cfg['cost']!r} must be zero or a positive number "
            f"(a fraction of price, e.g. 0.001 = 0.1% round-trip).")

    ic = cfg.get("index_costs")
    if ic is not None:
        if not isinstance(ic, dict):
            errors.append("index_costs must be a mapping of index name to cost (a fraction of price).")
        else:
            for k, v in ic.items():
                if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                    errors.append(f"index_costs[{k!r}]={v!r} must be zero or a positive number.")

    if "jump_threshold" in cfg and (not isinstance(cfg["jump_threshold"], (int, float)) or cfg["jump_threshold"] <= 0):
        errors.append(f"jump_threshold={cfg['jump_threshold']!r} must be a positive number.")

    if "pause_seconds" in cfg and (not isinstance(cfg["pause_seconds"], (int, float)) or cfg["pause_seconds"] < 0):
        errors.append(f"pause_seconds={cfg['pause_seconds']!r} must be zero or positive.")

    for key in ("test_all_buckets", "use_stooq_fallback", "multithreading"):
        if key in cfg and not isinstance(cfg[key], bool):
            errors.append(f"{key}={cfg[key]!r} must be true or false.")

    if "index" in cfg:
        from patternlab.universe_fetch import PROVIDERS, get_index_proxy
        if cfg["index"] not in PROVIDERS:
            errors.append(
                f"index={cfg['index']!r} has no registered loader. "
                f"Available: {sorted(PROVIDERS)}.")
        else:
            try:
                get_index_proxy(cfg["index"])
            except ValueError as e:
                errors.append(str(e))

    overrides = cfg.get("start_overrides") or {}
    if not isinstance(overrides, dict):
        errors.append("start_overrides must be a mapping of TICKER: \"YYYY-MM-DD\".")
    else:
        for ticker, date_str in overrides.items():
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(date_str)):
                errors.append(
                    f"start_overrides[{ticker!r}]={date_str!r} must be a YYYY-MM-DD date string.")

    if "disabled_features" in cfg:
        if not isinstance(cfg["disabled_features"], list) or not all(isinstance(f, str) for f in cfg["disabled_features"]):
            errors.append("disabled_features must be a list of feature-name strings.")
        else:
            from patternlab.humanize import ALL_FEATURES
            unknown = [f for f in cfg["disabled_features"] if f not in ALL_FEATURES]
            if unknown:
                errors.append(f"disabled_features contains unknown feature name(s): {unknown}. "
                              f"Valid names: {ALL_FEATURES}.")

    if errors:
        raise ConfigError(f"{path}: " + "; ".join(errors))


def ensure_dirs(cfg: dict) -> None:
    for key in ("data_dir", "report_dir"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)


def index_data_dir(cfg: dict, kind: str) -> Path:
    """Per-index cache folder: <data_dir>/<index>/<kind> (kind = raw, features,
    outcomes). Every index owns its own price data, features and outcomes, so
    a refresh, rebuild or index-relative feature on one index can never touch
    another's files."""
    return Path(cfg["data_dir"]) / cfg["index"] / kind


def market_data_dir(cfg: dict) -> Path:
    """Shared folder for the market-wide tickers (Market Insights' SPY, DIA, QQQ,
    IWM, ^VIX, ^VIX3M). One copy, so every index shows the same values. Stocks
    and each index's own proxy stay in their per-index folders."""
    return Path(cfg["data_dir"]) / "market" / "raw"


def manifest_path(cfg: dict) -> Path:
    return Path(cfg["data_dir"]) / f"manifest_{cfg['index']}.json"


def report_dir_for(cfg: dict) -> Path:
    d = Path(cfg["report_dir"]) / cfg["index"]
    d.mkdir(parents=True, exist_ok=True)
    return d