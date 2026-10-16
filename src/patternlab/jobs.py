from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

STAGES = [
    {"id": "m1", "label": "Fetch prices & universe", "script": "scripts/m1_fetch.py"},
    {"id": "m2", "label": "Compute features", "script": "scripts/m2_features.py"},
    {"id": "m3", "label": "Compute outcomes", "script": "scripts/m3_outcomes.py"},
    {"id": "m4", "label": "Single-condition search", "script": "scripts/m4_search.py"},
    {"id": "m5", "label": "Two-condition search (slowest stage)", "script": "scripts/m5_search.py"},
    {"id": "m6", "label": "Post-process results", "script": "scripts/m6_postprocess.py"},
]
STAGE_BY_ID = {s["id"]: s for s in STAGES}

JOBS = {
    "refresh": ["m1", "m2"],
    "full_discovery": ["m1", "m2", "m3", "m4", "m5", "m6"],
}

_lock = threading.Lock()
_state = {
    "status": "idle",       # idle | running | done | error
    "job_name": None,
    "stage_ids": [],
    "current_index": None,
    "started_at": None,
    "stage_started_at": None,
    "finished_at": None,
    "error": None,
}


def get_status() -> dict:
    with _lock:
        return dict(_state)


def is_running() -> bool:
    with _lock:
        return _state["status"] == "running"


def _log_path(job_name: str, stage_id: str) -> Path:
    d = PROJECT_ROOT / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_name}_{stage_id}.log"


def _run_chain(job_name: str, stage_ids: list[str]):
    now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        _state.update(status="running", job_name=job_name, stage_ids=stage_ids,
                      current_index=0, started_at=now(), stage_started_at=now(),
                      finished_at=None, error=None)

    for i, stage_id in enumerate(stage_ids):
        with _lock:
            _state["current_index"] = i
            _state["stage_started_at"] = now()
        stage = STAGE_BY_ID[stage_id]
        log_path = _log_path(job_name, stage_id)
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / stage["script"])],
                cwd=PROJECT_ROOT, stdout=logf, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            with _lock:
                _state.update(status="error", finished_at=now(),
                              error=f"{stage['label']} ({stage_id}) failed. Last output:\n{tail}")
            return

    if job_name == "full_discovery":
        _record_discovery_completion()

    with _lock:
        _state.update(status="done", finished_at=now())


def start_job(job_name: str) -> tuple[bool, str]:
    if job_name not in JOBS:
        return False, f"Unknown job {job_name!r}"
    if is_running():
        return False, "A job is already running."
    threading.Thread(target=_run_chain, args=(job_name, JOBS[job_name]), daemon=True).start()
    return True, "started"


def _config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def _discovery_log_path(index: str) -> Path:
    d = PROJECT_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"discovery_log_{index}.json"


def _record_discovery_completion():
    from patternlab.config import read_raw_config
    cfg = read_raw_config()
    _discovery_log_path(cfg["index"]).write_text(json.dumps({
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config_hash": _config_hash(cfg),
    }, indent=2))


def discovery_status() -> dict:
    """Last-run info for the currently configured index, plus whether
    settings changed since then -- drives the dashboard staleness prompt."""
    from patternlab.config import read_raw_config
    cfg = read_raw_config()
    path = _discovery_log_path(cfg["index"])
    if not path.exists():
        return {"completed_at": None, "days_ago": None, "config_changed": True, "never_run": True}
    data = json.loads(path.read_text())
    completed = datetime.fromisoformat(data["completed_at"])
    days_ago = (datetime.now(timezone.utc) - completed).days
    return {"completed_at": data["completed_at"], "days_ago": days_ago,
            "config_changed": data.get("config_hash") != _config_hash(cfg), "never_run": False}