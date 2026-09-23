from patternlab.config import load_config, ensure_dirs
from patternlab.universe_fetch import get_universe
from patternlab.search import load_panel, build_buckets
from patternlab.stats import thin_non_overlapping

cfg = load_config()
ensure_dirs(cfg)
uni = get_universe(cfg)
h0 = cfg["horizon"]
panel, feature_cols = load_panel(cfg, uni)
is_disc = panel[f"split_{h0}"] == 0
buckets, _ = build_buckets(panel, feature_cols, is_disc)

for view_name, vmask in (("all", panel["in_index"] | True), ("flagged", panel["in_index"])):
    mask = vmask & is_disc & (buckets["dist_52w_high"] == 0) & (buckets["month"] == 4)
    sub = panel[mask]
    keep = thin_non_overlapping(sub["bar_pos"], sub["ticker"], h0)
    thin = sub[keep]
    by_year = thin.groupby("year")[f"fwd_ret_{h0}"].agg(["count", "mean"]).sort_values("count", ascending=False)
    print(f"\n{view_name} view -- dist_52w_high bucket 0 AND month=4 (April), by year, sorted by occurrence count:")
    print(by_year.to_string(float_format=lambda x: f"{x:.4f}"))
    print(f"top-3 years: {by_year.head(3).index.tolist()}, "
         f"their mean returns: {by_year.head(3)['mean'].round(4).tolist()}")