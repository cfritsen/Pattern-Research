import json
from pathlib import Path
import numpy as np
import pandas as pd
from patternlab.config import load_config, ensure_dirs, manifest_path
from patternlab.universe_fetch import get_universe
from patternlab.buckets import CATEGORICAL, MARKET_LEVEL
from patternlab.search import load_panel, build_buckets
from patternlab.stats import benjamini_hochberg
from patternlab.db import connect, insert_run, get_or_create_pattern, insert_result
from patternlab.parallel import run_search


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    progress_path = Path(cfg["data_dir"]) / f"progress_{cfg['index']}_m4.json"
    progress_path.unlink(missing_ok=True)
    # Loaded here too (not just inside each worker) because the main process
    # needs the bucket columns/labels to build the task list before any
    # worker starts.
    panel, feature_cols = load_panel(cfg, uni)
    disabled = set(cfg.get("disabled_features", []))
    feature_cols = [c for c in feature_cols if c not in disabled]
    is_disc = panel[f"split_{h0}"] == 0
    buckets, _ = build_buckets(panel, feature_cols, is_disc)

    manifest = json.loads(manifest_path(cfg).read_text())
    conn = connect(cfg)
    run_id = insert_run(conn, {"horizon": h0, "move_atr": cfg["move_atr"], "n_conditions": 1},
                        manifest["data_version"], manifest["universe_snapshot"])

    # Clear prior single-condition results before inserting this run's --
    # otherwise re-running accumulates duplicate rows per pattern across
    # runs, which breaks every downstream query that assumes one row per
    # (pattern_id, view, split).
    conn.execute("DELETE FROM pattern_results_pooled WHERE pattern_id IN "
                 "(SELECT pattern_id FROM patterns WHERE n_conditions = 1)")
    conn.commit()

    tasks = []
    for view in ("all", "flagged"):
        for col in buckets.columns:
            if col in MARKET_LEVEL:      # same value for every stock per date: cannot pass alone (see buckets.py)
                continue
            n_labels = 5 if col not in CATEGORICAL else int(buckets[col].max() + 1)
            for label in range(n_labels):
                tasks.append((view, col, label))

    progress_path = Path(cfg["data_dir"]) / f"progress_{cfg['index']}_m4.json"
    raw_results = run_search(cfg, tasks, "m4", progress_path)
    tested = len(tasks) * 2   # each task covers both splits

    results = []
    for r in raw_results:
        desc = f"{r['feature']} in bucket {r['bucket']}"
        pid = get_or_create_pattern(conn, desc, [{"feature": r["feature"], "bucket": r["bucket"]}])
        r = dict(r)
        r.update(pattern_id=pid, run_id=run_id, horizon=h0, outcome_type="direction",
                 passed=0, q_value=None)
        results.append(r)

    if results:
        df = pd.DataFrame(results)
        disc_mask = df["split"] == "discovery"
        pv = df.loc[disc_mask, "p_value"].to_numpy()
        passed = benjamini_hochberg(pv, q=0.05)
        df.loc[disc_mask, "passed"] = passed.astype(int)
        pass_map = dict(zip(df.loc[disc_mask, "pattern_id"], passed))
        df.loc[~disc_mask, "passed"] = df.loc[~disc_mask, "pattern_id"].map(pass_map).fillna(0).astype(int)

        insert_cols = ["pattern_id", "run_id", "view", "horizon", "outcome_type", "split",
                      "n_occurrences", "mean_fwd_return", "baseline_mean", "hit_rate",
                      "baseline_hit_rate", "effect", "p_value", "q_value", "ci_low", "ci_high",
                      "breadth_stocks", "breadth_years", "passed"]
        for _, row in df.iterrows():
            insert_result(conn, {k: (None if pd.isna(row[k]) else row[k]) for k in insert_cols})
        conn.commit()

    n_passed_disc = int(df.loc[disc_mask, "passed"].sum()) if results else 0
    print(f"Tested {tested} bucket/view/split combinations, {len(results)} had enough occurrences")
    print(f"Discovery-period patterns passing 5% FDR: {n_passed_disc}")
    if results:
        top = df[disc_mask & (df["passed"] == 1)].sort_values("effect", key=abs, ascending=False)
        cols = ["view", "n_occurrences", "mean_fwd_return", "baseline_mean", "effect", "p_value",
               "breadth_stocks", "breadth_years"]
        print("\nTop discovery-period survivors (by |effect|):")
        with pd.option_context("display.width", 140):
            print(pd.concat([top[cols], df.loc[top.index, "pattern_id"]], axis=1)
                  .merge(pd.read_sql("SELECT pattern_id, description FROM patterns", conn),
                         on="pattern_id").head(15).to_string(index=False))


if __name__ == "__main__":
    main()