import argparse
import json
import time
from pathlib import Path
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe import load_universe
from patternlab.fetch import get_prices, data_version
from patternlab.quality import check_prices, failed_row


def main(refresh: bool) -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = load_universe(cfg["universe_csv"])

    rows, manifest = [], {}
    for _, r in uni.iterrows():
        if r["data_status"] == "missing":
            rows.append(failed_row(r["ticker"], "flagged_missing", "marked missing in universe CSV"))

    targets = [t for t in uni.loc[uni["data_status"] != "missing", "data_ticker"]]
    targets.append(cfg["index_proxy"])
    targets = list(dict.fromkeys(targets))           # dedupe, keep order

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
    (Path(cfg["data_dir"]) / "manifest.json").write_text(
        json.dumps({"data_version": version, "tickers": manifest}, indent=2))

    n_bad = int((report["status"] != "fetched").sum())
    print(f"\nData version: {version}")
    print(f"Quality report: {out}")
    if n_bad:
        print(f"WARNING: {n_bad} ticker(s) missing or failed. See the report.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    main(ap.parse_args().refresh)