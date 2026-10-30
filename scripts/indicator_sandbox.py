"""Indicator-redundancy sandbox.

Answers: "does this candidate indicator add information the current features don't
already have?" and, separately, "which current features are mostly explained by the
others?" Uses only already-cached data (no pipeline run). Results are NOT patterns and
say nothing about whether an indicator predicts anything -- only whether it is new.

    python scripts/indicator_sandbox.py                 # active index, every ticker
    python scripts/indicator_sandbox.py --max-tickers 100 --stride 10    # quick look
    python scripts/indicator_sandbox.py --trim          # current features only: which could be cut?

--trim ignores every candidate. It removes, one at a time, the existing feature the others
explain best, re-scoring after each removal, and prints the order plus a ready-to-paste
`disabled_features:` line. Options: --threshold R2 (default 0.85), --drop a,b (remove these
first), --keep a,b (never remove), --max-remove N (stop after N removals).
--trim-candidates does the same among the CANDIDATES only (no existing features), to see which
proposals overlap each other.
--trim --include a,b,c [--exclude x,y] runs ONE elimination over the existing features (minus
--exclude, which are left out up front and are not counted as steps) plus the named candidates
together: the combined test.
In the normal (non-trim) run, --drop a,b scores the candidates against the existing features
WITHOUT those (e.g. the set left after a trim).

Candidates live in src/patternlab/candidates.py; add a function there to try another.
Outputs: a printed summary plus CSVs in reports/<index>/ (indicator_sandbox_*.csv).
"""
import argparse
import time
import numpy as np
import pandas as pd
from patternlab.candidates import (compute_candidates, market_candidates, cross_sectional_rank)
from patternlab.clean import load_clean
from patternlab.config import load_config, index_data_dir, report_dir_for
from patternlab.redundancy import (R2_REDUNDANT, candidate_report, explained_by_others, feature_pairs, trim_order)
from patternlab.universe_fetch import get_universe, get_index_proxy

NON_FEATURES = {"tradable", "month"}          # month is categorical; tradable is a flag


def load_vix(cfg: dict):
    """Cached ^VIX closes if present; otherwise one fetch. None if unavailable."""
    path = index_data_dir(cfg, "raw") / "^VIX.parquet"
    try:
        if path.exists():
            return pd.read_parquet(path)["adj_close"].dropna()
        from patternlab.fetch import get_prices
        return get_prices("^VIX", cfg, incremental=True)[0]["adj_close"].dropna()
    except Exception as e:                                                # noqa: BLE001
        print(f"  (VIX unavailable, skipping vix_pct_252: {e})")
        return None


def run_trim(cfg: dict, existing: pd.DataFrame, args, mode: str = "existing", cand_names=()) -> None:
    split = lambda v: [x.strip() for x in v.split(",") if x.strip()]
    steps, remaining = trim_order(existing, args.threshold, forced=split(args.drop),
                                  protected=split(args.keep), max_remove=args.max_remove)
    out = report_dir_for(cfg)
    csv_name = {"existing": "indicator_sandbox_trim.csv", "candidates": "indicator_sandbox_trim_candidates.csv",
                "combined": "indicator_sandbox_trim_combined.csv"}[mode]
    steps.insert(2, "kind", ["candidate" if f in set(cand_names) else "existing" for f in steps["feature"]])
    remaining.insert(1, "kind", ["candidate" if f in set(cand_names) else "existing" for f in remaining["feature"]])
    steps.to_csv(out / csv_name, index=False)
    pd.set_option("display.width", 200, "display.max_colwidth", 80)
    print(f"=== TRIM ORDER ({ {'existing': 'existing features only', 'candidates': 'candidates only', 'combined': 'existing + candidates together'}[mode] }; each R2 is against what was LEFT at that moment; threshold {args.threshold}) ===")
    print(steps.to_string(index=False) if len(steps) else "nothing reaches the threshold")
    print(f"\n=== REMAINING {len(remaining)} features and how much the rest explain each ===")
    print(remaining.to_string(index=False))
    if mode == "combined":
        ex_rm = [f for f in steps["feature"] if f not in set(cand_names)]
        ca_rm = [f for f in steps["feature"] if f in set(cand_names)]
        print(f"\nExisting features that this combined set would also trim: {', '.join(ex_rm) or 'none'}")
        print(f"Candidates that fall out (covered by what stays): {', '.join(ca_rm) or 'none'}")
        print(f"Candidates that survive: {', '.join(f for f in remaining['feature'] if f in set(cand_names)) or 'none'}")
        if ex_rm:
            print(f"disabled_features (on top of any earlier trims): [{', '.join(ex_rm)}]")
    elif mode == "candidates":
        print("\nThese are overlaps AMONG the proposals. Removed ones are mostly covered by the ones that stay; "
              "the remaining list is the set worth testing against the existing features.")
    elif len(steps):
        names = ", ".join(steps["feature"])
        print(f"\nTo test the first K removals, paste the first K names of this list into config.yaml (or the Settings feature toggles):")
        print(f"disabled_features: [{names}]")
    print(f"\nCSV written to {out / csv_name}")
    print("Reminder: overlap across the whole range does not prove two features find the same patterns -- "
          "that is what the discovery run is for. Removals are cumulative; the later ones only make sense with the earlier ones gone.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=5, help="keep every Nth bar per ticker (default 5)")
    ap.add_argument("--max-tickers", type=int, default=0, help="limit tickers (0 = all)")
    ap.add_argument("--trim", action="store_true", help="trim mode: existing features only, no candidates")
    ap.add_argument("--trim-candidates", action="store_true",
                    help="trim mode among the candidate indicators only (no existing features)")
    ap.add_argument("--include", default="", help="trim: candidate indicators to add to the trim set (combined test)")
    ap.add_argument("--exclude", default="", help="existing features to leave out up front (not counted as removals)")
    ap.add_argument("--threshold", type=float, default=R2_REDUNDANT, help="trim: stop when no feature reaches this R2")
    ap.add_argument("--drop", default="", help="trim: comma-separated features to remove first")
    ap.add_argument("--keep", default="", help="trim: comma-separated features never to remove")
    ap.add_argument("--max-remove", type=int, default=None, help="trim: stop after this many removals")
    args = ap.parse_args()
    args.trim = args.trim or args.trim_candidates

    cfg = load_config()
    thr = cfg.get("corr_prune_threshold", 0.7)
    uni = get_universe(cfg)
    feat_dir = index_data_dir(cfg, "features")
    tickers = [t for t in uni["data_ticker"] if (feat_dir / f"{t}.parquet").exists()]
    if args.max_tickers:
        tickers = tickers[:args.max_tickers]
    print(f"Index {cfg['index']}: {len(tickers)} tickers, every {args.stride}th bar. Loading...")

    t0 = time.time()
    proxy_close = load_clean(get_index_proxy(cfg["index"]), cfg)[0]["adj_close"]
    need_cands = (not args.trim) or args.trim_candidates or bool(args.include)
    market = market_candidates(proxy_close, load_vix(cfg)) if need_cands else pd.DataFrame(index=proxy_close.index)

    frames, ret5 = [], {}
    for t in tickers:
        try:
            f = pd.read_parquet(feat_dir / f"{t}.parquet")
            df, _ = load_clean(t, cfg)
            f = f.reindex(df.index) if not f.index.equals(df.index) else f
            cand = compute_candidates(df) if need_cands else pd.DataFrame(index=df.index)
            cand = cand.drop(columns=[c for c in cand.columns if c in f.columns])   # already a real feature
            ret5[t] = f["ret_5"]
            part = pd.concat([f, cand], axis=1)
            part = part[part["tradable"].eq(True)].iloc[::args.stride].copy()
            part["ticker"] = t
            frames.append(part)
        except Exception as e:                                            # noqa: BLE001
            print(f"  skipped {t}: {e}")
    panel = pd.concat(frames)
    existing_cols = [c for c in f.columns if c not in NON_FEATURES and c in panel.columns]
    excluded = [x.strip() for x in args.exclude.split(",") if x.strip()]
    bad = [x for x in excluded if x not in existing_cols]
    if bad:
        raise SystemExit(f"--exclude: unknown existing feature(s) {bad}; available: {existing_cols}")
    existing_cols = [c for c in existing_cols if c not in excluded]
    if args.trim and not args.trim_candidates and not args.include:
        print(f"Loaded {len(panel):,} sampled rows in {time.time() - t0:.0f}s.\n")
        run_trim(cfg, panel[existing_cols].astype("float64"), args)
        return
    xrank = cross_sectional_rank(ret5)
    panel = panel.join(market.drop(columns=[c for c in market.columns if c in panel.columns]), how="left")
    panel["ret_5_xrank"] = xrank.stack().reindex(
        pd.MultiIndex.from_arrays([panel.index, panel["ticker"]])).to_numpy()
    print(f"Loaded {len(panel):,} sampled rows in {time.time() - t0:.0f}s.\n")

    cand_cols = [c for c in list(compute_candidates(df).columns) + list(market.columns) + ["ret_5_xrank"]
                 if c in panel.columns and c not in existing_cols]
    dropped = ([] if args.trim else [x.strip() for x in args.drop.split(",") if x.strip()])
    unknown = [x for x in dropped if x not in existing_cols]
    if unknown:
        raise SystemExit(f"--drop: unknown existing feature(s) {unknown}; available: {existing_cols}")
    existing_cols = [c for c in existing_cols if c not in dropped]
    existing, cands = panel[existing_cols].astype("float64"), panel[cand_cols].astype("float64")
    if dropped:
        print(f"Scoring against {len(existing_cols)} existing features (excluding {', '.join(dropped)}).\n")
    if args.trim_candidates:
        run_trim(cfg, cands, args, mode="candidates", cand_names=cand_cols)
        return
    if args.trim:                                              # combined: existing + chosen candidates
        inc = [x.strip() for x in args.include.split(",") if x.strip()]
        bad = [x for x in inc if x not in cand_cols]
        if bad:
            raise SystemExit(f"--include: unknown candidate(s) {bad}; available: {cand_cols}")
        run_trim(cfg, panel[existing_cols + inc].astype("float64"), args, mode="combined", cand_names=inc)
        return

    report = candidate_report(existing, cands, thr)
    pairs_all = feature_pairs(pd.concat([existing, cands], axis=1), thr)
    cand_set = set(cand_cols)
    pairs_cand = pairs_all[pairs_all["feature_a"].isin(cand_set) | pairs_all["feature_b"].isin(cand_set)]
    pairs_exist = pairs_all[~(pairs_all["feature_a"].isin(cand_set) | pairs_all["feature_b"].isin(cand_set))]
    others = explained_by_others(existing)

    out = report_dir_for(cfg)
    report.to_csv(out / "indicator_sandbox_candidates.csv", index=False)
    pairs_all.to_csv(out / "indicator_sandbox_pairs.csv", index=False)
    others.to_csv(out / "indicator_sandbox_existing_features.csv", index=False)

    pd.set_option("display.width", 200, "display.max_colwidth", 70)
    print(f"=== CANDIDATES vs existing features  (REDUNDANT if |rho| >= {thr} or R2 >= 0.85; OVERLAPS if |rho| >= 0.5 or R2 >= 0.5) ===")
    print(report[["candidate", "verdict", "max_abs_rho", "r2_vs_all_existing", "closest_three"]].to_string(index=False))
    print(f"\n=== Pairs at or above |rho| {thr}: involving a candidate ===")
    print(pairs_cand.to_string(index=False) if len(pairs_cand) else "none")
    print(f"\n=== Pairs at or above |rho| {thr}: existing features only ===")
    print(pairs_exist.to_string(index=False) if len(pairs_exist) else "none")
    print("\n=== Existing features: how much the OTHER existing features explain each one (R2) ===")
    print(others.to_string(index=False))
    print(f"\nCSVs written to {out}")
    print("Reminder: this measures overlap only. A NEW indicator may still carry no pattern; a REDUNDANT "
          "one may still matter at its extremes. Rank correlation over the whole range can hide that.")


if __name__ == "__main__":
    main()
