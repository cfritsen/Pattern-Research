from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from patternlab.buckets import CATEGORICAL
from patternlab.reports import build_pattern_context, passes_direction_filter


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


def compute_watchlist(cfg: dict, uni: pd.DataFrame, conn, only_ticker: str | None = None) -> list[dict]:
    """Flat (ticker, pattern_id, view, ...) match rows. only_ticker scopes
    this to a single stock (cheap -- loads one feature file instead of the
    whole universe), used by the Stock Research page's live-match tab."""
    feat_dir = Path(cfg["data_dir"]) / "features"

    context = build_pattern_context(conn)
    if context.empty:
        return []
    kept = context[context.apply(passes_direction_filter, axis=1)]

    edges_by_feature = load_edges(conn)

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
            historical_return = float(prow[f"mean_fwd_return_{view}"])
            for ticker, frow in rows_by_ticker.items():
                if all(current_bucket(c["feature"], frow, edges_by_feature) == c["bucket"]
                      for c in conditions):
                    matches.append({
                        "ticker": ticker,
                        "pattern_id": int(pattern_id),
                        "view": view,
                        "description": prow["description"],
                        "conditions": conditions,
                        "historical_return": historical_return,
                        "as_of_date": str(frow.name.date()),
                    })
    return matches