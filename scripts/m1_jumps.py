# scripts\m1_jumps.py
import pandas as pd
from pathlib import Path

for p in sorted(Path("data/raw").glob("*.parquet")):
    r = pd.read_parquet(p)["adj_close"].pct_change()
    for d, v in r[r.abs() > 0.25].items():
        print(f"{p.stem:6s} {d.date()}  {v:+.1%}")