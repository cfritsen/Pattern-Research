# scripts/check_month_coverage.py
import json
import sqlite3
from patternlab.config import load_config

cfg = load_config()
conn = sqlite3.connect(f"{cfg['data_dir']}/results_{cfg['index']}.db")

rows = conn.execute(
    "SELECT p.conditions_json FROM pattern_results_pooled r "
    "JOIN patterns p ON p.pattern_id = r.pattern_id "
    "WHERE r.split='discovery' AND r.passed=1"
).fetchall()

from collections import Counter
counts = Counter()
for (cj,) in rows:
    for c in json.loads(cj):
        if c["feature"] == "month":
            counts[c["bucket"]] += 1

for m in range(1, 13):
    print(m, counts.get(m, 0))