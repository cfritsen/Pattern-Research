from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from patternlab.config import load_config, ensure_dirs
from patternlab.db import connect
from patternlab.reports import build_pattern_context, pattern_view, to_api_rows
from patternlab.humanize import humanize_pattern_view
from patternlab.universe_fetch import PROVIDERS


STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
app = Flask(__name__, static_folder=None)
app.json.sort_keys = False


def _cfg_for(index: str) -> dict:
    # index is already checked against PROVIDERS by the caller below, so
    # overriding it here without re-validating the whole config is safe.
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


if __name__ == "__main__":
    app.run(port=5151, debug=True)