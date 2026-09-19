import argparse
import json
import time
from pathlib import Path
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.fetch import get_prices, data_version
from patternlab.quality import check_prices, failed_row


def main(refresh: bool, refresh_universe: bool, limit: int) -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg, refresh=refresh_universe)
    snap = str(uni["snapshot_date"].iloc[0])
    print(f"Universe: {len(uni)} constituents, snapshot {snap}")

    targets = list(dict.fromkeys(uni["data_ticker"]))
    if limit:
        targets = targets[:limit]
    targets = list(dict.fromkeys(targets + [cfg["index_proxy"]]))

    rows, manifest = [], {}
    for t in targets:
        try:
            df, meta = get_prices(t, cfg, refresh=refresh)
            manifest[t] = meta
            rows.append(check_prices(t, df, cfg["jump_threshold"]))
            print(f"ok    {t:8s} {meta['rows']:6d} rows  {meta['first']} -> {meta['last']}  [{meta['source']}]")
            if meta["fetched_at"]:
                time.sleep(cfg["pause_seconds"])
        except Exception as e:
            rows.append(failed_row(t, "fetch_failed", str(e)))
            print(f"FAIL  {t}: {e}")

    report = pd.DataFrame(rows)
    out = Path(cfg["report_dir"]) / "data_quality.csv"
    report.to_csv(out, index=False)

    version = data_version(manifest)
    (Path(cfg["data_dir"]) / "manifest.json").write_text(json.dumps(
        {"data_version": version, "universe_snapshot": snap, "tickers": manifest}, indent=2))

    n_bad = int((report["status"] != "fetched").sum())
    print(f"\nData version: {version}  |  universe snapshot: {snap}")
    print(f"Quality report: {out}")
    if n_bad:
        print(f"WARNING: {n_bad} ticker(s) failed. See the report.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download prices even if cached")
    ap.add_argument("--refresh-universe", action="store_true", help="pull a new constituent snapshot")
    ap.add_argument("--limit", type=int, default=0, help="only fetch the first N tickers (testing)")
    a = ap.parse_args()
    main(a.refresh, a.refresh_universe, a.limit)