import json
import time
import pandas as pd
from pathlib import Path
from patternlab.config import load_config, ensure_dirs, manifest_path, index_data_dir
from patternlab.universe_fetch import get_universe, get_index_proxy
from patternlab.clean import load_clean
from patternlab.features import compute_features
from patternlab.indicators import load_vix_close, market_features


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    out_dir = index_data_dir(cfg, "features")
    out_dir.mkdir(parents=True, exist_ok=True)

    proxy = get_index_proxy(cfg["index"])
    idx_df, _ = load_clean(proxy, cfg)
    idx_close = idx_df["adj_close"]
    # Date-level features (same value for every stock on a date) are computed once, not per ticker.
    market = market_features(idx_close, load_vix_close(cfg))

    t0, done, failed, total_rows, complete_rows = time.time(), 0, [], 0, 0
    for t in uni["data_ticker"]:
        try:
            df, _ = load_clean(t, cfg)
            f = compute_features(df, idx_close, market)
            f32 = f.select_dtypes("float64").columns
            f[f32] = f[f32].astype("float32")
            f.to_parquet(out_dir / f"{t}.parquet")
            done += 1
            total_rows += len(f)
            complete_rows += int(f.drop(columns=["tradable"]).notna().all(axis=1).sum())
        except Exception as e:
            failed.append((t, str(e)))

    # Cheap extra artifact for live-matching pages (watchlist, pattern
    # matching, pattern stocks, date insights) -- one row per ticker instead
    # of 503 separate full-history files. Nothing new is computed here; this
    # just gathers each ticker's already-finished last row into one table.
    last_rows = []
    for t in uni["data_ticker"]:
        path = out_dir / f"{t}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty or not bool(df["tradable"].iloc[-1]):
            continue
        row = df.iloc[-1].copy()
        row["ticker"] = t
        last_rows.append(row)
    if last_rows:
        snapshot = pd.DataFrame(last_rows).set_index("ticker")
        snapshot.to_parquet(out_dir / "_latest_snapshot.parquet")
        print(f"Latest-snapshot cache: {len(snapshot)} tickers")

    manifest = json.loads(manifest_path(cfg).read_text())
    meta = {"price_data_version": manifest["data_version"],
            "universe_snapshot": manifest["universe_snapshot"],
            "tickers": done, "rows": total_rows, "complete_rows": complete_rows}
    (out_dir / "_meta.json").write_text(json.dumps(meta, indent=2))

    print(f"{done} tickers, {total_rows:,} rows ({complete_rows:,} with every feature present), "
          f"{time.time() - t0:.0f}s")
    if failed:
        print(f"{len(failed)} failed:")
        for t, e in failed[:20]:
            print(f"  {t}: {e}")


if __name__ == "__main__":
    main()