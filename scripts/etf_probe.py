"""ETF probe: can Yahoo (via yfinance) supply what an ETF universe needs?

For each candidate ticker it records AUM (totalAssets), category, fund family,
average volume, expense ratio, and price-history depth (first bar, years of
history). Throttled by config.yaml's pause_seconds. Writes a CSV next to the
universe snapshots and prints a summary of what came back empty.

Candidates are a hand-picked list of large, liquid, plain-vanilla ETFs. NO
leveraged or inverse funds. The list is chosen from general knowledge of what
is big; the AUM column here is what actually ranks them.

Run from the project root:  python scripts/etf_probe.py
"""
from __future__ import annotations
import time
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

from patternlab.config import load_config

CANDIDATES = {
    "US broad": "SPY VOO IVV VTI QQQ QQQM IWM DIA MDY IJH IJR VB VO VV RSP SCHB ITOT SCHX IWB IWV OEF",
    "US style": "IWF IWD VUG VTV VBR VBK IVW IVE IWN IWO SCHG MGK",
    "US sector": "XLK XLF XLE XLV XLY XLP XLI XLB XLU XLRE XLC VGT VHT VFH VDE VIS VCR VDC VAW VPU",
    "US industry": "SMH SOXX XBI IBB KRE KBE XOP OIH XHB ITB XRT IYR VNQ ITA JETS IGV",
    "Dividend/factor": "VYM SCHD DVY HDV VIG DGRO NOBL SPHD MTUM QUAL USMV VLUE SPLV",
    "International": "EFA IEFA VEA VWO IEMG EEM VXUS IXUS EWJ EWZ EWW EWY EWT EWG EWU EWC EWA FXI MCHI INDA EZU VGK ACWI VT SCZ",
    "Bonds": "AGG BND TLT IEF SHY LQD HYG JNK TIP MUB BNDX EMB VCIT VCSH BIL SGOV IEI GOVT SHV MBB BSV BIV IGSB",
    "Commodities/FX": "GLD IAU SLV USO UNG DBC GDX GDXJ PDBC CPER DBA UUP FXE FXY GLDM URA COPX PPLT",
    "Thematic": "ARKK ICLN TAN LIT BOTZ SKYY CIBR HACK",
}

FIELDS = ["totalAssets", "netAssets", "category", "fundFamily", "quoteType",
          "averageVolume", "netExpenseRatio", "annualReportExpenseRatio"]


def probe(ticker: str) -> dict:
    row = {"ticker": ticker}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:                              # noqa: BLE001
        info, row["info_error"] = {}, str(e)[:80]
    for k in FIELDS:
        row[k] = info.get(k)
    try:
        h = yf.Ticker(ticker).history(period="max", auto_adjust=False)
        row["first_bar"] = h.index[0].date().isoformat() if len(h) else None
        row["bars"] = len(h)
    except Exception as e:                              # noqa: BLE001
        row["first_bar"], row["bars"] = None, 0
        row["hist_error"] = str(e)[:80]
    return row


def main() -> None:
    cfg = load_config()
    pause = cfg.get("pause_seconds", 0.5)
    seen, rows = set(), []
    for group, tickers in CANDIDATES.items():
        for t in tickers.split():
            if t in seen:
                continue
            seen.add(t)
            r = probe(t)
            r["group"] = group
            rows.append(r)
            aum = r.get("totalAssets") or r.get("netAssets")
            print(f"{t:6s} {group:16s} AUM={'--' if not aum else f'{aum/1e9:,.1f}B':>9s}  first={r['first_bar']}")
            time.sleep(pause)

    df = pd.DataFrame(rows)
    df["aum"] = df["totalAssets"].fillna(df["netAssets"])
    df["years"] = ((pd.Timestamp.today() - pd.to_datetime(df["first_bar"])).dt.days / 365.25).round(1)
    df = df.sort_values("aum", ascending=False, na_position="last")

    out = Path(cfg["data_dir"]) / "universe" / f"etf_probe_{date.today().isoformat()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    n = len(df)
    print(f"\n=== SUMMARY ({n} tickers) -> {out} ===")
    print(f"AUM missing:      {df['aum'].isna().sum()}")
    print(f"category missing: {df['category'].isna().sum()}")
    print(f"no price history: {(df['bars'].fillna(0) == 0).sum()}")
    print(f"< 10 years of history: {(df['years'] < 10).sum()}   < 5 years: {(df['years'] < 5).sum()}")
    print("\nMissing AUM:", ", ".join(df.loc[df['aum'].isna(), 'ticker']) or "none")
    print("Short history (<10y):", ", ".join(df.loc[df['years'] < 10, 'ticker']) or "none")
    print("\nTop 15 by AUM:")
    print(df[["ticker", "group", "aum", "years"]].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
