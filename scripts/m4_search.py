import json
from pathlib import Path
import numpy as np
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.buckets import bucket_feature, CATEGORICAL
from patternlab.stats import thin_non_overlapping, cluster_bootstrap_pvalue, benjamini_hochberg, breadth
from patternlab.db import connect, insert_run, get_or_create_pattern, insert_result
from patternlab.search import load_panel, evaluate_condition, MIN_OCCURRENCES, COST


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    panel, feature_cols = load_panel(cfg, uni)
    is_disc = panel[f"split_{h0}"] == 0
    is_conf = panel[f"split_{h0}"] == 1

    manifest = json.loads((Path(cfg["data_dir"]) / "manifest.json").read_text())
    conn = connect(cfg)
    run_id = insert_run(conn, {"horizon": h0, "move_atr": cfg["move_atr"], "n_conditions": 1},
                        manifest["data_version"], manifest["universe_snapshot"])

    bucket_frames, edge_log = {}, {}
    for col in feature_cols:
        if col.startswith(("fwd_ret_", "split_")):
            continue
        b, edges = bucket_feature(panel[col], is_disc)
        bucket_frames[col] = b
        edge_log[col] = edges
    buckets = pd.DataFrame(bucket_frames)

    results, tested = [], 0
    for view, vmask in (("all", pd.Series(True, index=panel.index)),
                        ("flagged", panel["in_index"])):
        for col in buckets.columns:
            n_labels = 5 if col not in CATEGORICAL else int(buckets[col].max() + 1)
            for label in range(n_labels):
                mask = vmask & (buckets[col] == label)
                for split_name, smask in (("discovery", is_disc), ("confirm", is_conf)):
                    sub = panel[mask & smask]
                    market_sub = panel[vmask & smask][[f"fwd_ret_{h0}", "date"]].rename(
                        columns={f"fwd_ret_{h0}": "fwd_ret"}).groupby("date").mean()
                    tested += 1
                    r = evaluate_condition(sub, market_sub, view, h0, cfg.get("cost", COST))
                    if r is None:
                        continue
                    desc = f"{col} in bucket {label}"
                    pid = get_or_create_pattern(conn, desc, [{"feature": col, "bucket": int(label)}])
                    r.update(pattern_id=pid, run_id=run_id, view=view, horizon=h0,
                            outcome_type="direction", split=split_name, passed=0, q_value=None)
                    results.append(r)

    if results:
        df = pd.DataFrame(results)
        disc_mask = df["split"] == "discovery"
        q = np.full(len(df), np.nan)
        q[disc_mask.to_numpy()] = np.nan  # placeholder; BH computed below on discovery p-values only
        pv = df.loc[disc_mask, "p_value"].to_numpy()
        passed = benjamini_hochberg(pv, q=0.05)
        df.loc[disc_mask, "passed"] = passed.astype(int)
        # propagate discovery pass/fail to the matching confirm row of the same pattern/view
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