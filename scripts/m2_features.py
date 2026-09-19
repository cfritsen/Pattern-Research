import json
import time
from pathlib import Path
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.universe import in_index_flag
from patternlab.clean import load_clean
from patternlab.features import compute_features


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    out_dir = Path(cfg["data_dir"]) / "features"
    out_dir.mkdir(parents=True, exist_ok=True)

    idx_df, _ = load_clean(cfg["index_proxy"], cfg)
    idx_close = idx_df["adj_close"]

    t0, done, failed, total_rows, complete_rows = time.time(), 0, [], 0, 0
    for t, added in zip(uni["data_ticker"], uni["date_added"]):
        try:
            df, _ = load_clean(t, cfg)
            f = compute_features(df, idx_close)
            f["in_index"] = in_index_flag(df.index, added).to_numpy()
            f32 = f.select_dtypes("float64").columns
            f[f32] = f[f32].astype("float32")
            f.to_parquet(out_dir / f"{t}.parquet")
            done += 1
            total_rows += len(f)
            complete_rows += int(f.drop(columns=["tradable", "in_index"]).notna().all(axis=1).sum())
        except Exception as e:
            failed.append((t, str(e)))

    manifest = json.loads((Path(cfg["data_dir"]) / "manifest.json").read_text())
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