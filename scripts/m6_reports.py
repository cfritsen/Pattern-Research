import argparse
import pandas as pd
from patternlab.config import load_config, ensure_dirs, report_dir_for
from patternlab.db import connect
from patternlab.reports import build_pattern_context, pattern_view, stock_view
from patternlab.humanize import humanize_pattern_view, humanize_stock_view

DISCLAIMER = ("This report shows historical statistical patterns in price data. It is "
             "descriptive research, not investment advice, and not a recommendation to "
             "buy or sell any security. Patterns are reported as \u201cfollowed by\u201d a "
             "historical outcome, never as a cause. Past patterns may not repeat. Trading "
             "involves risk of loss; you are solely responsible for your own decisions.")


def to_html(pattern_df: pd.DataFrame, worst_df: pd.DataFrame, stock_df: pd.DataFrame,
           ticker: str | None, edges_by_feature: dict[str, list[float]]) -> str:
    friendly_p = humanize_pattern_view(pattern_df, edges_by_feature)
    friendly_w = humanize_pattern_view(worst_df, edges_by_feature) if len(worst_df) else None
    friendly_s = humanize_stock_view(stock_df, edges_by_feature) if ticker and len(stock_df) else None
    parts = [
        "<html><head><meta charset='utf-8'><title>Pattern Research Report</title><style>",
        "body{font-family:sans-serif;max-width:1400px;margin:2em auto}",
        "table{border-collapse:collapse;width:100%;font-size:0.8em}",
        "td,th{border:1px solid #ccc;padding:5px 8px;text-align:right;vertical-align:top}",
        "th{background:#eee}td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}",
        ".note{background:#fff3cd;padding:0.75em;margin:1em 0;border-radius:4px}",
        ".cond{padding:2px 0;border-left:3px solid #ccc;padding-left:6px;margin-bottom:3px}",
        ".key{font-style:italic;color:#555;margin:0.25em 0 0.75em}",
        "</style></head><body><h1>Market Pattern Research Report</h1>",
        f"<div class='note'><b>{DISCLAIMER}</b></div>",
        "<h2>Strongest historical results (whole market)</h2>",
        "<p class='key'>Each pair of numbers shows: All Data / Index-Only Data. "
        "\u201c--\u201d means that view did not pass this pattern's statistical filters, "
        "or there wasn't enough data to check.</p>",
        friendly_p.to_html(index=False, escape=False)]
    if friendly_w is not None:
        parts += ["<h2>Weakest historical results (whole market)</h2>",
                 friendly_w.to_html(index=False, escape=False)]
    if ticker and friendly_s is not None:
        parts += [f"<h2>Strongest historical results for {ticker}</h2>",
                 friendly_s.to_html(index=False, escape=False)]
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    if args.ticker:
        args.ticker = args.ticker.upper()

    cfg = load_config()
    ensure_dirs(cfg)
    conn = connect(cfg)

    edges_by_feature: dict[str, list[float]] = {}
    for feat, idx, val in conn.execute(
            "SELECT feature, edge_index, edge_value FROM feature_bucket_edges ORDER BY feature, edge_index"):
        edges_by_feature.setdefault(feat, []).append(val)

    context = build_pattern_context(conn)
    pdf = pattern_view(context, args.top)
    wdf = pattern_view(context, args.top, worst=True)
    sdf = stock_view(conn, args.ticker, context, 5) if args.ticker else pd.DataFrame()

    out_dir = report_dir_for(cfg)
    pdf.to_csv(out_dir / "pattern_view.csv", index=False)
    wdf.to_csv(out_dir / "pattern_view_worst.csv", index=False)
    if args.ticker:
        sdf.to_csv(out_dir / f"stock_view_{args.ticker}.csv", index=False)
    (out_dir / "report.html").write_text(to_html(pdf, wdf, sdf, args.ticker, edges_by_feature), encoding="utf-8")

    print(f"Wrote {out_dir / 'pattern_view.csv'} ({len(pdf)} rows)")
    print(f"Wrote {out_dir / 'pattern_view_worst.csv'} ({len(wdf)} rows)")
    if args.ticker:
        print(f"Wrote {out_dir / f'stock_view_{args.ticker}.csv'} ({len(sdf)} rows)")
    print(f"Wrote {out_dir / 'report.html'}")


if __name__ == "__main__":
    main()