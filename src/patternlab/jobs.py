from __future__ import annotations
import hashlib
import json
import os
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
    "update_data": ["m1", "m2"],
    "full_rediscovery": ["m1", "m2", "m3", "m4", "m5", "m6"],
}

# Extra CLI args per (job, stage). update_data's M1 only fetches bars newer
# than the cache (cheap, bounded adjustment drift). full_rediscovery's M1
# does a genuine full redownload (slower, but re-derives dividend/split
# adjustment correctly across all history) -- see fetch.py's get_prices().
STAGE_ARGS = {
    ("update_data", "m1"): ["--incremental"],
    ("full_rediscovery", "m1"): ["--refresh"],
}

_lock = threading.Lock()
_job_cfg: dict = {}          # frozen settings of the running (or last) job
_queue: list[dict] = []      # waiting runs: {"job_name", "index"}; runs one at a time, in order
_results: list[dict] = []    # finished runs this session (newest last), so failures in a queue are not lost
_worker_active = False       # True while the queue worker thread is working through runs
MAX_RESULTS = 20
_state = {
    "status": "idle",       # idle | running | done | error
    "job_name": None,
    "stage_ids": [],
    "current_index": None,
    "job_index": None,      # the index (S&P 500, ...) this job was started on; fixed for the whole job
    "started_at": None,
    "stage_started_at": None,
    "finished_at": None,
    "error": None,
}


def get_status() -> dict:
    with _lock:
        state = dict(_state)
        state["queue"] = [dict(q) for q in _queue]
        state["results"] = [dict(r) for r in _results]
        state["active"] = _worker_active          # True from the first run starting until the queue is empty
    if state["status"] == "running" and state["stage_ids"]:
        stage_id = state["stage_ids"][state["current_index"]]
        if stage_id in ("m4", "m5"):
            p = PROJECT_ROOT / _job_cfg.get("data_dir", "data") / f"progress_{state['job_index']}_{stage_id}.json"
            if p.exists():
                try:
                    state["stage_progress"] = json.loads(p.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
    return state


def is_running() -> bool:
    with _lock:
        return _state["status"] == "running" or _worker_active


def _log_path(job_name: str, stage_id: str) -> Path:
    d = PROJECT_ROOT / "data" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_name}_{stage_id}.log"


def _freeze_config(cfg: dict) -> Path:
    """Write the job's own copy of the settings; its stages read this, not config.yaml."""
    import yaml
    path = PROJECT_ROOT / "data" / "logs" / "job_config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def _run_chain(job_name: str, stage_ids: list[str], cfg: dict, cfg_path: Path):
    now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    env = {**os.environ, "PATTERNLAB_CONFIG": str(cfg_path)}
    with _lock:
        _state.update(status="running", job_name=job_name, stage_ids=stage_ids,
                      job_index=cfg["index"], current_index=0, started_at=now(), stage_started_at=now(),
                      finished_at=None, error=None)

    for i, stage_id in enumerate(stage_ids):
        with _lock:
            _state["current_index"] = i
            _state["stage_started_at"] = now()
        stage = STAGE_BY_ID[stage_id]
        extra_args = STAGE_ARGS.get((job_name, stage_id), [])
        log_path = _log_path(job_name, stage_id)
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / stage["script"]), *extra_args],
                cwd=PROJECT_ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        if proc.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            with _lock:
                msg = f"{stage['label']} ({stage_id}) failed. Last output:\n{tail}"
                _state.update(status="error", finished_at=now(), error=msg)
                _add_result(job_name, cfg["index"], "error", msg, now())
            return

        # M1 fetches price data in BOTH jobs (incrementally for update_data,
        # a full refresh for full_rediscovery) -- record it here, at the
        # stage level, so "last price data update" reflects whichever job
        # most recently actually ran a fetch, not just one of the two.
        if stage_id == "m1":
            _record_price_update_completion(cfg)

    if job_name == "full_rediscovery":
        _record_discovery_completion(cfg)

    with _lock:
        _state.update(status="done", finished_at=now())
        _add_result(job_name, cfg["index"], "done", None, now())


def _add_result(job_name, index, status, error, finished_at):
    """Caller holds _lock."""
    _results.append({"job_name": job_name, "index": index, "status": status,
                     "error": error, "finished_at": finished_at})
    del _results[:-MAX_RESULTS]


def _worker():
    """Works through the queue one run at a time, never two at once. Each run is
    pinned to its own index and takes the settings in force when it starts, so a
    Settings change made while it waited applies to it."""
    from patternlab.config import read_raw_config
    global _worker_active, _job_cfg
    while True:
        with _lock:
            if not _queue:
                _worker_active = False
                return
            item = _queue.pop(0)
        try:
            cfg = read_raw_config()
            cfg["index"] = item["index"]
            cfg_path = _freeze_config(cfg)
            _job_cfg = cfg
        except Exception as e:                      # keep the queue moving
            with _lock:
                msg = f"Could not start: {e}"
                _state.update(status="error", finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              job_name=item["job_name"], job_index=item["index"], error=msg)
                _add_result(item["job_name"], item["index"], "error", msg,
                            datetime.now(timezone.utc).isoformat(timespec="seconds"))
            continue
        _run_chain(item["job_name"], JOBS[item["job_name"]], cfg, cfg_path)


def start_job(job_name: str, indices: list[str] | None = None) -> tuple[bool, str]:
    """Start a run on each index in `indices` (default: the index selected now).
    If a run is going, the new ones wait in the queue; a run already running or
    queued for the same job and index is not added twice."""
    global _worker_active
    if job_name not in JOBS:
        return False, f"Unknown job {job_name!r}"
    from patternlab.config import read_raw_config
    from patternlab.universe_fetch import PROVIDERS
    indices = list(indices) if indices else [read_raw_config()["index"]]
    unknown = [i for i in indices if i not in PROVIDERS]
    if unknown:
        return False, f"Unknown index {unknown[0]!r}"
    with _lock:
        taken = {(q["job_name"], q["index"]) for q in _queue}
        if _state["status"] == "running":
            taken.add((_state["job_name"], _state["job_index"]))
        added = []
        for idx in indices:
            if (job_name, idx) not in taken:
                _queue.append({"job_name": job_name, "index": idx})
                taken.add((job_name, idx))
                added.append(idx)
        if not added:
            return False, "That run is already running or queued."
        start = not _worker_active
        if start:
            _worker_active = True
    if start:
        threading.Thread(target=_worker, daemon=True).start()
        return True, "started"
    return True, "queued"


def clear_results() -> None:
    with _lock:
        _results.clear()


def remove_queued(position: int) -> bool:
    with _lock:
        if 0 <= position < len(_queue):
            del _queue[position]
            return True
    return False


def _config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def _discovery_log_path(index: str) -> Path:
    d = PROJECT_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"discovery_log_{index}.json"


def _price_update_log_path(index: str) -> Path:
    d = PROJECT_ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"price_update_log_{index}.json"


def _record_price_update_completion(cfg: dict):
    _price_update_log_path(cfg["index"]).write_text(json.dumps({
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))


def price_update_status() -> dict:
    """Last time price data (M1) was fetched for the currently configured
    index, via either Update Price Data or Full Rediscovery -- both run M1."""
    from patternlab.config import read_raw_config
    cfg = read_raw_config()
    path = _price_update_log_path(cfg["index"])
    if not path.exists():
        return {"completed_at": None, "days_ago": None, "never_run": True}
    data = json.loads(path.read_text())
    completed = datetime.fromisoformat(data["completed_at"])
    days_ago = (datetime.now(timezone.utc) - completed).days
    return {"completed_at": data["completed_at"], "days_ago": days_ago, "never_run": False}


def _record_discovery_completion(cfg: dict):
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