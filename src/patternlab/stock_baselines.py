"""Per-stock baselines.

A stock's baseline is its OWN average forward return over all of its tradable days
(the same horizon as the results, over its full history, like its per-stock pattern
mean), computed once per view: All Data, and Index-Only (days since it joined the index).
A per-stock Edge is the stock's mean after the pattern minus this, so a stock that
drifts up anyway is credited only for what the pattern adds. The market-wide Edge keeps
the market-wide baseline.

Always calculated from the outcome files, never assumed. Kept in the `stock_baselines`
table and refreshed on its own when the outcome files are newer than the stored copy
(so no rediscovery is needed to start using it)."""
from __future__ import annotations
import pandas as pd

from patternlab.config import index_data_dir
from patternlab.universe import in_index_flag

MIN_BASELINE_DAYS = 250      # about a year of trading days; fewer and the stock falls back to the market baseline


def results_horizon(conn, cfg: dict) -> int:
    row = conn.execute("SELECT horizon FROM pattern_results_pooled LIMIT 1").fetchone()
    return int(row[0]) if row else int(cfg["horizon"])


def _outcome_files(cfg: dict, uni: pd.DataFrame) -> dict:
    out_dir = index_data_dir(cfg, "outcomes")
    files = {t: out_dir / f"{t}.parquet" for t in uni["data_ticker"]}
    return {t: p for t, p in files.items() if p.exists()}


def compute_stock_baselines(cfg: dict, uni: pd.DataFrame, horizon: int) -> pd.DataFrame:
    added = uni.set_index("data_ticker")["date_added"]
    rows = []
    for t, path in _outcome_files(cfg, uni).items():
        o = pd.read_parquet(path, columns=[f"fwd_ret_{horizon}", "tradable"])
        o = o[o["tradable"]]
        fwd = o[f"fwd_ret_{horizon}"]
        for view, mask in (("all", pd.Series(True, index=o.index)),
                           ("flagged", pd.Series(in_index_flag(o.index, added.get(t)).to_numpy(), index=o.index))):
            v = fwd[mask].dropna()
            rows.append({"ticker": t, "view": view, "n": int(len(v)),
                         "mean_fwd_return": float(v.mean()) if len(v) >= MIN_BASELINE_DAYS else None})
    return pd.DataFrame(rows, columns=["ticker", "view", "n", "mean_fwd_return"])


def ensure_stock_baselines(cfg: dict, uni: pd.DataFrame, conn) -> None:
    """(Re)build the table when it is missing, built for another horizon, or older
    than the outcome files."""
    files = _outcome_files(cfg, uni)
    if not files:
        return
    newest = max(p.stat().st_mtime for p in files.values())
    horizon = results_horizon(conn, cfg)
    meta = conn.execute("SELECT MAX(source_mtime), MAX(horizon), COUNT(*) FROM stock_baselines").fetchone()
    if meta[2] and meta[1] == horizon and meta[0] is not None and meta[0] >= newest:
        return
    df = compute_stock_baselines(cfg, uni, horizon)
    conn.execute("DELETE FROM stock_baselines")
    conn.executemany(
        "INSERT INTO stock_baselines (ticker, view, horizon, n, mean_fwd_return, source_mtime) VALUES (?,?,?,?,?,?)",
        [(r.ticker, r.view, horizon, r.n, r.mean_fwd_return, newest) for r in df.itertuples()])
    conn.commit()


def load_stock_baselines(conn, ticker: str | None = None) -> dict:
    """(ticker, view) -> the stock's own baseline. A stock with too little history is absent."""
    query = "SELECT ticker, view, mean_fwd_return FROM stock_baselines WHERE mean_fwd_return IS NOT NULL"
    params = ()
    if ticker:
        query += " AND ticker = ?"
        params = (ticker,)
    return {(t, v): float(m) for t, v, m in conn.execute(query, params)}
