# scripts/check_join_dates.py
import pandas as pd
from patternlab.config import load_config
from patternlab.universe_fetch import get_universe

cfg = load_config()
uni = get_universe(cfg)
missing = uni[uni["date_added"].isna()]
print(f"{len(missing)} of {len(uni)} constituents have no join date on record:")
print(missing[["ticker", "company"]].to_string(index=False))
print("\nAAPL row:")
print(uni[uni["ticker"] == "AAPL"][["ticker", "company", "date_added"]].to_string(index=False))