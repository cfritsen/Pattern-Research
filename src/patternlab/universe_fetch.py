from __future__ import annotations
import io
from datetime import date
from pathlib import Path
import pandas as pd
import requests
from patternlab.universe import load_snapshot

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HEADERS = {"User-Agent": "patternlab/0.1 (personal research tool)"}
NEEDED = ["Symbol", "Security", "GICS Sector", "Date added"]


def to_data_ticker(symbol: str) -> str:
    return symbol.strip().replace(".", "-")


def validate_snapshot(df: pd.DataFrame, lo: int = 450, hi: int = 520) -> None:
    if not lo <= len(df) <= hi:
        raise RuntimeError(f"Suspicious constituent count: {len(df)} (expected {lo}-{hi})")
    if df["ticker"].duplicated().any():
        raise RuntimeError("Duplicate tickers in constituent table")


def fetch_sp500() -> pd.DataFrame:
    resp = requests.get(WIKI_SP500, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    table = next((t for t in tables if all(c in t.columns for c in NEEDED)), None)
    if table is None:
        raise RuntimeError("Constituents table not found; the page layout may have changed")
    added = table["Date added"].astype(str).str.extract(r"(\d{4}-\d{2}-\d{2})")[0]
    df = pd.DataFrame({
        "ticker": table["Symbol"].astype(str).str.strip(),
        "company": table["Security"].astype(str).str.strip(),
        "sector": table["GICS Sector"].astype(str).str.strip(),
        "date_added": pd.to_datetime(added, errors="coerce"),
    })
    df["data_ticker"] = df["ticker"].map(to_data_ticker)
    return df


PROVIDERS = {"sp500": fetch_sp500}   # add other indices or a paid provider here

# The benchmark ticker used per index for relative-strength features (M2).
# Add an entry here whenever a new index loader is added to PROVIDERS.
INDEX_PROXIES = {
    "sp500": "SPY",
    # "nasdaq100": "QQQ",   # example for when that loader is added
    # "dow": "DIA",         # example for when that loader is added
}

# Fixed reference used ONLY for the discovery/confirm date-split boundary
# (M3). Deliberately NOT index-derived: pinning the split to one ticker,
# regardless of which index is active, keeps data/outcomes/ files identical
# (and therefore shareable) across indices -- otherwise the same historical
# bar could land in "discovery" under one index and "confirm" under
# another, depending only on which index happened to be configured.
MARKET_REFERENCE = "SPY"


def get_index_proxy(index: str) -> str:
    try:
        return INDEX_PROXIES[index]
    except KeyError:
        raise ValueError(
            f"No proxy ticker registered for index {index!r}. "
            f"Add it to INDEX_PROXIES in universe_fetch.py.")


def get_universe(cfg: dict, refresh: bool = False) -> pd.DataFrame:
    index = cfg["index"]
    folder = Path(cfg["data_dir"]) / "universe"
    folder.mkdir(parents=True, exist_ok=True)
    snaps = sorted(folder.glob(f"{index}_*.csv"))
    if snaps and not refresh:
        return load_snapshot(snaps[-1])
    df = PROVIDERS[index]()
    validate_snapshot(df)
    today = date.today().isoformat()
    df["snapshot_date"] = today
    df.to_csv(folder / f"{index}_{today}.csv", index=False)
    return df