import json
import pandas as pd

from patternlab.db import connect, insert_run, get_or_create_pattern, insert_result
from patternlab.humanize import humanize_pattern_view
from patternlab.reports import build_pattern_context, to_api_rows


def _db(tmp_path, with_thinned):
    cfg = {"data_dir": str(tmp_path), "index": "sp500"}
    conn = connect(cfg)
    run = insert_run(conn, {"horizon": 10}, "v", "snap")
    pid = get_or_create_pattern(conn, "ret_1 in bucket 0", [{"feature": "ret_1", "bucket": 0}])
    for view, n, thin in (("all", 1000, 400), ("flagged", 900, 350)):
        for split in ("discovery", "confirm"):
            row = {"pattern_id": pid, "run_id": run, "view": view, "horizon": 10, "outcome_type": "x",
                   "split": split, "n_occurrences": n, "mean_fwd_return": 0.01, "baseline_mean": 0.0,
                   "hit_rate": 0.5, "baseline_hit_rate": 0.5, "effect": 0.01, "p_value": 0.001,
                   "q_value": 0.01, "ci_low": 0.0, "ci_high": 0.02, "breadth_stocks": 0.7,
                   "breadth_years": 0.7, "passed": 1}
            if with_thinned:
                row["n_thinned"] = thin
            insert_result(conn, row)
    conn.commit()
    return conn


def test_context_uses_thinned_count_and_keeps_raw(tmp_path):
    ctx = build_pattern_context(_db(tmp_path, True))
    r = ctx.iloc[0]
    assert (r["n_all"], r["n_flagged"]) == (400, 350)
    assert (r["n_raw_all"], r["n_raw_flagged"]) == (1000, 900)


def test_old_results_fall_back_to_raw_count(tmp_path):
    ctx = build_pattern_context(_db(tmp_path, False))
    r = ctx.iloc[0]
    assert (r["n_all"], r["n_flagged"]) == (1000, 900)


def test_pre_index_bias_still_uses_raw_counts(tmp_path):
    ctx = build_pattern_context(_db(tmp_path, True))
    row = to_api_rows(ctx, {})[0]
    assert abs(row["pre_index_bias"] - 0.1) < 1e-9          # (1000-900)/1000, not (400-350)/400
    assert row["n_raw_all"] == 1000 and row["n_all"] == 400


def test_existing_database_gets_the_new_column(tmp_path):
    cfg = {"data_dir": str(tmp_path), "index": "sp500"}
    conn = connect(cfg)
    cols = [r[1] for r in conn.execute("pragma table_info(pattern_results_pooled)")]
    assert "n_thinned" in cols
    connect(cfg)                                              # a second connect must not fail


def test_report_labels_follow_horizon(tmp_path):
    ctx = build_pattern_context(_db(tmp_path, True))
    for h in (3, 10):
        out = humanize_pattern_view(ctx, {}, h)
        assert f"{h}-day Return" in out.columns and f"{h}-day Baseline" in out.columns
        assert "5-day Return" not in out.columns or h == 5
    assert list(out["Cases Found"]) == ["400"] and "Raw Cases" not in out.columns


def test_cost_nets_edge_and_hides_results_within_it(tmp_path):
    conn = _db(tmp_path, True)                       # both views have effect +1.00%
    ctx = build_pattern_context(conn, cost=0.002)
    r = ctx.iloc[0]
    assert abs(r["effect_all"] - 0.008) < 1e-12 and abs(r["effect_flagged"] - 0.008) < 1e-12
    assert abs(r["mean_fwd_return_all"] - 0.01) < 1e-12          # Return stays gross
    assert build_pattern_context(conn, cost=0.02).empty is True or len(build_pattern_context(conn, cost=0.02)) == 0
