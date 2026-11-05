import json
import numpy as np
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.search import load_panel, build_buckets, MIN_PER_STOCK
from patternlab.stats import thin_non_overlapping
from patternlab.regime import year_breakdown
from patternlab.by_stock import per_stock_breakdown
from patternlab.db import connect
from patternlab.clusters import pack, cluster_patterns, CLUSTER_JACCARD


def condition_mask(buckets: pd.DataFrame, conditions: list[dict]) -> pd.Series:
    mask = pd.Series(True, index=buckets.index)
    for c in conditions:
        mask &= (buckets[c["feature"]] == c["bucket"])
    return mask


def store_by_stock(conn, thin, h0, pattern_id, run_id, view, split):
    by_stock = per_stock_breakdown(thin, h0, MIN_PER_STOCK)
    for ticker, r in by_stock.iterrows():
        mean = None if pd.isna(r["mean"]) else float(r["mean"])
        hit = None if pd.isna(r["hit_rate"]) else float(r["hit_rate"])
        effect = None if pd.isna(r["effect"]) else float(r["effect"])
        conn.execute(
            "INSERT INTO pattern_results_by_stock "
            "(pattern_id, run_id, ticker, view, horizon, split, n, mean_fwd_return, hit_rate, effect) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(pattern_id), int(run_id), ticker, view, h0, split,
             int(r["n"]), mean, hit, effect))


def store_clusters(conn, buckets: pd.DataFrame, is_disc: pd.Series) -> None:
    """Group passed patterns that fire on mostly the same days (reporting only;
    see clusters.py). Uses the discovery-period, All Data occurrences."""
    rows = conn.execute(
        "SELECT p.pattern_id, p.conditions_json, MAX(ABS(r.effect)) "
        "FROM pattern_results_pooled r JOIN patterns p ON p.pattern_id = r.pattern_id "
        "WHERE r.split='discovery' AND r.passed=1 GROUP BY p.pattern_id").fetchall()
    d = is_disc.to_numpy()
    packed, strength = {}, {}
    for pid, cj, eff in rows:
        # a day with no bucket value (indicator warm-up) doesn't match the pattern
        m = condition_mask(buckets, json.loads(cj)).fillna(False).to_numpy(dtype=bool) & d
        packed[int(pid)] = pack(m[d])
        strength[int(pid)] = 0.0 if eff is None else float(eff)
    conn.execute("DELETE FROM pattern_clusters")
    if packed:
        cl = cluster_patterns(packed, strength, CLUSTER_JACCARD)
        conn.executemany(
            "INSERT INTO pattern_clusters (pattern_id, cluster_id, is_lead, cluster_size, jaccard) VALUES (?, ?, ?, ?, ?)",
            [(int(r.pattern_id), int(r.cluster_id), int(r.is_lead), int(r.cluster_size), float(r.jaccard))
             for r in cl.itertuples()])
        print(f"Grouped {len(cl)} passed patterns into {cl['cluster_id'].nunique()} groups "
              f"(overlap >= {CLUSTER_JACCARD:.0%} of days)")


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    panel, feature_cols = load_panel(cfg, uni)
    is_disc = panel[f"split_{h0}"] == 0
    buckets, edges = build_buckets(panel, feature_cols, is_disc)
    view_masks = {"all": pd.Series(True, index=panel.index), "flagged": panel["in_index"]}

    conn = connect(cfg)

    conn.execute("DELETE FROM feature_bucket_edges")
    for feat, edge_list in edges.items():
        for i, v in enumerate(edge_list):
            conn.execute("INSERT INTO feature_bucket_edges (feature, edge_index, edge_value) VALUES (?, ?, ?)",
                        (feat, i, float(v)))
    conn.commit()
    print(f"Stored bucket edges for {len(edges)} features")

    passed = pd.read_sql(
        "SELECT result_id, pattern_id, run_id, view FROM pattern_results_pooled "
        "WHERE split='discovery' AND passed=1", conn)
    patterns = pd.read_sql("SELECT pattern_id, conditions_json FROM patterns", conn)
    passed = passed.merge(patterns, on="pattern_id")
    print(f"Post-processing {len(passed)} passed discovery-period patterns...")

    conn.execute("DELETE FROM pattern_results_by_stock")
    for _, row in passed.iterrows():
        conditions = json.loads(row["conditions_json"])
        base_mask = view_masks[row["view"]] & condition_mask(buckets, conditions)

        # Year-concentration diagnostic stays discovery-period only, matching
        # the whole-market table -- unchanged from before.
        disc_sub = panel[base_mask & is_disc]
        keep_d = thin_non_overlapping(disc_sub["bar_pos"], disc_sub["ticker"], h0)
        disc_thin = disc_sub[keep_d]
        top3_share, mean_excl = year_breakdown(disc_thin, h0)
        conn.execute("UPDATE pattern_results_pooled SET top3_year_share=?, mean_excl_top3=? WHERE result_id=?",
                     (top3_share, mean_excl, int(row["result_id"])))

        # Per-stock breakdown uses FULL history (discovery + confirm combined),
        # not the 70/30 split -- at single-stock scale, 30% of an already
        # narrow pattern's occurrences is too thin to report meaningfully.
        # The pooled, whole-market out-of-sample check still uses the 70/30
        # split, where the sample size makes it meaningful. Thinning runs once
        # across the full timeline rather than once per split, which also
        # closes a small gap: two occurrences straddling the old discovery/
        # confirm boundary could previously both survive thinning even if
        # fewer than `horizon` bars apart.
        full_sub = panel[base_mask]
        keep_f = thin_non_overlapping(full_sub["bar_pos"], full_sub["ticker"], h0)
        full_thin = full_sub[keep_f]
        store_by_stock(conn, full_thin, h0, row["pattern_id"], row["run_id"], row["view"], "full")
    conn.commit()
    store_clusters(conn, buckets, is_disc)
    conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()