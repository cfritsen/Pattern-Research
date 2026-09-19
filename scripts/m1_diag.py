# scripts\m1_diag.py
import pandas as pd

for t in ["CRH", "MNST", "ODFL", "TTWO"]:
    df = pd.read_parquet(f"data/raw/{t}.parquet")
    z = df["volume"] == 0
    grp = (z != z.shift()).cumsum()
    runs = [(g.index[0].date(), len(g)) for _, g in z.groupby(grp)
            if g.iloc[0] and len(g) >= 3]
    print(f"{t}: {int(z.sum())} zero-volume bars; runs of 3+: {runs[:8]}")

df = pd.read_parquet("data/raw/CRH.parquet")
print("\nCRH around the end of its zero-volume period:")
print(df.loc["1999-05-20":"1999-06-03", ["close", "volume"]])