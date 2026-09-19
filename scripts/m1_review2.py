# scripts\m1_review2.py
import pandas as pd
from pathlib import Path

rows = []
for p in sorted(Path("data/raw").glob("*.parquet")):
    df = pd.read_parquet(p)
    r = df["adj_close"].pct_change()
    for d, v in r[r.abs() > 0.25].items():
        i = df.index.get_loc(d)
        base = df["volume"].iloc[max(0, i - 20):i].mean()
        ratio = df["volume"].iloc[i] / base if base > 0 else float("nan")
        rows.append((p.stem, d.date(), round(v * 100, 1), round(ratio, 1)))

out = pd.DataFrame(rows, columns=["ticker", "date", "move_pct", "volume_x_avg"])
weak = out[(out["volume_x_avg"] < 2) | out["volume_x_avg"].isna()]
print("Big moves with under 2x normal volume (or no volume data):")
print(weak.to_string(index=False))
print(f"\n{len(out)} big moves total, median volume {out['volume_x_avg'].median():.1f}x normal\n")

q = pd.read_csv("reports/data_quality.csv")
for t in q.nlargest(8, "zero_volume_bars")["ticker"]:
    df = pd.read_parquet(f"data/raw/{t}.parquet")
    z = df.index[df["volume"] == 0]
    nz = df.index[df["volume"] > 0]
    print(f"{t}: history {df.index[0].date()} to {df.index[-1].date()}, "
          f"zero-volume {z[0].date()} to {z[-1].date()} ({len(z)} bars), "
          f"first traded bar {nz[0].date()}")