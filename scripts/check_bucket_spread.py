# scripts/check_bucket_spread.py
import sqlite3
from patternlab.config import load_config

cfg = load_config()
conn = sqlite3.connect(f"{cfg['data_dir']}/results_{cfg['index']}.db")

query = """
SELECT p.n_conditions,
       SUM(CASE WHEN json_extract(p.conditions_json,'$[0].bucket') IN (0,4) 
                 AND (p.n_conditions=1 OR json_extract(p.conditions_json,'$[1].bucket') IN (0,4))
                THEN 1 ELSE 0 END) AS extreme_only,
       COUNT(*) AS total
FROM pattern_results_pooled r JOIN patterns p ON p.pattern_id=r.pattern_id
WHERE r.split='discovery' AND r.passed=1
GROUP BY p.n_conditions
"""

for row in conn.execute(query):
    print(row)