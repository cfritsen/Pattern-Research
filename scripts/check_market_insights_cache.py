# scripts/check_market_insights_cache.py
import pandas as pd
from patternlab.config import load_config

cfg = load_config()
for ticker in ("SPY", "DIA", "QQQ", "IWM"):
    path = f"{cfg['data_dir']}/raw/{ticker}.parquet"
    try:
        df = pd.read_parquet(path)
        print(f"{ticker}: {len(df)} rows, {df.index[0].date()} -> {df.index[-1].date()}")
        print(df[['adj_close']].tail(3))
    except FileNotFoundError:
        print(f"{ticker}: NO CACHE FILE EXISTS at {path}")
    print()