from __future__ import annotations
import calendar
import re
import numpy as np
import pandas as pd

OVERLAP_FLAG = 1.5
MISSING = "--"
NOT_APPLICABLE = "N/A"

FEATURE_INFO = {
    "ret_1": ("1-day Return", "Bad 1-day Drop", "Good 1-day Gain"),
    "ret_3": ("3-day Return", "Bad 3-day Drop", "Good 3-day Gain"),
    "ret_5": ("5-day Return", "Bad 5-day Drop", "Good 5-day Gain"),
    "ret_10": ("10-day Return", "Bad 10-day Drop", "Good 10-day Gain"),
    "ret_20": ("20-day Return", "Bad 20-day Drop", "Good 20-day Gain"),
    "dist_sma20_atr": ("20-day Avg Distance", "Below 20-day Avg", "Above 20-day Avg"),
    "dist_sma50_atr": ("50-day Avg Distance", "Below 50-day Avg", "Above 50-day Avg"),
    "dist_sma200_atr": ("200-day Avg Distance", "Below 200-day Avg", "Above 200-day Avg"),
    "rsi14": ("14-day RSI", "Oversold RSI", "Overbought RSI"),
    "macd_hist_pct": ("MACD Histogram", "Bearish MACD", "Bullish MACD"),
    "atr_pct": ("Volatility Level", "Low Volatility", "High Volatility"),
    "range_comp_10": ("10-day Range", "Tight Range", "Wide Range"),
    "gap_pct": ("Opening Gap", "Gap Down", "Gap Up"),
    "body_ratio": ("Candle Body Size", "Small Candle Body", "Large Candle Body"),
    "upper_wick_ratio": ("Upper Wick Size", "Small Upper Wick", "Large Upper Wick"),
    "lower_wick_ratio": ("Lower Wick Size", "Small Lower Wick", "Large Lower Wick"),
    "close_loc": ("Close Location", "Closed Near Low", "Closed Near High"),
    "streak": ("Win/Loss Streak", "Long Losing Streak", "Long Winning Streak"),
    "vol_rel_20": ("Trading Volume", "Low Volume", "High Volume"),
    "rel_strength_20": ("20-day vs. Market", "Underperforming Market", "Outperforming Market"),
    "dist_52w_high": ("52-week High Distance", "Deep Pullback from 52-week High", "Near 52-week High"),
    "dist_52w_low": ("52-week Low Distance", "Near 52-week Low", "Far from 52-week Low"),
}
MONTH_NAMES = {i: calendar.month_name[i] for i in range(1, 13)}
DOW_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}

PCT_FEATURES = {"ret_1", "ret_3", "ret_5", "ret_10", "ret_20", "macd_hist_pct", "atr_pct",
                "gap_pct", "dist_52w_high", "dist_52w_low", "rel_strength_20"}
ATR_FEATURES = {"dist_sma20_atr", "dist_sma50_atr", "dist_sma200_atr", "range_comp_10"}
POINTS_FEATURES = {"rsi14"}
RATIO_FEATURES = {"body_ratio", "upper_wick_ratio", "lower_wick_ratio", "close_loc"}
DAYS_FEATURES = {"streak"}
MULT_FEATURES = {"vol_rel_20"}


def format_edge_value(feature: str, value: float) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "?"
    if feature in PCT_FEATURES:
        return f"{value:+.1%}"
    if feature in ATR_FEATURES:
        return f"{value:+.1f} ATRs"
    if feature in POINTS_FEATURES:
        return f"{value:.0f}"
    if feature in RATIO_FEATURES:
        return f"{value:.0%}"
    if feature in DAYS_FEATURES:
        return f"{value:+.0f} days"
    if feature in MULT_FEATURES:
        return f"{value:.1f}x normal"
    return f"{value:.3g}"


def bucket_range_text(feature: str, bucket: int, edges: list[float] | None) -> str:
    if feature in ("month", "dow") or not edges:
        return ""
    n = len(edges)
    lo = edges[bucket - 1] if 0 < bucket <= n else None
    hi = edges[bucket] if bucket < n else None
    if lo is None and hi is not None:
        return f" (below {format_edge_value(feature, hi)})"
    if lo is not None and hi is None:
        return f" (above {format_edge_value(feature, lo)})"
    if lo is not None and hi is not None:
        return f" (between {format_edge_value(feature, lo)} and {format_edge_value(feature, hi)})"
    return ""


def describe_bucket(feature: str, bucket: int, edges: list[float] | None = None) -> str:
    if feature == "month":
        return MONTH_NAMES.get(int(bucket), f"Month {bucket}")
    if feature == "dow":
        return DOW_NAMES.get(int(bucket), f"Day {bucket}")
    name, low, high = FEATURE_INFO.get(feature, (feature, f"{feature} (bottom fifth)", f"{feature} (top fifth)"))
    if bucket == 0:
        text = low
    elif bucket == 4:
        text = high
    else:
        pct = f"{bucket * 20}-{(bucket + 1) * 20}th pct."
        text = f"{name} ({pct})"
    return text + bucket_range_text(feature, bucket, edges)


def short_bucket_label(feature: str, bucket: int) -> str:
    """Same as describe_bucket but without the numeric range -- for compact
    inline labels like 'vs. Best Single Condition'."""
    return describe_bucket(feature, bucket, edges=None)


def parse_conditions(description: str) -> list[dict]:
    return [{"feature": m.group(1), "bucket": int(m.group(2))}
            for m in re.finditer(r"(\w+) in bucket (\d+)", description)]


def conditions_html(description: str, edges_by_feature: dict[str, list[float]] | None) -> str:
    conds = parse_conditions(description)
    parts = [describe_bucket(c["feature"], c["bucket"], (edges_by_feature or {}).get(c["feature"]))
             for c in conds]
    return "".join(f"<div class='cond'>{p}</div>" for p in parts)


def fmt_signed(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return MISSING
    return f"{x:+.2%}"


def fmt_plain(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return MISSING
    return f"{x:.1%}"


def dual(all_v, flagged_v, fmt) -> str:
    return f"{fmt(all_v)} / {fmt(flagged_v)}"


def overlap_label(ratio) -> str:
    if ratio is None or (isinstance(ratio, float) and np.isnan(ratio)):
        return MISSING
    diff_pct = (ratio - 1) * 100
    if ratio > OVERLAP_FLAG:
        return f"Co-occur +{diff_pct:.0f}%"
    if ratio < 1 / OVERLAP_FLAG:
        return f"Avoided {abs(diff_pct):.0f}%"
    return "No"


def concentration_note(top3_share, mean_excl, reference_mean) -> str:
    if top3_share is None or (isinstance(top3_share, float) and np.isnan(top3_share)):
        return MISSING
    if top3_share > 0.35:
        if pd.notna(mean_excl) and pd.notna(reference_mean):
            verb = "drops to" if mean_excl < reference_mean else "rises to"
            excl_txt = fmt_signed(mean_excl)
        else:
            verb, excl_txt = "changes to", MISSING
        return f"Caution: {top3_share:.0%} from top 3 years (excluding, {verb} {excl_txt})"
    return f"Consistent: {top3_share:.0%} from top 3 years"


def pre_index_bias(n_all, n_flagged) -> str:
    """Bare percentage -- the explanation of what this means lives in the
    report's key text (see m6_reports.to_html), not repeated in every cell."""
    if pd.isna(n_all) or pd.isna(n_flagged) or n_all == 0:
        return MISSING
    pct = (n_all - n_flagged) / n_all
    return f"{pct:.0%}"


def best_single_label(entry) -> str:
    """entry: (effect, feature, bucket) or None."""
    if entry is None:
        return NOT_APPLICABLE
    effect, feature, bucket = entry
    return f"{fmt_signed(effect)} ({short_bucket_label(feature, bucket)})"


def dual_best_single(entry_all, entry_flagged) -> str:
    return f"{best_single_label(entry_all)} / {best_single_label(entry_flagged)}"


def humanize_pattern_view(df: pd.DataFrame, edges_by_feature: dict[str, list[float]] | None) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    out = pd.DataFrame()
    out["Conditions"] = [conditions_html(d, edges_by_feature) for d in df["description"]]
    out["Pre-Index Bias"] = [pre_index_bias(a, f) for a, f in zip(df["n_all"], df["n_flagged"])]
    out["Cases Found"] = df["n_all"].map(lambda n: f"{n:,.0f}" if pd.notna(n) else MISSING)
    out["5-day Return"] = [dual(a, f, fmt_signed) for a, f in zip(df["mean_fwd_return_all"], df["mean_fwd_return_flagged"])]
    out["5-day Baseline"] = [dual(a, f, fmt_signed) for a, f in zip(df["baseline_mean_all"], df["baseline_mean_flagged"])]
    out["Edge"] = [dual(a, f, fmt_signed) for a, f in zip(df["effect_all"], df["effect_flagged"])]
    out["vs. Best Single Condition"] = [dual_best_single(a, f) for a, f in
                                        zip(df["best_single_all"], df["best_single_flagged"])]
    out["Forward Test Return"] = [dual(a, f, fmt_signed) for a, f in
                                  zip(df["confirm_mean_fwd_return_all"], df["confirm_mean_fwd_return_flagged"])]
    out["False Discovery Rate"] = [dual(a, f, fmt_plain) for a, f in zip(df["q_value_all"], df["q_value_flagged"])]
    out["Stocks Agreed"] = [dual(a, f, fmt_plain) for a, f in zip(df["breadth_stocks_all"], df["breadth_stocks_flagged"])]
    out["Years Agreed"] = [dual(a, f, fmt_plain) for a, f in zip(df["breadth_years_all"], df["breadth_years_flagged"])]
    out["Conditions Overlap?"] = df["overlap_ratio"].map(overlap_label)
    out["Year Concentration"] = [concentration_note(t, m, r) for t, m, r in
                                 zip(df["top3_year_share"], df["mean_excl_top3"], df["reference_mean"])]
    return out


def humanize_stock_view(df: pd.DataFrame, edges_by_feature: dict[str, list[float]] | None) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    out = pd.DataFrame()
    out["Conditions"] = [conditions_html(d, edges_by_feature) for d in df["description"]]
    out["Pre-Index Bias"] = [pre_index_bias(a, f) for a, f in zip(df["n_all"], df["n_flagged"])]
    out["Cases for this stock"] = df["n_all"].map(lambda n: f"{n:,.0f}" if pd.notna(n) else MISSING)
    out["5-day Return"] = [dual(a, f, fmt_signed) for a, f in zip(df["mean_fwd_return_all"], df["mean_fwd_return_flagged"])]
    out["5-day Baseline"] = [dual(a, f, fmt_signed) for a, f in zip(df["baseline_mean_all"], df["baseline_mean_flagged"])]
    out["Edge"] = [dual(a, f, fmt_signed) for a, f in zip(df["edge_all"], df["edge_flagged"])]
    out["vs. Best Single Condition"] = [dual_best_single(a, f) for a, f in
                                        zip(df["best_single_all"], df["best_single_flagged"])]
    out["Hit Rate"] = [dual(a, f, fmt_plain) for a, f in zip(df["hit_rate_all"], df["hit_rate_flagged"])]
    out["vs. All-stock Average"] = [dual(a, f, fmt_signed) for a, f in
                                    zip(df["stock_effect_all"], df["stock_effect_flagged"])]
    out["Conditions Overlap?"] = df["overlap_ratio"].map(overlap_label)
    out["Year Concentration"] = [concentration_note(t, m, r) for t, m, r in
                                 zip(df["top3_year_share"], df["mean_excl_top3"], df["reference_mean"])]
    return out