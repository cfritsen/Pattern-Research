from __future__ import annotations
import json
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path
import pandas as pd
from patternlab.universe_fetch import get_universe
from patternlab.search import load_panel, build_buckets, evaluate_condition
from patternlab.overlap import bucket_overlap_ratio

# Process-global, set once per worker by _init_worker -- avoids rebuilding
# the panel on every task, only once per worker process at startup.
_PANEL = _BUCKETS = _IS_DISC = _IS_CONF = _H0 = _MARKET = None


def resolved_worker_count(cfg: dict) -> int:
    if not cfg.get("multithreading", False):
        return 1
    return max(1, cpu_count() - 2)


def _init_worker(cfg: dict):
    global _PANEL, _BUCKETS, _IS_DISC, _IS_CONF, _H0, _MARKET
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    panel, feature_cols = load_panel(cfg, uni)
    is_disc = panel[f"split_{h0}"] == 0
    is_conf = panel[f"split_{h0}"] == 1
    buckets, _ = build_buckets(panel, feature_cols, is_disc)

    view_masks = {"all": pd.Series(True, index=panel.index), "flagged": panel["in_index"]}
    market = {}
    for view, vmask in view_masks.items():
        for split_name, smask in (("discovery", is_disc), ("confirm", is_conf)):
            market[(view, split_name)] = panel[vmask & smask][[f"fwd_ret_{h0}", "date"]].rename(
                columns={f"fwd_ret_{h0}": "fwd_ret"}).groupby("date").mean()

    _PANEL, _BUCKETS, _IS_DISC, _IS_CONF, _H0, _MARKET = panel, buckets, is_disc, is_conf, h0, market


def _view_mask(view: str) -> pd.Series:
    return pd.Series(True, index=_PANEL.index) if view == "all" else _PANEL["in_index"]


def m4_task(task: tuple) -> list[dict]:
    """task = (view, feature, bucket)."""
    view, col, label = task
    mask = _view_mask(view) & (_BUCKETS[col] == label)
    out = []
    for split_name, smask in (("discovery", _IS_DISC), ("confirm", _IS_CONF)):
        sub = _PANEL[mask & smask]
        r = evaluate_condition(sub, _MARKET[(view, split_name)], view, _H0)
        if r is None:
            continue
        r = dict(r)
        r.update(view=view, split=split_name, feature=col, bucket=int(label))
        out.append(r)
    return out


def m5_task(task: tuple) -> list[dict]:
    """task = (view, feature_a, bucket_a, feature_b, bucket_b)."""
    view, fa, la, fb, lb = task
    vmask = _view_mask(view)
    mask_ab = vmask & (_BUCKETS[fa] == la) & (_BUCKETS[fb] == lb)
    out = []
    for split_name, smask in (("discovery", _IS_DISC), ("confirm", _IS_CONF)):
        sub = _PANEL[mask_ab & smask]
        r = evaluate_condition(sub, _MARKET[(view, split_name)], view, _H0)
        if r is None:
            continue
        scope = vmask & smask
        ov = bucket_overlap_ratio(_BUCKETS[fa], la, _BUCKETS[fb], lb, scope)
        r = dict(r)
        r.update(view=view, split=split_name, feature_a=fa, bucket_a=int(la),
                 feature_b=fb, bucket_b=int(lb), overlap_ratio=ov)
        out.append(r)
    return out


def _write_progress(path: Path, done: int, total: int, t0: float):
    path.write_text(json.dumps({"done": done, "total": total, "elapsed_s": round(time.time() - t0, 1)}))


def run_search(cfg: dict, tasks: list, kind: str, progress_path: Path | None = None) -> list[dict]:
    """kind: 'm4' or 'm5'. Returns the flat list of result dicts from every
    task, in no particular order -- the caller is responsible for turning
    each one into a DB pattern + result row."""
    task_fn = m4_task if kind == "m4" else m5_task
    n_workers = resolved_worker_count(cfg)
    total = len(tasks)
    if progress_path:
        _write_progress(progress_path, 0, total, time.time())
    results, done, t0 = [], 0, time.time()

    if n_workers == 1:
        _init_worker(cfg)
        for t in tasks:
            results.extend(task_fn(t))
            done += 1
            if progress_path and done % 50 == 0:
                _write_progress(progress_path, done, total, t0)
    else:
        with Pool(processes=n_workers, initializer=_init_worker, initargs=(cfg,)) as pool:
            for r in pool.imap_unordered(task_fn, tasks, chunksize=20):
                results.extend(r)
                done += 1
                if progress_path and done % 20 == 0:
                    _write_progress(progress_path, done, total, t0)

    if progress_path:
        _write_progress(progress_path, total, total, t0)
    return results