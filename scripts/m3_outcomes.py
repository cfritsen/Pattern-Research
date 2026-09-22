import json
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.clean import load_clean
from patternlab.outcomes import HORIZONS, compute_outcomes, split_labels, split_cutoff, hit_flags


def main() -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    uni = get_universe(cfg)
    feat_dir = Path(cfg["data_dir"]) / "features"
    out_dir = Path(cfg["data_dir"]) / "outcomes"
    out_dir.mkdir(parents=True, exist_ok=True)
    h0, move = cfg["horizon"], cfg["move_atr"]

    idx_df, _ = load_clean(cfg["index_proxy"], cfg)
    cutoff = split_cutoff(idx_df.index[0], idx_df.index[-1], cfg["discovery_frac"])
    print(f"Discovery: before {cutoff.date()}   Confirm: {cutoff.date()} onward")

    frames, failed, coverage = [], [], Counter()
    for t in uni["data_ticker"]:
        try:
            df, _ = load_clean(t, cfg)
            f = pd.read_parquet(feat_dir / f"{t}.parquet", columns=["atr_pct", "tradable", "in_index"])
            if not f.index.equals(df.index):
                raise ValueError(f"feature/price date mismatch: "
                                  f"features {f.index[0].date()}-{f.index[-1].date()} ({len(f)} rows), "
                                  f"prices {df.index[0].date()}-{df.index[-1].date()} ({len(df)} rows)")
            o = pd.concat([compute_outcomes(df["adj_close"]), split_labels(df.index, cutoff)], axis=1)
            o["up_hit"], o["down_hit"] = hit_flags(o[f"fwd_ret_{h0}"], f["atr_pct"], move)
            o["tradable"], o["in_index"] = f["tradable"], f["in_index"]
            fc = [c for c in o.columns if c.startswith("fwd_ret_")]
            o[fc] = o[fc].astype("float32")
            o.to_parquet(out_dir / f"{t}.parquet")
            frames.append(o)
            coverage.update(set(o.index.year[o["tradable"].to_numpy()]))
        except Exception as e:
            failed.append((t, repr(e)))
            if len(failed) <= 3:
                print(f"FAIL {t}: {e}")

    if not frames:
        print(f"\nAll {len(failed)} tickers failed. First few:")
        for t, e in failed[:5]:
            print(f"  {t}: {e}")
        return

    panel = pd.concat(frames)
    del frames
    fwd_cols = [f"fwd_ret_{h}" for h in HORIZONS]

    market = panel[fwd_cols].where(panel["tradable"]).groupby(level=0).mean()
    market["n_stocks"] = panel["tradable"].groupby(level=0).sum()
    market.to_parquet(out_dir / "_market_mean.parquet")

    rows = []
    for view, vmask in (("all", panel["tradable"]), ("flagged", panel["tradable"] & panel["in_index"])):
        for h in HORIZONS:
            r = panel[f"fwd_ret_{h}"].astype("float64")
            for name, code in (("discovery", 0), ("confirm", 1)):
                m = vmask & (panel[f"split_{h}"] == code) & r.notna()
                x = r[m]
                row = dict(view=view, split=name, horizon=h, n=int(m.sum()), mean_ret=x.mean(),
                           median_ret=x.median(), std_ret=x.std(), up_hit=np.nan, down_hit=np.nan)
                if h == h0:
                    mh = m & panel["up_hit"].notna()
                    row["up_hit"] = float(panel.loc[mh, "up_hit"].mean())
                    row["down_hit"] = float(panel.loc[mh, "down_hit"].mean())
                rows.append(row)
    base = pd.DataFrame(rows)
    base.to_csv(Path(cfg["report_dir"]) / "baselines.csv", index=False)

    (out_dir / "_meta.json").write_text(json.dumps(
        {"cutoff": str(cutoff.date()), "default_horizon": h0, "move_atr": move,
         "horizons": list(HORIZONS), "rows": int(len(panel))}, indent=2))

    print(f"\n{len(panel):,} rows, {len(uni) - len(failed)} tickers")
    print("\nStocks with tradable data, by year:")
    print({y: coverage[y] for y in (1996, 2000, 2005, 2010, 2015, 2018, 2025)})
    print(f"\nBaselines at horizon {h0}:")
    print(base[base["horizon"] == h0].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    if failed:
        print(f"\n{len(failed)} failed:")
        for t, e in failed[:20]:
            print(f"  {t}: {e}")


if __name__ == "__main__":
    main()