from __future__ import annotations
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_version TEXT NOT NULL,
    universe_snapshot TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patterns (
    pattern_id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    n_conditions INTEGER NOT NULL,
    UNIQUE(conditions_json)
);

CREATE TABLE IF NOT EXISTS pattern_results_pooled (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id INTEGER NOT NULL REFERENCES patterns(pattern_id),
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    view TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    outcome_type TEXT NOT NULL,
    split TEXT NOT NULL,
    n_occurrences INTEGER NOT NULL,
    mean_fwd_return REAL,
    baseline_mean REAL,
    hit_rate REAL,
    baseline_hit_rate REAL,
    effect REAL,
    p_value REAL,
    q_value REAL,
    ci_low REAL,
    ci_high REAL,
    breadth_stocks REAL,
    breadth_years REAL,
    passed INTEGER
);
CREATE INDEX IF NOT EXISTS idx_results_run ON pattern_results_pooled(run_id);
CREATE INDEX IF NOT EXISTS idx_results_pattern ON pattern_results_pooled(pattern_id);
"""


def connect(cfg: dict) -> sqlite3.Connection:
    path = Path(cfg["data_dir"]) / "results.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def insert_run(conn: sqlite3.Connection, settings: dict, data_version: str, universe_snapshot: str) -> int:
    from datetime import datetime, timezone
    cur = conn.execute(
        "INSERT INTO runs (settings_json, created_at, data_version, universe_snapshot) VALUES (?, ?, ?, ?)",
        (json.dumps(settings, sort_keys=True), datetime.now(timezone.utc).isoformat(timespec="seconds"),
         data_version, universe_snapshot))
    conn.commit()
    return cur.lastrowid


def get_or_create_pattern(conn: sqlite3.Connection, description: str, conditions: list) -> int:
    cj = json.dumps(conditions, sort_keys=True)
    row = conn.execute("SELECT pattern_id FROM patterns WHERE conditions_json = ?", (cj,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO patterns (description, conditions_json, n_conditions) VALUES (?, ?, ?)",
        (description, cj, len(conditions)))
    conn.commit()
    return cur.lastrowid


def insert_result(conn: sqlite3.Connection, row: dict) -> None:
    cols = ", ".join(row.keys())
    qs = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO pattern_results_pooled ({cols}) VALUES ({qs})", tuple(row.values()))