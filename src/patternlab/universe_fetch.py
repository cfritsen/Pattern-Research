from __future__ import annotations
import io
from datetime import date
from pathlib import Path
import pandas as pd
import requests
from patternlab.universe import load_snapshot

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_SP400 = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
WIKI_SP600 = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
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


def _fetch_wiki_no_join_dates(url: str) -> pd.DataFrame:
    """S&P MidCap 400 / SmallCap 600 from Wikipedia. Their constituents tables have
    NO date-added column, so date_added is left empty and every stock counts as a
    long-standing member (see universe.in_index_flag) -- the Index-Only view
    equals All Data."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    need = ["Symbol", "Security", "GICS Sector"]
    table = next((t for t in tables if all(c in t.columns for c in need)), None)
    if table is None:
        raise RuntimeError("Constituents table not found; the page layout may have changed")
    df = pd.DataFrame({
        "ticker": table["Symbol"].astype(str).str.strip(),
        "company": table["Security"].astype(str).str.strip(),
        "sector": table["GICS Sector"].astype(str).str.strip(),
        "date_added": pd.NaT,
    })
    df["data_ticker"] = df["ticker"].map(to_data_ticker)
    return df


def fetch_sp400() -> pd.DataFrame:
    return _fetch_wiki_no_join_dates(WIKI_SP400)


def fetch_sp600() -> pd.DataFrame:
    return _fetch_wiki_no_join_dates(WIKI_SP600)


PROVIDERS = {"sp500": fetch_sp500, "sp400": fetch_sp400, "sp600": fetch_sp600}   # add other indices or a paid provider here

# Acceptable constituent count per index; a count outside this range means the
# source page changed or was scraped wrong. Indices not listed use (450, 520).
EXPECTED_COUNTS = {"sp500": (450, 520), "sp400": (380, 420), "sp600": (570, 630)}

# The benchmark ticker used per index for relative-strength features (M2).
# Add an entry here whenever a new index loader is added to PROVIDERS.
INDEX_PROXIES = {
    "sp500": "SPY",
    "sp400": "MDY",         # SPDR S&P MidCap 400 ETF (history back to 1995)
    "sp600": "IJR",         # iShares Core S&P Small-Cap ETF (history back to 2000)
}

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
    validate_snapshot(df, *EXPECTED_COUNTS.get(index, (450, 520)))
    today = date.today().isoformat()
    df["snapshot_date"] = today
    df.to_csv(folder / f"{index}_{today}.csv", index=False)
    return df