import os
import subprocess
import sys
import pandas as pd
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from patternlab.config import (
    load_config, ensure_dirs, read_raw_config, save_config,
    validate_config, ConfigError, VALID_HORIZONS,
)
from patternlab.db import connect
from patternlab.reports import build_pattern_context, pattern_view, to_api_rows, stock_view, stock_to_api_rows, passes_direction_filter
from patternlab.humanize import badge_text, FEATURE_INFO, ALL_FEATURES, conditions_html
from patternlab.universe_fetch import get_universe, get_index_proxy, PROVIDERS
from patternlab.jobs import start_job, get_status, discovery_status, STAGES
from patternlab.watchlist import compute_watchlist, load_edges, compute_matching_table, matching_table_to_api_rows, compute_pattern_matches, compute_month_patterns_context, compute_month_stock_matches


STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
app = Flask(__name__, static_folder=None)
app.json.sort_keys = False

# "folder" fields get an Open Folder button instead of a text input (see
# api_open_folder below). This is desktop-only functionality -- a hosted
# web app has no way to open a folder on the SERVER's machine for a remote
# user, so this route and these buttons are app-build-only and should be
# dropped (or replaced with something else, e.g. a download link) when a
# hosted version is built.
FIELD_METADATA = [
    {"key": "index", "label": "Index", "type": "select", "options": None,
     "help": "Which index's current constituents to use. The benchmark/proxy ticker is derived automatically from this."},
    {"key": "start_date", "label": "Start date", "type": "string",
     "help": "Earliest date to fetch price history from (YYYY-MM-DD)."},
    {"key": "use_stooq_fallback", "label": "Use Stooq fallback", "type": "boolean",
     "help": "Fall back to Stooq if yfinance fails for a ticker."},
    {"key": "jump_threshold", "label": "Jump threshold", "type": "number", "min": 0, "step": 0.01,
     "help": "A day's price move larger than this (as a fraction, 0.25 = 25%) gets flagged in the data-quality report."},
    {"key": "pause_seconds", "label": "Pause between fetches (seconds)", "type": "number", "min": 0, "step": 0.1,
     "help": "Seconds to wait between price-fetch requests, to be kind to the data provider's servers."},
    {"key": "horizon", "label": "Horizon (bars)", "type": "select", "options": list(VALID_HORIZONS),
     "help": "Forward-return horizon the search is run against. Must be one of the pre-computed horizons."},
    {"key": "move_atr", "label": "Move size (ATR multiple)", "type": "number", "min": 0.01, "step": 0.1,
     "help": "Size of the \"move\" outcome, in units of that bar's own ATR%."},
    {"key": "discovery_frac", "label": "Discovery fraction", "type": "number", "min": 0.01, "max": 0.99, "step": 0.01,
     "help": "Fraction of the date range used for discovery (vs. confirmation)."},
    {"key": "cost", "label": "Assumed trading cost", "type": "number", "min": 0, "step": 0.0001,
     "help": "Assumed round-trip trading cost, as a fraction of price (0.001 = 0.1%)."},
    {"key": "corr_prune_threshold", "label": "Correlation prune threshold", "type": "number", "min": 0.01, "max": 0.99, "step": 0.01,
     "help": "Feature pairs with |Spearman correlation| above this are excluded from 2-condition testing."},
    {"key": "test_all_buckets", "label": "Test all buckets (full grid)", "type": "boolean",
     "help": "Off: 2-condition search only tests the extreme buckets of each continuous feature (faster). On: tests the full 5x5 grid (much slower)."},
    {"key": "multithreading", "label": "Multithreading", "type": "boolean",
     "help": "Run the 2-condition search across multiple CPU cores instead of one."},
]


def _cfg_for(index: str) -> dict:
    cfg = dict(load_config())
    cfg["index"] = index
    ensure_dirs(cfg)
    return cfg


@app.get("/")
def index_page():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.get("/api/indices")
def api_indices():
    return jsonify(sorted(PROVIDERS))


@app.get("/api/patterns")
def api_patterns():
    index = request.args.get("index", "sp500")
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400

    cfg = _cfg_for(index)
    conn = connect(cfg)
    edges_by_feature: dict[str, list[float]] = {}
    for feat, idx, val in conn.execute(
            "SELECT feature, edge_index, edge_value FROM feature_bucket_edges ORDER BY feature, edge_index"):
        edges_by_feature.setdefault(feat, []).append(val)

    context = build_pattern_context(conn)
    return jsonify(to_api_rows(context, edges_by_feature))


@app.get("/api/config")
def api_get_config():
    cfg = read_raw_config()
    errors = None
    try:
        validate_config(dict(cfg))
    except ConfigError as e:
        errors = str(e)
    meta = [dict(f) for f in FIELD_METADATA]
    for f in meta:
        if f["key"] == "index":
            f["options"] = sorted(PROVIDERS)
        if f["key"] == "multithreading":
            from patternlab.parallel import resolved_worker_count
            on_count = resolved_worker_count({**cfg, "multithreading": True})
            f["help"] += f" (currently resolves to {on_count} worker{'s' if on_count != 1 else ''} when on)"
    feature_meta = [{"key": f, "label": FEATURE_INFO[f][0] if f in FEATURE_INFO else f.capitalize()}
                    for f in ALL_FEATURES]
    return jsonify({"config": cfg, "fields": meta, "errors": errors, "all_features": feature_meta})


@app.post("/api/config")
def api_save_config():
    cfg = request.get_json()
    try:
        save_config(cfg)
    except ConfigError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"status": "ok"})


# Desktop-app-only. See the FIELD_METADATA comment above -- a hosted web
# version has no equivalent and should not expose this route.
@app.get("/api/open-folder")
def api_open_folder():
    which = request.args.get("which")
    if which not in ("data_dir", "report_dir"):
        return jsonify({"error": f"Unknown folder {which!r}"}), 400

    cfg = read_raw_config()
    path = Path(cfg.get(which, which.replace("_dir", "")))
    path.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True)
        else:
            subprocess.run(["xdg-open", str(path)], check=True)
    except Exception as e:
        return jsonify({"error": f"Couldn't open {path}: {e}"}), 500
    return jsonify({"status": "ok"})

@app.post("/api/jobs/start")
def api_jobs_start():
    body = request.get_json() or {}
    ok, msg = start_job(body.get("job"))
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "started"})


@app.get("/api/jobs/status")
def api_jobs_status():
    status = get_status()
    status["stages_meta"] = STAGES
    status["discovery"] = discovery_status()
    return jsonify(status)

@app.get("/api/watchlist")
def api_watchlist():
    cfg0 = read_raw_config()
    index = request.args.get("index", cfg0.get("index", "sp500"))
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400

    cfg = _cfg_for(index)
    uni = get_universe(cfg)
    conn = connect(cfg)
    matches = compute_watchlist(cfg, uni, conn)
    for m in matches:
        m["badge"] = badge_text(m["conditions"])
    return jsonify(matches)


@app.get("/api/stock-research")
def api_stock_research():
    cfg0 = read_raw_config()
    index = request.args.get("index", cfg0.get("index", "sp500"))
    ticker = request.args.get("ticker", "").upper().strip()
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    cfg = _cfg_for(index)
    uni = get_universe(cfg)
    conn = connect(cfg)
    edges_by_feature = load_edges(conn)
    context = build_pattern_context(conn)
    # Same direction-consistency filter Market Research and the Watchlist
    # already apply -- without it, Per Stock showed patterns that had
    # already been excluded everywhere else (confirm-period reversals).
    kept = context[context.apply(passes_direction_filter, axis=1)] if not context.empty else context
    sdf = stock_view(conn, ticker, kept, top_n=100000)

    live_matches = compute_watchlist(cfg, uni, conn, only_ticker=ticker)
    live_ids = {m["pattern_id"] for m in live_matches}

    return jsonify(stock_to_api_rows(sdf, edges_by_feature, live_ids))

@app.get("/api/stock-matching")
def api_stock_matching():
    cfg0 = read_raw_config()
    index = request.args.get("index", cfg0.get("index", "sp500"))
    ticker = request.args.get("ticker", "").upper().strip()
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    cfg = _cfg_for(index)
    uni = get_universe(cfg)
    conn = connect(cfg)
    edges_by_feature = load_edges(conn)
    rows = compute_matching_table(cfg, uni, conn, ticker)
    return jsonify(matching_table_to_api_rows(rows, edges_by_feature))

@app.get("/api/pattern-matches")
def api_pattern_matches():
    cfg0 = read_raw_config()
    index = request.args.get("index", cfg0.get("index", "sp500"))
    try:
        pattern_id = int(request.args.get("pattern_id", ""))
    except ValueError:
        return jsonify({"error": "pattern_id must be an integer"}), 400
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400

    cfg = _cfg_for(index)
    uni = get_universe(cfg)
    conn = connect(cfg)
    edges_by_feature = load_edges(conn)
    context = build_pattern_context(conn)
    if context.empty or pattern_id not in context.index:
        return jsonify({"error": "Pattern not found"}), 404
    prow = context.loc[pattern_id]

    meta = {
        "pattern_id": pattern_id,
        "conditions_html": conditions_html(prow["description"], edges_by_feature),
        "baseline_mean_all": None if pd.isna(prow["baseline_mean_all"]) else float(prow["baseline_mean_all"]),
        "baseline_mean_flagged": None if pd.isna(prow["baseline_mean_flagged"]) else float(prow["baseline_mean_flagged"]),
    }
    matches = compute_pattern_matches(cfg, uni, conn, pattern_id)
    return jsonify({"pattern": meta, "matches": matches})

@app.get("/api/date-insights/patterns")
def api_date_insights_patterns():
    cfg0 = read_raw_config()
    index = request.args.get("index", cfg0.get("index", "sp500"))
    try:
        month = int(request.args.get("month", ""))
    except ValueError:
        return jsonify({"error": "month must be an integer 1-12"}), 400
    if not 1 <= month <= 12:
        return jsonify({"error": "month must be between 1 and 12"}), 400
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400
    cfg = _cfg_for(index)
    conn = connect(cfg)
    edges_by_feature = load_edges(conn)
    context = compute_month_patterns_context(conn, month)
    return jsonify(to_api_rows(context, edges_by_feature))


@app.get("/api/date-insights/stocks")
def api_date_insights_stocks():
    cfg0 = read_raw_config()
    index = request.args.get("index", cfg0.get("index", "sp500"))
    try:
        month = int(request.args.get("month", ""))
    except ValueError:
        return jsonify({"error": "month must be an integer 1-12"}), 400
    if not 1 <= month <= 12:
        return jsonify({"error": "month must be between 1 and 12"}), 400
    if index not in PROVIDERS:
        return jsonify({"error": f"Unknown index {index!r}"}), 400
    cfg = _cfg_for(index)
    conn = connect(cfg)
    matches = compute_month_stock_matches(conn, month)
    return jsonify(matches)

if __name__ == "__main__":
    # threaded=True so status polls are served while a job's background
    # thread is running; use_reloader=False so an in-progress job isn't
    # lost if the dev-reloader restarts the process (e.g. editing a .py
    # file while a 20+ minute job is running).
    app.run(port=5151, debug=True, threaded=True, use_reloader=False)