import json
from pathlib import Path
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.search import load_panel, build_buckets
from patternlab.stats import thin_non_overlapping
from patternlab.db import connect

TOP_N = 15


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    panel, feature_cols = load_panel(cfg, uni)
    is_disc = panel[f"split_{h0}"] == 0
    buckets, _ = build_buckets(panel, feature_cols, is_disc)

    conn = connect(cfg)
    run_id = conn.execute("SELECT MAX(run_id) FROM runs WHERE n_conditions = 2").fetchone()[0]
    rows = pd.read_sql(f"""
        SELECT r.pattern_id, r.view, r.effect, r.n_occurrences, p.description, p.conditions_json
        FROM pattern_results_pooled r JOIN patterns p ON p.pattern_id = r.pattern_id
        WHERE r.run_id = {run_id} AND r.split = 'discovery' AND r.passed = 1
        ORDER BY ABS(r.effect) DESC LIMIT {TOP_N}
    """, conn)

    view_masks = {"all": pd.Series(True, index=panel.index), "flagged": panel["in_index"]}
    year_sets = {}
    print(f"Year breakdown for the top {len(rows)} passed 2-condition discovery patterns:\n")
    for _, row in rows.iterrows():
        conds = json.loads(row["conditions_json"])
        mask = view_masks[row["view"]] & is_disc
        for c in conds:
            mask &= (buckets[c["feature"]] == c["bucket"])
        sub = panel[mask]
        keep = thin_non_overlapping(sub["bar_pos"], sub["ticker"], h0)
        thin = sub[keep]
        by_year = thin.groupby("year")[f"fwd_ret_{h0}"].agg(["count", "mean"]).sort_values("count", ascending=False)
        top3_share = by_year["count"].head(3).sum() / by_year["count"].sum() if len(by_year) else float("nan")
        label = f"{row['description']} (view={row['view']})"
        print(f"{label}\n  n={int(row['n_occurrences'])}  effect={row['effect']:+.4f}  "
              f"top-3-years share of occurrences: {top3_share:.0%}\n"
              f"  years present: {sorted(by_year.index.tolist())}\n")
        year_sets[label] = set(by_year.index)

    all_years = sorted(set().union(*year_sets.values())) if year_sets else []
    overlap = pd.DataFrame(0, index=year_sets.keys(), columns=all_years)
    for label, years in year_sets.items():
        overlap.loc[label, list(years)] = 1
    print("Presence matrix (1 = this pattern had occurrences that year) -- "
          "columns where most rows are 1 mean several 'different' top patterns are leaning on the same years:")
    with pd.option_context("display.width", 220, "display.max_columns", 50):
        print(overlap)


if __name__ == "__main__":
    main()