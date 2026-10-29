from __future__ import annotations
import json
from pathlib import Path
from patternlab.config import index_data_dir
import numpy as np
import pandas as pd
from patternlab.buckets import CATEGORICAL
from patternlab.reports import build_pattern_context, passes_direction_filter
from patternlab.humanize import badge_text, conditions_html


def apply_bucket_scalar(value, edges: list[float]) -> int | None:
    """Mirrors buckets.apply_buckets' pd.cut convention (right-inclusive
    bins, outermost buckets open-ended) but for a single live value instead
    of a whole Series."""
    if value is None or pd.isna(value) or not edges:
        return None
    for i, e in enumerate(edges):
        if value <= e:
            return i
    return len(edges)


def load_edges(conn) -> dict[str, list[float]]:
    edges: dict[str, list[float]] = {}
    for feat, idx, val in conn.execute(
            "SELECT feature, edge_index, edge_value FROM feature_bucket_edges ORDER BY feature, edge_index"):
        edges.setdefault(feat, []).append(val)
    return edges


def load_latest_snapshot(cfg: dict) -> pd.DataFrame:
    """The cheap, pre-built one-row-per-ticker snapshot M2 writes. Falls
    back to the slow per-file path (one read per ticker) if the snapshot
    hasn't been generated yet (e.g. an older data/features/ directory from
    before this optimization existed) -- still correct, just slower."""
    path = index_data_dir(cfg, "features") / "_latest_snapshot.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def _legacy_latest_feature_row(feat_dir: Path, ticker: str) -> pd.Series | None:
    path = feat_dir / f"{ticker}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty or not bool(df["tradable"].iloc[-1]):
        return None
    return df.iloc[-1]


def get_snapshot(cfg: dict, uni: pd.DataFrame) -> pd.DataFrame:
    """Snapshot indexed by ticker, restricted to uni's tickers. Uses the
    fast cached path when available, otherwise rebuilds it the slow way
    (and this is the only place that slow path still runs)."""
    snap = load_latest_snapshot(cfg)
    if not snap.empty:
        return snap.loc[snap.index.intersection(uni["data_ticker"])]
    feat_dir = index_data_dir(cfg, "features")
    rows = {}
    for t in uni["data_ticker"]:
        r = _legacy_latest_feature_row(feat_dir, t)
        if r is not None:
            rows[t] = r
    return pd.DataFrame(rows).T if rows else pd.DataFrame()


def bucket_snapshot(snapshot: pd.DataFrame, edges_by_feature: dict[str, list[float]]) -> pd.DataFrame:
    """Vectorized bucketing of every ticker's every feature at once -- one
    pd.cut call per continuous feature across all tickers, instead of a
    Python function call per (ticker, feature) pair."""
    out = pd.DataFrame(index=snapshot.index)
    for col in snapshot.columns:
        if col in CATEGORICAL:
            out[col] = snapshot[col]
            continue
        edges = edges_by_feature.get(col)
        if not edges:
            continue
        bounds = [-np.inf] + edges + [np.inf]
        out[col] = pd.cut(snapshot[col], bins=bounds, labels=list(range(len(bounds) - 1)),
                          include_lowest=True).astype("Int8")
    return out


def matches_for_conditions(bucketed: pd.DataFrame, conditions: list[dict]) -> pd.Index:
    """Tickers (index values) satisfying every condition -- one boolean mask
    per condition, ANDed together, all vectorized."""
    mask = pd.Series(True, index=bucketed.index)
    for c in conditions:
        if c["feature"] not in bucketed.columns:
            return pd.Index([])
        mask &= (bucketed[c["feature"]] == c["bucket"])
    return bucketed.index[mask]


def load_stock_stats(conn, pattern_ids: set[int], ticker_filter: str | None = None) -> dict:
    """(ticker, pattern_id, view) -> per-stock stats for patterns that
    cleared the per-stock minimum-occurrence bar. Built via zip() over raw
    columns rather than df.iterrows() -- iterrows() constructs a full
    pandas Series per row, which gets very slow once the result set is in
    the tens of thousands of rows (as it can be here: patterns x tickers x
    views)."""
    if not pattern_ids:
        return {}
    placeholders = ",".join("?" for _ in pattern_ids)
    query = (f"SELECT pattern_id, ticker, view, n, mean_fwd_return, hit_rate, effect "
            f"FROM pattern_results_by_stock WHERE split='full' AND pattern_id IN ({placeholders})")
    params = list(pattern_ids)
    if ticker_filter:
        query += " AND ticker = ?"
        params.append(ticker_filter)
    df = pd.read_sql(query, conn, params=params)
    df = df.dropna(subset=["mean_fwd_return"])

    out = {}
    for ticker, pid, view, n, mfr, hr, eff in zip(
            df["ticker"], df["pattern_id"], df["view"], df["n"],
            df["mean_fwd_return"], df["hit_rate"], df["effect"]):
        out[(ticker, int(pid), view)] = {
            "n": int(n), "mean_fwd_return": float(mfr),
            "hit_rate": None if pd.isna(hr) else float(hr),
            "effect": float(eff),
        }
    return out


def compute_watchlist(cfg: dict, uni: pd.DataFrame, conn, only_ticker: str | None = None) -> list[dict]:
    """Flat (ticker, pattern_id, view, ...) match rows."""
    context = build_pattern_context(conn)
    if context.empty:
        return []
    kept = context[context.apply(passes_direction_filter, axis=1)]

    edges_by_feature = load_edges(conn)
    snapshot = get_snapshot(cfg, uni)
    if only_ticker:
        snapshot = snapshot.loc[snapshot.index.intersection([only_ticker])]
    if snapshot.empty:
        return []
    bucketed = bucket_snapshot(snapshot, edges_by_feature)

    stock_returns = load_stock_stats(conn, set(int(i) for i in kept.index), ticker_filter=only_ticker)

    matches = []
    for pattern_id, prow in kept.iterrows():
        conditions = json.loads(prow["conditions_json"])
        matching_tickers = matches_for_conditions(bucketed, conditions)
        if len(matching_tickers) == 0:
            continue
        for view in ("all", "flagged"):
            if pd.isna(prow[f"effect_{view}"]):
                continue
            market_return = float(prow[f"mean_fwd_return_{view}"])
            for ticker in matching_tickers:
                stats = stock_returns.get((ticker, int(pattern_id), view))
                matches.append({
                    "ticker": ticker,
                    "pattern_id": int(pattern_id),
                    "view": view,
                    "description": prow["description"],
                    "conditions": conditions,
                    "historical_return": stats["mean_fwd_return"] if stats else market_return,
                    "return_source": "stock" if stats else "market",
                    "as_of_date": None,
                })
    return matches


def compute_matching_table(cfg: dict, uni: pd.DataFrame, conn, ticker: str) -> list[dict]:
    """Every live match for one ticker, with stock-confirmed/market-wide fallback."""
    snapshot = get_snapshot(cfg, uni)
    if ticker not in snapshot.index:
        return []
    row_frame = snapshot.loc[[ticker]]

    context = build_pattern_context(conn)
    if context.empty:
        return []
    kept = context[context.apply(passes_direction_filter, axis=1)]
    edges_by_feature = load_edges(conn)
    bucketed = bucket_snapshot(row_frame, edges_by_feature)

    pattern_ids = set(int(i) for i in kept.index)
    stock_stats = load_stock_stats(conn, pattern_ids, ticker_filter=ticker)

    rows = []
    for pattern_id, prow in kept.iterrows():
        conditions = json.loads(prow["conditions_json"])
        if len(matches_for_conditions(bucketed, conditions)) == 0:
            continue
        for view in ("all", "flagged"):
            if pd.isna(prow[f"effect_{view}"]):
                continue
            stats = stock_stats.get((ticker, int(pattern_id), view))
            confirmed = stats is not None
            market_n = prow["n_all"] if view == "all" else prow["n_flagged"]
            rows.append({
                "pattern_id": int(pattern_id),
                "view": view,
                "confirmed": confirmed,
                "description": prow["description"],
                "n": stats["n"] if confirmed else (None if pd.isna(market_n) else int(market_n)),
                "mean_fwd_return": stats["mean_fwd_return"] if confirmed else float(prow[f"mean_fwd_return_{view}"]),
                "edge": stats["effect"] if confirmed else float(prow[f"effect_{view}"]),
                "hit_rate": stats["hit_rate"] if confirmed else (
                    None if pd.isna(prow[f"hit_rate_{view}"]) else float(prow[f"hit_rate_{view}"])),
                "pre_index_bias": None if pd.isna(prow["n_all"]) or pd.isna(prow["n_flagged"]) or prow["n_all"] == 0
                    else (prow["n_all"] - prow["n_flagged"]) / prow["n_all"],
                "overlap_ratio": None if pd.isna(prow["overlap_ratio"]) else float(prow["overlap_ratio"]),
                "top3_year_share": None if pd.isna(prow["top3_year_share"]) else float(prow["top3_year_share"]),
                "mean_excl_top3": None if pd.isna(prow["mean_excl_top3"]) else float(prow["mean_excl_top3"]),
                "reference_mean": None if pd.isna(prow["reference_mean"]) else float(prow["reference_mean"]),
            })
    return rows


def matching_table_to_api_rows(rows: list[dict], edges_by_feature: dict) -> list[dict]:
    out = []
    for r in rows:
        entry = dict(r)
        entry["conditions_html"] = conditions_html(r["description"], edges_by_feature)
        out.append(entry)
    return out


def compute_pattern_matches(cfg: dict, uni: pd.DataFrame, conn, pattern_id: int) -> list[dict]:
    """Every ticker currently matching ONE fixed pattern."""
    context = build_pattern_context(conn)
    if context.empty or pattern_id not in context.index:
        return []
    prow = context.loc[pattern_id]
    if not passes_direction_filter(prow):
        return []

    conditions = json.loads(prow["conditions_json"])
    edges_by_feature = load_edges(conn)
    snapshot = get_snapshot(cfg, uni)
    if snapshot.empty:
        return []
    bucketed = bucket_snapshot(snapshot, edges_by_feature)
    matching_tickers = matches_for_conditions(bucketed, conditions)

    stock_stats = load_stock_stats(conn, {pattern_id})

    rows = []
    for ticker in matching_tickers:
        for view in ("all", "flagged"):
            if pd.isna(prow[f"effect_{view}"]):
                continue
            stats = stock_stats.get((ticker, pattern_id, view))
            confirmed = stats is not None
            market_n = prow["n_all"] if view == "all" else prow["n_flagged"]
            rows.append({
                "ticker": ticker,
                "view": view,
                "confirmed": confirmed,
                "n": stats["n"] if confirmed else (None if pd.isna(market_n) else int(market_n)),
                "mean_fwd_return": stats["mean_fwd_return"] if confirmed else float(prow[f"mean_fwd_return_{view}"]),
                "edge": stats["effect"] if confirmed else float(prow[f"effect_{view}"]),
                "hit_rate": stats["hit_rate"] if confirmed else (
                    None if pd.isna(prow[f"hit_rate_{view}"]) else float(prow[f"hit_rate_{view}"])),
            })
    return rows


def compute_month_patterns_context(conn, month: int) -> pd.DataFrame:
    """Pattern rows whose conditions include month == the given bucket."""
    context = build_pattern_context(conn)
    if context.empty:
        return context
    def has_month(conds_json):
        conds = json.loads(conds_json)
        return any(c["feature"] == "month" and c["bucket"] == month for c in conds)
    kept = context[context["conditions_json"].apply(has_month)]
    if kept.empty:
        return kept
    return kept[kept.apply(passes_direction_filter, axis=1)]


def compute_month_stock_matches(conn, month: int) -> list[dict]:
    """Purely historical -- no live/current data read at all."""
    context = compute_month_patterns_context(conn, month)
    if context.empty:
        return []
    pattern_ids = set(int(i) for i in context.index)
    stock_stats = load_stock_stats(conn, pattern_ids)

    matches = []
    for (ticker, pattern_id, view), stats in stock_stats.items():
        prow = context.loc[pattern_id]
        conditions = json.loads(prow["conditions_json"])
        other_conditions = [c for c in conditions if c["feature"] != "month"]
        badge = badge_text(other_conditions) if other_conditions else badge_text(conditions)
        matches.append({
            "ticker": ticker,
            "pattern_id": pattern_id,
            "view": view,
            "badge": badge,
            "n": stats["n"],
            "historical_return": stats["mean_fwd_return"],
            "hit_rate": stats["hit_rate"],
        })
    return matches


def compute_current_month_highlights(conn, month: int) -> dict:
    """Top 5 patterns and top 5 stocks for the given month."""
    context = compute_month_patterns_context(conn, month)
    if context.empty:
        return {"patterns": [], "stocks": []}

    edges_by_feature = load_edges(conn)
    top_patterns = context.sort_values("rank_key", ascending=False).head(5)
    pattern_cards = []
    for pid, row in top_patterns.iterrows():
        eff_all = row["effect_all"] if pd.notna(row["effect_all"]) else None
        eff_flag = row["effect_flagged"] if pd.notna(row["effect_flagged"]) else None
        if eff_all is not None and (eff_flag is None or abs(eff_all) >= abs(eff_flag)):
            view, ret = "all", float(row["mean_fwd_return_all"])
        else:
            view, ret = "flagged", float(row["mean_fwd_return_flagged"])
        pattern_cards.append({
            "pattern_id": int(pid), "view": view,
            "conditions_html": conditions_html(row["description"], edges_by_feature),
            "return": ret,
        })

    stock_matches = compute_month_stock_matches(conn, month)
    by_ticker: dict[str, dict] = {}
    for m in stock_matches:
        cur = by_ticker.get(m["ticker"])
        if cur is None or m["historical_return"] > cur["historical_return"]:
            by_ticker[m["ticker"]] = m
    top_stocks = sorted(by_ticker.values(), key=lambda m: m["historical_return"], reverse=True)[:5]
    stock_cards = [{"ticker": m["ticker"], "badge": m["badge"], "return": m["historical_return"]}
                  for m in top_stocks]

    return {"patterns": pattern_cards, "stocks": stock_cards}