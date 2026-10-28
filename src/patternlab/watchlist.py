from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from patternlab.buckets import CATEGORICAL
from patternlab.reports import build_pattern_context, passes_direction_filter
from patternlab.humanize import badge_text


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


def latest_feature_row(feat_dir: Path, ticker: str) -> pd.Series | None:
    path = feat_dir / f"{ticker}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if df.empty or not bool(df["tradable"].iloc[-1]):
        return None
    return df.iloc[-1]


def current_bucket(feature: str, row: pd.Series, edges_by_feature: dict) -> int | None:
    if feature in CATEGORICAL:
        v = row.get(feature)
        return None if pd.isna(v) else int(v)
    return apply_bucket_scalar(row.get(feature), edges_by_feature.get(feature, []))

def load_stock_returns(conn, pattern_ids: set[int], ticker_filter: str | None = None) -> dict:
    """(ticker, pattern_id, view) -> per-stock mean forward return, for
    patterns that cleared the per-stock minimum-occurrence bar (nulls from
    thin samples are already excluded -- see by_stock.py's per_stock_breakdown).
    """
    if not pattern_ids:
        return {}
    placeholders = ",".join("?" for _ in pattern_ids)
    query = (f"SELECT pattern_id, ticker, view, mean_fwd_return FROM pattern_results_by_stock "
            f"WHERE split='full' AND pattern_id IN ({placeholders})")
    params = list(pattern_ids)
    if ticker_filter:
        query += " AND ticker = ?"
        params.append(ticker_filter)
    df = pd.read_sql(query, conn, params=params)
    return {(r["ticker"], int(r["pattern_id"]), r["view"]): float(r["mean_fwd_return"])
           for _, r in df.iterrows() if pd.notna(r["mean_fwd_return"])}

def compute_watchlist(cfg: dict, uni: pd.DataFrame, conn, only_ticker: str | None = None) -> list[dict]:
    """Flat (ticker, pattern_id, view, ...) match rows. only_ticker scopes
    this to a single stock (cheap -- loads one feature file instead of the
    whole universe), used by the Stock Research page's live-match tab.
    historical_return prefers the per-stock figure when one exists and is
    reliable (>=30 occurrences for that stock); falls back to the pooled
    market-wide figure otherwise. return_source records which was used,
    so the two are never silently conflated in the UI again."""
    feat_dir = Path(cfg["data_dir"]) / "features"

    context = build_pattern_context(conn)
    if context.empty:
        return []
    kept = context[context.apply(passes_direction_filter, axis=1)]

    edges_by_feature = load_edges(conn)
    stock_returns = load_stock_returns(conn, set(int(i) for i in kept.index), ticker_filter=only_ticker)

    rows_by_ticker: dict[str, pd.Series] = {}
    tickers = [only_ticker] if only_ticker else list(uni["data_ticker"])
    for t in tickers:
        r = latest_feature_row(feat_dir, t)
        if r is not None:
            rows_by_ticker[t] = r

    matches = []
    for pattern_id, prow in kept.iterrows():
        conditions = json.loads(prow["conditions_json"])
        for view in ("all", "flagged"):
            if pd.isna(prow[f"effect_{view}"]):
                continue  # this pattern didn't pass in this view
            market_return = float(prow[f"mean_fwd_return_{view}"])
            for ticker, frow in rows_by_ticker.items():
                if all(current_bucket(c["feature"], frow, edges_by_feature) == c["bucket"]
                      for c in conditions):
                    stock_specific = stock_returns.get((ticker, int(pattern_id), view))
                    matches.append({
                        "ticker": ticker,
                        "pattern_id": int(pattern_id),
                        "view": view,
                        "description": prow["description"],
                        "conditions": conditions,
                        "historical_return": stock_specific if stock_specific is not None else market_return,
                        "return_source": "stock" if stock_specific is not None else "market",
                        "as_of_date": str(frow.name.date()),
                    })
    return matches

def load_stock_stats(conn, pattern_ids: set[int], ticker_filter: str | None = None) -> dict:
    """(ticker, pattern_id, view) -> {n, mean_fwd_return, hit_rate, effect} for
    stock-level stats that cleared the per-stock minimum-occurrence bar
    (by_stock.py nulls mean/hit_rate/effect together when a stock falls
    short, so checking mean_fwd_return is enough to detect 'unconfirmed')."""
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
    out = {}
    for _, r in df.iterrows():
        if pd.isna(r["mean_fwd_return"]):
            continue
        out[(r["ticker"], int(r["pattern_id"]), r["view"])] = {
            "n": int(r["n"]), "mean_fwd_return": float(r["mean_fwd_return"]),
            "hit_rate": None if pd.isna(r["hit_rate"]) else float(r["hit_rate"]),
            "effect": float(r["effect"]),
        }
    return out


def compute_matching_table(cfg: dict, uni: pd.DataFrame, conn, ticker: str) -> list[dict]:
    """Every live match for one ticker. 'confirmed' is True when this
    stock has its own reliable (>=30 occurrence) history for the pattern;
    in that case stock-specific Return/Edge/Hit Rate are used. Otherwise
    falls back to the pooled market-wide figures, with confirmed=False so
    the UI can label it rather than silently mixing the two -- same
    fallback principle as the dashboard watchlist card, but exposing the
    distinction explicitly instead of hiding it behind one number."""
    feat_dir = Path(cfg["data_dir"]) / "features"
    frow = latest_feature_row(feat_dir, ticker)
    if frow is None:
        return []

    context = build_pattern_context(conn)
    if context.empty:
        return []
    kept = context[context.apply(passes_direction_filter, axis=1)]
    edges_by_feature = load_edges(conn)

    pattern_ids = set(int(i) for i in kept.index)
    stock_stats = load_stock_stats(conn, pattern_ids, ticker_filter=ticker)

    rows = []
    for pattern_id, prow in kept.iterrows():
        conditions = json.loads(prow["conditions_json"])
        if not all(current_bucket(c["feature"], frow, edges_by_feature) == c["bucket"]
                  for c in conditions):
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
    from patternlab.humanize import conditions_html
    out = []
    for r in rows:
        entry = dict(r)
        entry["conditions_html"] = conditions_html(r["description"], edges_by_feature)
        out.append(entry)
    return out

def compute_pattern_matches(cfg: dict, uni: pd.DataFrame, conn, pattern_id: int) -> list[dict]:
    """Every ticker currently matching ONE fixed pattern -- the inverse
    pivot of compute_matching_table (which fixes ticker, varies pattern).
    Same stock-confirmed/market-wide fallback logic and confirmation flag."""
    feat_dir = Path(cfg["data_dir"]) / "features"

    context = build_pattern_context(conn)
    if context.empty or pattern_id not in context.index:
        return []
    prow = context.loc[pattern_id]
    if not passes_direction_filter(prow):
        return []

    conditions = json.loads(prow["conditions_json"])
    edges_by_feature = load_edges(conn)
    stock_stats = load_stock_stats(conn, {pattern_id})

    rows = []
    for ticker in uni["data_ticker"]:
        frow = latest_feature_row(feat_dir, ticker)
        if frow is None:
            continue
        if not all(current_bucket(c["feature"], frow, edges_by_feature) == c["bucket"]
                  for c in conditions):
            continue
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
    """Pattern rows (same shape as build_pattern_context) whose conditions
    include month == the given bucket (1-12). Powers Date Insights'
    Patterns tab, which reuses Market Research's row format as-is."""
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
    """Flat (ticker, pattern_id, view) rows for Date Insights' Stocks tab.
    Purely historical -- a stock appears here only if it has enough of its
    own historical occurrences (per load_stock_stats' reliability floor) of
    a pattern whose conditions include this month. No live or current data
    is read; this reflects what already happened, not today's values."""
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