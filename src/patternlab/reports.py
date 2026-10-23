from __future__ import annotations
from patternlab.humanize import conditions_html, describe_bucket
import json
import numpy as np
import pandas as pd

def fmt_pct_sign(v) -> str:
    return f"{v:+.2%}"

def load_single_condition_lookup(conn) -> dict:
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
    qualifying = pd.read_sql(
        "SELECT DISTINCT pattern_id FROM pattern_results_pooled WHERE split='discovery' AND passed=1 "
        "AND run_id IN (SELECT MAX(run_id) FROM runs WHERE n_conditions=1 "
        "UNION SELECT MAX(run_id) FROM runs WHERE n_conditions=2)", conn)
    ids = tuple(qualifying["pattern_id"].tolist())
    if not ids:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in ids)
    df = pd.read_sql(
        f"SELECT r.pattern_id, p.description, p.conditions_json, r.view, r.split, r.passed, "
        f"r.n_occurrences, r.mean_fwd_return, r.baseline_mean, r.effect, r.q_value, "
        f"r.breadth_stocks, r.breadth_years, r.overlap_ratio, r.top3_year_share, r.mean_excl_top3 "
        f"FROM pattern_results_pooled r JOIN patterns p ON p.pattern_id = r.pattern_id "
        f"WHERE r.pattern_id IN ({placeholders}) "
        f"AND r.run_id IN (SELECT MAX(run_id) FROM runs WHERE n_conditions=1 "
        f"UNION SELECT MAX(run_id) FROM runs WHERE n_conditions=2)", conn, params=ids)

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


def same_direction(discovery_val, confirm_val) -> bool:
    if pd.isna(discovery_val) or pd.isna(confirm_val):
        return True
    return (discovery_val >= 0) == (confirm_val >= 0)


def passes_direction_filter(row) -> bool:
    ok_all = True
    if pd.notna(row["effect_all"]):
        c = row["confirm_mean_fwd_return_all"]
        ok_all = same_direction(row["effect_all"],
                                (c - row["baseline_mean_all"]) if pd.notna(c) else np.nan)
    ok_flagged = True
    if pd.notna(row["effect_flagged"]):
        c = row["confirm_mean_fwd_return_flagged"]
        ok_flagged = same_direction(row["effect_flagged"],
                                    (c - row["baseline_mean_flagged"]) if pd.notna(c) else np.nan)
    return ok_all and ok_flagged


def pattern_view(context: pd.DataFrame, top_n: int, worst: bool = False) -> pd.DataFrame:
    if context.empty:
        return context
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

    out = out.sort_values("rank_key", ascending=False).head(top_n)
    out.index.name = "pattern_id"
    return out.reset_index()

def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v) or np.isinf(v)):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def _pre_index_bias_frac(n_all, n_flagged):
    if pd.isna(n_all) or pd.isna(n_flagged) or n_all == 0:
        return None
    return (n_all - n_flagged) / n_all


def direction_ok(row, view: str):
    """True/False if this view passed and has something to check against;
    None if this view never passed at all (nothing to evaluate)."""
    effect = row[f"effect_{view}"]
    if pd.isna(effect):
        return None
    confirm = row[f"confirm_mean_fwd_return_{view}"]
    baseline = row[f"baseline_mean_{view}"]
    if pd.isna(confirm):
        return True
    return same_direction(effect, confirm - baseline)


def to_api_rows(context: pd.DataFrame, edges_by_feature: dict) -> list[dict]:
    """Every passed pattern, raw numbers for both views, nothing pre-dropped
    or pre-truncated -- the frontend sorts/filters/truncates all of it."""
    if context.empty:
        return []
    rows = []
    for pid, row in context.iterrows():
        entry = {
            "pattern_id": int(pid),
            "conditions_html": conditions_html(row["description"], edges_by_feature),
            "n_all": _clean(row["n_all"]),
            "n_flagged": _clean(row["n_flagged"]),
            "pre_index_bias": _pre_index_bias_frac(row["n_all"], row["n_flagged"]),
            "overlap_ratio": _clean(row["overlap_ratio"]),
            "top3_year_share": _clean(row["top3_year_share"]),
            "mean_excl_top3": _clean(row["mean_excl_top3"]),
            "reference_mean": _clean(row["reference_mean"]),
        }
        for view in ("all", "flagged"):
            entry[f"mean_fwd_return_{view}"] = _clean(row[f"mean_fwd_return_{view}"])
            entry[f"baseline_mean_{view}"] = _clean(row[f"baseline_mean_{view}"])
            entry[f"effect_{view}"] = _clean(row[f"effect_{view}"])
            entry[f"confirm_mean_fwd_return_{view}"] = _clean(row[f"confirm_mean_fwd_return_{view}"])
            entry[f"q_value_{view}"] = _clean(row[f"q_value_{view}"])
            entry[f"breadth_stocks_{view}"] = _clean(row[f"breadth_stocks_{view}"])
            entry[f"breadth_years_{view}"] = _clean(row[f"breadth_years_{view}"])
            entry[f"direction_ok_{view}"] = direction_ok(row, view)
            bs = row[f"best_single_{view}"]
            entry[f"best_single_{view}"] = (
                {"effect": _clean(bs[0]), "feature": bs[1], "bucket": int(bs[2])} if bs else None
            )
            entry[f"best_single_html_{view}"] = (
                f"{fmt_pct_sign(bs[0])} ({describe_bucket(bs[1], bs[2], edges_by_feature.get(bs[1]))})"
                if bs else "N/A"
            )
        rows.append(entry)
    return rows

def stock_to_api_rows(stock_df: pd.DataFrame, edges_by_feature: dict, live_pattern_ids: set[int] | None = None) -> list[dict]:
    if stock_df.empty:
        return []
    live_pattern_ids = live_pattern_ids or set()
    rows = []
    for _, row in stock_df.iterrows():
        pid = int(row["pattern_id"])
        entry = {
            "pattern_id": pid,
            "is_live": pid in live_pattern_ids,
            "conditions_html": conditions_html(row["description"], edges_by_feature),
            "n_all": _clean(row["n_all"]),
            "n_flagged": _clean(row["n_flagged"]),
            "pre_index_bias": _pre_index_bias_frac(row["n_all"], row["n_flagged"]),
            "overlap_ratio": _clean(row["overlap_ratio"]),
            "top3_year_share": _clean(row["top3_year_share"]),
            "mean_excl_top3": _clean(row["mean_excl_top3"]),
            "reference_mean": _clean(row["reference_mean"]),
        }
        for view in ("all", "flagged"):
            entry[f"mean_fwd_return_{view}"] = _clean(row[f"mean_fwd_return_{view}"])
            entry[f"edge_{view}"] = _clean(row[f"edge_{view}"])
            entry[f"hit_rate_{view}"] = _clean(row[f"hit_rate_{view}"])
            entry[f"stock_effect_{view}"] = _clean(row[f"stock_effect_{view}"])
            bs = row[f"best_single_{view}"]
            entry[f"best_single_{view}"] = (
                {"effect": _clean(bs[0]), "feature": bs[1], "bucket": int(bs[2])} if bs else None
            )
        rows.append(entry)
    return rows