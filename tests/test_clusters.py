import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from patternlab.clusters import pack, jaccard, cluster_patterns
from patternlab.db import connect, insert_run, get_or_create_pattern, insert_result
from patternlab.reports import build_pattern_context, to_api_rows, load_clusters


def m(idx, n=100):
    a = np.zeros(n, dtype=bool)
    a[list(idx)] = True
    return pack(a)


def test_jaccard_basic():
    assert jaccard(m(range(0, 10)), m(range(0, 10))) == 1.0
    assert jaccard(m(range(0, 10)), m(range(10, 20))) == 0.0
    assert abs(jaccard(m(range(0, 10)), m(range(5, 15))) - 5 / 15) < 1e-9


def test_similar_patterns_group_under_the_strongest():
    packed = {1: m(range(0, 20)), 2: m(range(1, 21)), 3: m(range(50, 70))}
    out = cluster_patterns(packed, {1: 0.02, 2: 0.05, 3: 0.01}, threshold=0.5).set_index("pattern_id")
    assert out.loc[2, "is_lead"] and out.loc[1, "cluster_id"] == 2     # 2 is stronger, so it leads
    assert out.loc[1, "cluster_size"] == 2 and out.loc[3, "cluster_size"] == 1
    assert out.loc[3, "is_lead"] and out.loc[3, "cluster_id"] == 3


def test_no_chaining_through_a_middle_pattern():
    # A~B and B~C overlap, but A and C do not: C must not be pulled into A's group through B.
    packed = {1: m(range(0, 20)), 2: m(range(10, 30)), 3: m(range(20, 40))}
    out = cluster_patterns(packed, {1: 0.03, 2: 0.02, 3: 0.01}, threshold=0.3).set_index("pattern_id")
    assert out.loc[2, "cluster_id"] == 1            # B joins lead A
    assert out.loc[3, "is_lead"]                    # C only compares to leads (A), not B


def test_every_pattern_is_in_exactly_one_group_and_threshold_one_means_no_grouping():
    packed = {i: m(range(i, i + 10)) for i in range(5)}
    out = cluster_patterns(packed, {i: i for i in range(5)}, threshold=1.01)
    assert sorted(out["pattern_id"]) == list(range(5)) and out["is_lead"].all()


def _db(tmp_path):
    conn = connect({"data_dir": str(tmp_path), "index": "sp500"})
    run = insert_run(conn, {"horizon": 5}, "v", "snap")
    pids = []
    for i in range(3):
        pid = get_or_create_pattern(conn, f"ret_{i} in bucket 0", [{"feature": f"ret_{i}", "bucket": 0}])
        pids.append(pid)
        for view in ("all", "flagged"):
            for split in ("discovery", "confirm"):
                insert_result(conn, {"pattern_id": pid, "run_id": run, "view": view, "horizon": 5,
                                     "outcome_type": "x", "split": split, "n_occurrences": 500,
                                     "n_thinned": 200, "mean_fwd_return": 0.01, "baseline_mean": 0.0,
                                     "hit_rate": 0.5, "baseline_hit_rate": 0.5, "effect": 0.01 * (i + 1),
                                     "p_value": 0.001, "q_value": 0.01, "ci_low": 0.0, "ci_high": 0.02,
                                     "breadth_stocks": 0.7, "breadth_years": 0.7, "passed": 1})
    conn.commit()
    return conn, pids


def _m6():
    spec = importlib.util.spec_from_file_location("m6_postprocess", Path("scripts") / "m6_postprocess.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_m6_stores_clusters_and_api_exposes_them(tmp_path):
    conn, pids = _db(tmp_path)
    n = 60
    flags = {0: range(0, 30), 1: range(2, 32), 2: range(40, 60)}      # patterns 0 and 1 overlap heavily
    buckets = pd.DataFrame({f"ret_{i}": [0 if k in flags[i] else 1 for k in range(n)] for i in range(3)})
    _m6().store_clusters(conn, buckets, pd.Series(True, index=buckets.index))
    cl = load_clusters(conn)
    assert cl[pids[1]]["cluster_id"] == pids[1] and cl[pids[0]]["cluster_id"] == pids[1]   # 1 is stronger
    assert cl[pids[2]]["cluster_size"] == 1
    rows = {r["pattern_id"]: r for r in to_api_rows(build_pattern_context(conn), {}, cl)}
    assert rows[pids[1]]["cluster_lead"] and rows[pids[1]]["cluster_size"] == 2
    assert not rows[pids[0]]["cluster_lead"] and rows[pids[0]]["cluster_id"] == pids[1]
    # case counts are untouched by grouping
    assert rows[pids[0]]["n_all"] == 200


def test_results_without_clusters_stay_ungrouped(tmp_path):
    conn, pids = _db(tmp_path)
    rows = to_api_rows(build_pattern_context(conn), {}, load_clusters(conn))
    assert all(r["cluster_lead"] and r["cluster_size"] == 1 and r["cluster_id"] is None for r in rows)


def test_m6_handles_missing_bucket_values(tmp_path):
    # Features with no value on some days (warm-up periods) have a missing bucket;
    # those days simply don't match. This crashed M6 with "boolean value of NA is ambiguous".
    conn, pids = _db(tmp_path)
    n = 60
    flags = {0: range(0, 30), 1: range(2, 32), 2: range(40, 60)}
    cols = {}
    for i in range(3):
        vals = pd.array([0 if k in flags[i] else 1 for k in range(n)], dtype="Int64")
        vals[:5] = pd.NA
        cols[f"ret_{i}"] = vals
    buckets = pd.DataFrame(cols)
    _m6().store_clusters(conn, buckets, pd.Series(True, index=buckets.index))
    assert len(load_clusters(conn)) == 3
