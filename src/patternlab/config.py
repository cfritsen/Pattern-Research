from pathlib import Path
import yaml

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ensure_dirs(cfg: dict) -> None:
    for key in ("data_dir", "report_dir"):
        Path(cfg[key]).mkdir(parents=True, exist_ok=True)