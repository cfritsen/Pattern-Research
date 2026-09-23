import json
from pathlib import Path
import numpy as np
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.buckets import CATEGORICAL
from patternlab.search import load_panel, build_buckets, evaluate_condition
from patternlab.correlation import spearman_matrix, prune_pairs
from patternlab.overlap import bucket_overlap_ratio
from patternlab.stats import benjamini_hochberg, bh_qvalues
from patternlab.db import connect, insert_run, get_or_create_pattern, insert_result

OVERLAP_FLAG = 1.5


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    cost = cfg.get("cost", 0.001)
    corr_threshold = cfg.get("corr_prune_threshold", 0.7)
    extremes_only = not cfg.get("test_all_buckets", False)

    panel, feature_cols = load_panel(cfg, uni)
    is_disc = panel[f"split_{h0}"] == 0
    is_conf = panel[f"split_{h0}"] == 1
    buckets, _ = build_buckets(panel, feature_cols, is_disc)

    continuous = [c for c in buckets.columns if c not in CATEGORICAL]
    rho = spearman_matrix(panel, continuous, is_disc)
    pairs_to_test, pruned = prune_pairs(rho, corr_threshold)
    categorical = [c for c in buckets.columns if c in CATEGORICAL]
    pruned_set = {(a, b) for a, b, _ in pruned}
    for c in categorical:
        for other in buckets.columns:
            if other == c:
                continue
            pair = tuple(sorted((c, other)))
            if pair not in pruned_set:
                pairs_to_test.append(pair)
    pairs_to_test = sorted({tuple(sorted(p)) for p in pairs_to_test})

    manifest = json.loads((Path(cfg["data_dir"]) / "manifest.json").read_text())
    conn = connect(cfg)
    run_id = insert_run(conn, {"horizon": h0, "move_atr": cfg["move_atr"], "n_conditions": 2,
                               "corr_prune_threshold": corr_threshold, "extremes_only": extremes_only},
                        manifest["data_version"], manifest["universe_snapshot"])

    for a, b, r in pruned:
        conn.execute("INSERT INTO feature_correlations (run_id, feature_a, feature_b, spearman_rho, pruned) "
                     "VALUES (?, ?, ?, ?, 1)", (run_id, a, b, r))
    for a, b in pairs_to_test:
        r = float(rho.loc[a, b]) if a in rho.columns and b in rho.columns else None
        conn.execute("INSERT INTO feature_correlations (run_id, feature_a, feature_b, spearman_rho, pruned) "
                     "VALUES (?, ?, ?, ?, 0)", (run_id, a, b, r))
    conn.commit()
    print(f"{len(pairs_to_test)} feature pairs to test, {len(pruned)} pruned at |rho| > {corr_threshold}")

    bucket_labels = {}
    for c in buckets.columns:
        n_labels = int(buckets[c].max() + 1) if buckets[c].notna().any() else 0
        labels = list(range(n_labels))
        if c not in CATEGORICAL and extremes_only and n_labels == 5:
            labels = [0, 4]
        bucket_labels[c] = labels

    results, tested = [], 0
    for view, vmask in (("all", pd.Series(True, index=panel.index)), ("flagged", panel["in_index"])):
        market_by_split = {
            split_name: panel[vmask & smask][[f"fwd_ret_{h0}", "date"]].rename(
                columns={f"fwd_ret_{h0}": "fwd_ret"}).groupby("date").mean()
            for split_name, smask in (("discovery", is_disc), ("confirm", is_conf))
        }
        for a, b in pairs_to_test:
            for la in bucket_labels[a]:
                for lb in bucket_labels[b]:
                    mask_ab = vmask & (buckets[a] == la) & (buckets[b] == lb)
                    for split_name, smask in (("discovery", is_disc), ("confirm", is_conf)):
                        sub = panel[mask_ab & smask]
                        market_sub = market_by_split[split_name]
                        tested += 1
                        res = evaluate_condition(sub, market_sub, view, h0, cost)
                        if res is None:
                            continue
                        scope = vmask & smask
                        ov = bucket_overlap_ratio(buckets[a], la, buckets[b], lb, scope)
                        tag = " [overlapping conditions]" if (not np.isnan(ov) and
                              (ov > OVERLAP_FLAG or ov < 1 / OVERLAP_FLAG)) else ""
                        desc = f"{a} in bucket {la} AND {b} in bucket {lb}{tag}"
                        pid = get_or_create_pattern(conn, desc,
                                                    [{"feature": a, "bucket": int(la)}, {"feature": b, "bucket": int(lb)}])
                        res.update(pattern_id=pid, run_id=run_id, view=view, horizon=h0, outcome_type="direction",
                                  split=split_name, overlap_ratio=ov, passed=0, q_value=None, baseline_hit_rate=None)
                        results.append(res)

    print(f"Tested {tested} 2-condition combinations, {len(results)} had enough occurrences")
    df2 = pd.DataFrame(results)

    # --- joint FDR across M4's stored discovery p-values and these new ones ---
    old = pd.read_sql(
        "SELECT result_id, pattern_id, p_value, breadth_stocks, breadth_years, effect "
        "FROM pattern_results_pooled WHERE split='discovery' "
        "AND run_id = (SELECT MAX(run_id) FROM runs WHERE n_conditions = 1)", conn)
    n_old = len(old)
    disc2 = df2[df2["split"] == "discovery"] if len(df2) else pd.DataFrame(columns=["p_value"])
    combined_p = np.concatenate([old["p_value"].to_numpy(), disc2["p_value"].to_numpy()])
    q_all = bh_qvalues(combined_p)
    passed_all = benjamini_hochberg(combined_p, q=0.05)

    old["q_value"] = q_all[:n_old]
    old["final_pass"] = [int(p and old["breadth_stocks"].iloc[i] >= 0.6 and old["breadth_years"].iloc[i] >= 0.6
                            and abs(old["effect"].iloc[i]) > cost)
                         for i, p in enumerate(passed_all[:n_old])]
    for _, r in old.iterrows():
        conn.execute("UPDATE pattern_results_pooled SET q_value=?, passed=? WHERE result_id=?",
                     (float(r["q_value"]), int(r["final_pass"]), int(r["result_id"])))
    conn.execute("""
        UPDATE pattern_results_pooled SET passed = (
            SELECT passed FROM pattern_results_pooled p2
            WHERE p2.pattern_id = pattern_results_pooled.pattern_id AND p2.split='discovery'
              AND p2.run_id = (SELECT MAX(run_id) FROM runs WHERE n_conditions = 1))
        WHERE split='confirm' AND run_id = (SELECT MAX(run_id) FROM runs WHERE n_conditions = 1)
    """)

    if len(df2):
        disc_idx = df2.index[df2["split"] == "discovery"]
        df2.loc[disc_idx, "q_value"] = q_all[n_old:]
        fdr_pass = passed_all[n_old:]
        final_pass = [int(p and df2.loc[i, "breadth_stocks"] >= 0.6 and df2.loc[i, "breadth_years"] >= 0.6
                          and abs(df2.loc[i, "effect"]) > cost)
                     for i, p in zip(disc_idx, fdr_pass)]
        df2.loc[disc_idx, "passed"] = final_pass
        pass_map = dict(zip(df2.loc[disc_idx, "pattern_id"], final_pass))
        conf_idx = df2.index[df2["split"] == "confirm"]
        df2.loc[conf_idx, "passed"] = df2.loc[conf_idx, "pattern_id"].map(pass_map).fillna(0).astype(int)

        insert_cols = ["pattern_id", "run_id", "view", "horizon", "outcome_type", "split", "n_occurrences",
                      "mean_fwd_return", "baseline_mean", "hit_rate", "baseline_hit_rate", "effect", "p_value",
                      "q_value", "ci_low", "ci_high", "breadth_stocks", "breadth_years", "overlap_ratio", "passed"]
        for _, row in df2.iterrows():
            insert_result(conn, {k: (None if (k not in row or pd.isna(row[k])) else row[k]) for k in insert_cols})
    conn.commit()

    n_passed = int(df2.loc[df2["split"] == "discovery", "passed"].sum()) if len(df2) else 0
    print(f"2-condition discovery patterns passing FDR + breadth + cost: {n_passed}")
    if n_passed:
        top = df2[(df2["split"] == "discovery") & (df2["passed"] == 1)].copy()
        top["abs_effect"] = top["effect"].abs()
        top = top.sort_values("abs_effect", ascending=False).head(15)
        desc = pd.read_sql("SELECT pattern_id, description FROM patterns", conn)
        top = top.merge(desc, on="pattern_id")
        cols = ["view", "n_occurrences", "mean_fwd_return", "baseline_mean", "effect", "p_value",
               "overlap_ratio", "breadth_stocks", "breadth_years", "description"]
        with pd.option_context("display.width", 160):
            print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()