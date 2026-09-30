import json
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.search import load_panel, build_buckets, evaluate_condition
from patternlab.exit_timing import exit_day_mask
from patternlab.db import connect

TOP_N = 10


def condition_mask(buckets: pd.DataFrame, conditions: list[dict]) -> pd.Series:
    mask = pd.Series(True, index=buckets.index)
    for c in conditions:
        mask &= (buckets[c["feature"]] == c["bucket"])
    return mask


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    h0 = cfg["horizon"]
    cost = cfg.get("cost", 0.001)
    panel, feature_cols = load_panel(cfg, uni)
    is_disc = panel[f"split_{h0}"] == 0
    buckets, _ = build_buckets(panel, feature_cols, is_disc)
    view_masks = {"all": pd.Series(True, index=panel.index), "flagged": panel["in_index"]}

    conn = connect(cfg)
    top = pd.read_sql(
        "SELECT r.pattern_id, r.view, r.effect AS entry_effect, r.n_occurrences AS entry_n, "
        "p.description, p.conditions_json FROM pattern_results_pooled r "
        "JOIN patterns p ON p.pattern_id = r.pattern_id "
        "WHERE r.split='discovery' AND r.passed=1 ORDER BY ABS(r.effect) DESC LIMIT ?",
        conn, params=(TOP_N,))

    print(f"Entry-day (as currently defined) vs. exit-day (first day the pattern is no longer true), "
         f"discovery period, top {len(top)} passed patterns:\n")

    market_by_view = {
        view: panel[vmask & is_disc][[f"fwd_ret_{h0}", "date"]].rename(
            columns={f"fwd_ret_{h0}": "fwd_ret"}).groupby("date").mean()
        for view, vmask in view_masks.items()
    }

    rows = []
    for _, row in top.iterrows():
        conds = json.loads(row["conditions_json"])
        vmask = view_masks[row["view"]]
        entry_mask = vmask & is_disc & condition_mask(buckets, conds)
        exits = exit_day_mask(condition_mask(buckets, conds), panel["ticker"], panel["bar_pos"])
        exit_mask = vmask & is_disc & exits

        entry_sub = panel[entry_mask]
        exit_sub = panel[exit_mask]
        entry_res = evaluate_condition(entry_sub, market_by_view[row["view"]], row["view"], h0, cost)
        exit_res = evaluate_condition(exit_sub, market_by_view[row["view"]], row["view"], h0, cost)

        rows.append({
            "description": row["description"], "view": row["view"],
            "entry_n": row["entry_n"], "entry_effect": row["entry_effect"],
            "exit_n": exit_res["n_occurrences"] if exit_res else 0,
            "exit_effect": exit_res["effect"] if exit_res else float("nan"),
            "exit_note": "" if exit_res else "below minimum occurrences after exit-day thinning",
        })

    out = pd.DataFrame(rows)
    with pd.option_context("display.width", 160, "display.float_format", lambda x: f"{x:+.4f}"):
        print(out.to_string(index=False))


if __name__ == "__main__":
    main()