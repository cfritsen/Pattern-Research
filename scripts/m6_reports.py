import argparse
import json
from pathlib import Path
import pandas as pd
import numpy as np
from patternlab.config import load_config, ensure_dirs, report_dir_for
from patternlab.db import connect
from patternlab.humanize import humanize_pattern_view, humanize_stock_view

DISCLAIMER = ("This report shows historical statistical patterns in price data. It is "
             "descriptive research, not investment advice, and not a recommendation to "
             "buy or sell any security. Patterns are reported as \u201cfollowed by\u201d a "
             "historical outcome, never as a cause. Past patterns may not repeat. Trading "
             "involves risk of loss; you are solely responsible for your own decisions.")


def load_single_condition_lookup(conn) -> dict:
    """(feature, bucket, view) -> effect, from the latest single-condition
    (n_conditions=1) run's discovery-period results."""
    df = pd.read_sql(
        "SELECT p.conditions_json, r.view, r.effect FROM pattern_results_pooled r "
        "JOIN patterns p ON p.pattern_id = r.pattern_id "
        "WHERE r.split='discovery' AND p.n_conditions = 1 "
        "AND r.run_id = (SELECT MAX(run_id) FROM runs WHERE n_conditions = 1)", conn)
    lookup = {}
    for _, row in df.iterrows():
        c = json.loads(row["conditions_json"])[0]
        lookup[(c["feature"], c["bucket"], row["view"])] = row["effect"]
    return lookup


def best_single(conditions: list[dict], view: str, lookup: dict):
    candidates = []
    for c in conditions:
        e = lookup.get((c["feature"], c["bucket"], view))
        if e is not None:
            candidates.append((e, c["feature"], c["bucket"]))
    if not candidates or len(conditions) < 2:
        return None
    return max(candidates, key=lambda t: abs(t[0]))


def build_pattern_context(conn) -> pd.DataFrame:
    """One row per pattern_id (index), covering every metric the reports need,
    for both views, unfiltered by top-N -- shared by the whole-market table
    and the per-stock table so both draw from the same numbers."""
    qualifying = pd.read_sql(
        "SELECT DISTINCT pattern_id FROM pattern_results_pooled WHERE split='discovery' AND passed=1", conn)
    ids = tuple(qualifying["pattern_id"].tolist())
    if not ids:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in ids)
    df = pd.read_sql(
        f"SELECT r.pattern_id, p.description, p.conditions_json, r.view, r.split, r.passed, "
        f"r.n_occurrences, r.mean_fwd_return, r.baseline_mean, r.effect, r.q_value, "
        f"r.breadth_stocks, r.breadth_years, r.overlap_ratio, r.top3_year_share, r.mean_excl_top3 "
        f"FROM pattern_results_pooled r JOIN patterns p ON p.pattern_id = r.pattern_id "
        f"WHERE r.pattern_id IN ({placeholders})", conn, params=ids)

    lookup = load_single_condition_lookup(conn)
    disc = df[df["split"] == "discovery"].copy()
    conf = df[df["split"] == "confirm"].set_index(["pattern_id", "view"])["mean_fwd_return"]
    disc["confirm_mean_fwd_return"] = disc.set_index(["pattern_id", "view"]).index.map(conf)

    all_rows = disc[disc["view"] == "all"].set_index("pattern_id")
    flagged_rows = disc[disc["view"] == "flagged"].set_index("pattern_id")
    common = all_rows.index.union(flagged_rows.index)
    all_rows = all_rows.reindex(common)
    flagged_rows = flagged_rows.reindex(common)

    merged = pd.DataFrame(index=common)
    merged["description"] = all_rows["description"].combine_first(flagged_rows["description"])
    merged["conditions_json"] = all_rows["conditions_json"].combine_first(flagged_rows["conditions_json"])
    merged["n_all"] = all_rows["n_occurrences"]
    merged["n_flagged"] = flagged_rows["n_occurrences"]
    passed_all = all_rows["passed"].fillna(0).astype(bool)
    passed_flagged = flagged_rows["passed"].fillna(0).astype(bool)

    for col in ["mean_fwd_return", "baseline_mean", "effect", "confirm_mean_fwd_return",
               "q_value", "breadth_stocks", "breadth_years"]:
        merged[f"{col}_all"] = all_rows[col].where(passed_all)
        merged[f"{col}_flagged"] = flagged_rows[col].where(passed_flagged)

    merged["overlap_ratio"] = all_rows["overlap_ratio"].where(passed_all).combine_first(
        flagged_rows["overlap_ratio"].where(passed_flagged))
    merged["top3_year_share"] = all_rows["top3_year_share"].where(passed_all).combine_first(
        flagged_rows["top3_year_share"].where(passed_flagged))
    merged["mean_excl_top3"] = all_rows["mean_excl_top3"].where(passed_all).combine_first(
        flagged_rows["mean_excl_top3"].where(passed_flagged))
    merged["reference_mean"] = all_rows["mean_fwd_return"].where(passed_all).combine_first(
        flagged_rows["mean_fwd_return"].where(passed_flagged))

    best_all, best_flagged = [], []
    for pid, row in merged.iterrows():
        conds = json.loads(row["conditions_json"])
        best_all.append(best_single(conds, "all", lookup))
        best_flagged.append(best_single(conds, "flagged", lookup))
    merged["best_single_all"] = best_all
    merged["best_single_flagged"] = best_flagged

    merged["rank_key"] = merged[["effect_all", "effect_flagged"]].abs().max(axis=1)
    return merged


def pattern_view(context: pd.DataFrame, top_n: int, worst: bool = False) -> pd.DataFrame:
    kept = context[context.apply(passes_direction_filter, axis=1)]
    if worst:
        def signed_rank(row):
            vals = [v for v in (row["effect_all"], row["effect_flagged"]) if pd.notna(v)]
            return min(vals) if vals else np.nan
        kept = kept.assign(signed_rank=kept.apply(signed_rank, axis=1))
        kept = kept[kept["signed_rank"] < 0]
        return kept.sort_values("signed_rank", ascending=True).head(top_n).reset_index(drop=True)
    return kept.sort_values("rank_key", ascending=False).head(top_n).reset_index(drop=True)


def stock_view(conn, ticker: str, context: pd.DataFrame, top_n: int) -> pd.DataFrame:
    by_stock = pd.read_sql(
        "SELECT pattern_id, view, n, mean_fwd_return, hit_rate, effect "
        "FROM pattern_results_by_stock WHERE ticker = ? AND split = 'full'", conn, params=(ticker,))
    if by_stock.empty:
        return pd.DataFrame()

    all_rows = by_stock[by_stock["view"] == "all"].set_index("pattern_id")
    flagged_rows = by_stock[by_stock["view"] == "flagged"].set_index("pattern_id")
    common = all_rows.index.union(flagged_rows.index).intersection(context.index)
    all_rows = all_rows.reindex(common)
    flagged_rows = flagged_rows.reindex(common)
    ctx = context.reindex(common)
    # A truly missing row here (vs. a small-but-present count) means the
    # ticker had zero occurrences in that view for this pattern -- not
    # unknown data. n_all should never be the missing side, since every
    # flagged occurrence is by definition also an "all" occurrence.
    all_rows["n"] = all_rows["n"].fillna(0)
    flagged_rows["n"] = flagged_rows["n"].fillna(0)

    out = pd.DataFrame(index=common)
    out["description"] = ctx["description"]
    out["n_all"] = all_rows["n"]
    out["n_flagged"] = flagged_rows["n"]
    out["mean_fwd_return_all"] = all_rows["mean_fwd_return"]
    out["mean_fwd_return_flagged"] = flagged_rows["mean_fwd_return"]
    out["hit_rate_all"] = all_rows["hit_rate"]
    out["hit_rate_flagged"] = flagged_rows["hit_rate"]
    out["stock_effect_all"] = all_rows["effect"]
    out["stock_effect_flagged"] = flagged_rows["effect"]
    out["baseline_mean_all"] = ctx["baseline_mean_all"]
    out["baseline_mean_flagged"] = ctx["baseline_mean_flagged"]
    out["edge_all"] = out["mean_fwd_return_all"] - out["baseline_mean_all"]
    out["edge_flagged"] = out["mean_fwd_return_flagged"] - out["baseline_mean_flagged"]
    out["best_single_all"] = ctx["best_single_all"]
    out["best_single_flagged"] = ctx["best_single_flagged"]
    out["overlap_ratio"] = ctx["overlap_ratio"]
    out["top3_year_share"] = ctx["top3_year_share"]
    out["mean_excl_top3"] = ctx["mean_excl_top3"]
    out["reference_mean"] = ctx["reference_mean"]
    out["rank_key"] = out[["mean_fwd_return_all", "mean_fwd_return_flagged"]].abs().max(axis=1)

    return out.sort_values("rank_key", ascending=False).head(top_n).reset_index(drop=True)


def to_html(pattern_df: pd.DataFrame, worst_df: pd.DataFrame, stock_df: pd.DataFrame,
           ticker: str | None, edges_by_feature: dict[str, list[float]]) -> str:
    friendly_p = humanize_pattern_view(pattern_df, edges_by_feature)
    friendly_w = humanize_pattern_view(worst_df, edges_by_feature) if len(worst_df) else None
    friendly_s = humanize_stock_view(stock_df, edges_by_feature) if ticker and len(stock_df) else None
    parts = [
        "<html><head><meta charset='utf-8'><title>Pattern Research Report</title><style>",
        "body{font-family:sans-serif;max-width:1400px;margin:2em auto}",
        "table{border-collapse:collapse;width:100%;font-size:0.8em}",
        "td,th{border:1px solid #ccc;padding:5px 8px;text-align:right;vertical-align:top}",
        "th{background:#eee}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}",
        ".note{background:#fff3cd;padding:0.75em;margin:1em 0;border-radius:4px}",
        ".cond{padding:2px 0;border-left:3px solid #ccc;padding-left:6px;margin-bottom:3px}",
        ".key{font-style:italic;color:#555;margin:0.25em 0 0.75em}",
        "</style></head><body><h1>Market Pattern Research Report</h1>",
        f"<div class='note'><b>{DISCLAIMER}</b></div>",
        "<h2>Strongest historical results (whole market)</h2>",
        "<p class='key'>Each pair of numbers shows: All Data / Index-Only Data. "
        "\u201c--\u201d means that view did not pass this pattern's statistical filters, "
        "or there wasn't enough data to check. \u201cPre-Index Bias\u201d is the share of a "
        "pattern's \u2018All Data\u2019 cases that happened before the stock had actually "
        "joined the S&P 500.</p>",
        friendly_p.to_html(index=False, escape=False)]
    if friendly_w is not None:
        parts += ["<h2>Weakest historical results (whole market)</h2>",
                 "<p class='key'>Patterns whose historical result was negative and stayed "
                 "negative on newer data. Same columns and rules as above.</p>",
                 friendly_w.to_html(index=False, escape=False)]
    if ticker and friendly_s is not None:
        parts += [f"<h2>Strongest historical results for {ticker}</h2>",
                 friendly_s.to_html(index=False, escape=False)]
    parts.append("</body></html>")
    return "\n".join(parts)

def same_direction(discovery_val, confirm_val) -> bool:
    """True if both are present and share a sign (reduced magnitude is fine,
    a sign flip is not). Missing confirm data (NaN) doesn't fail the check --
    there's nothing to contradict."""
    if pd.isna(discovery_val) or pd.isna(confirm_val):
        return True
    return (discovery_val >= 0) == (confirm_val >= 0)


def passes_direction_filter(row) -> bool:
    """Only checks a view's confirm sign against its own discovery edge if
    that view actually passed the statistical filters (has a non-NaN edge) --
    a view the pattern never passed on doesn't get to veto it."""
    ok_all = True
    if pd.notna(row["effect_all"]):
        ok_all = same_direction(row["effect_all"], row["confirm_mean_fwd_return_all"] -
                                row["baseline_mean_all"] if pd.notna(row["confirm_mean_fwd_return_all"]) else np.nan)
    ok_flagged = True
    if pd.notna(row["effect_flagged"]):
        ok_flagged = same_direction(row["effect_flagged"], row["confirm_mean_fwd_return_flagged"] -
                                    row["baseline_mean_flagged"] if pd.notna(row["confirm_mean_fwd_return_flagged"]) else np.nan)
    return ok_all and ok_flagged

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    if args.ticker:
        args.ticker = args.ticker.upper()

    cfg = load_config()
    ensure_dirs(cfg)
    conn = connect(cfg)

    edges_by_feature: dict[str, list[float]] = {}
    for feat, idx, val in conn.execute(
            "SELECT feature, edge_index, edge_value FROM feature_bucket_edges ORDER BY feature, edge_index"):
        edges_by_feature.setdefault(feat, []).append(val)

    context = build_pattern_context(conn)
    pdf = pattern_view(context, args.top)
    wdf = pattern_view(context, args.top, worst=True)
    sdf = stock_view(conn, args.ticker, context, 5) if args.ticker else pd.DataFrame()

    out_dir = report_dir_for(cfg)
    pdf.to_csv(out_dir / "pattern_view.csv", index=False)
    wdf.to_csv(out_dir / "pattern_view_worst.csv", index=False)
    if args.ticker:
        sdf.to_csv(out_dir / f"stock_view_{args.ticker}.csv", index=False)
    (out_dir / "report.html").write_text(to_html(pdf, wdf, sdf, args.ticker, edges_by_feature), encoding="utf-8")

    print(f"Wrote {out_dir / 'pattern_view.csv'} ({len(pdf)} rows)")
    print(f"Wrote {out_dir / 'pattern_view_worst.csv'} ({len(wdf)} rows)")
    if args.ticker:
        print(f"Wrote {out_dir / f'stock_view_{args.ticker}.csv'} ({len(sdf)} rows)")
    print(f"Wrote {out_dir / 'report.html'}")


if __name__ == "__main__":
    main()