# scripts\m1_review.py
import pandas as pd
from pathlib import Path

q = pd.read_csv("reports/data_quality.csv")
print(q["status"].value_counts().to_string())
print("sources:", q["source"].value_counts().to_dict())
print(f"\nrows per ticker: min {q['rows'].min()}, median {int(q['rows'].median())}")
print("shortest histories:")
print(q.nsmallest(10, "rows")[["ticker", "first", "rows"]].to_string(index=False))

for col in ["zero_volume_bars", "nonpositive_prices", "high_below_low"]:
    bad = q[q[col] > 0]
    print(f"\n{col} > 0: {len(bad)} tickers")
    if len(bad):
        print(bad[["ticker", col]].sort_values(col, ascending=False).head(10).to_string(index=False))

print("\nmost >25% jumps:")
print(q.nlargest(10, "jumps_over_threshold")[["ticker", "jumps_over_threshold"]].to_string(index=False))

# moves near common split ratios (expect a few real events among them)
ratios = [2, 3, 4, 5, 10, 1/2, 1/3, 1/4, 1/5, 1/10, 3/2, 2/3]
sus = []
for p in Path("data/raw").glob("*.parquet"):
    r = pd.read_parquet(p)["adj_close"].pct_change().dropna()
    for d, v in r[r.abs() > 0.25].items():
        if any(abs((1 + v) - s) / s < 0.03 for s in ratios):
            sus.append((p.stem, d.date(), f"{v:+.1%}"))
print(f"\nsplit-like jumps: {len(sus)}")
for s in sus:
    print(*s)