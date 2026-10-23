# scripts/verify_refresh_start_date.py
import sys
from patternlab.config import load_config
import patternlab.fetch as fetch_module

ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
cfg = load_config()

real_fetch_from = fetch_module._fetch_from
captured = {}

def spy(ticker, start, use_stooq):
    captured["start"] = start
    return real_fetch_from(ticker, start, use_stooq)

fetch_module._fetch_from = spy

df, meta = fetch_module.get_prices(ticker, cfg, refresh=True)

print(f"Start date actually used: {captured.get('start')}")
print(f"cfg['start_date']:        {cfg['start_date']}")
print()
if captured.get("start") == cfg["start_date"]:
    print("PASS: refresh=True fetched from the true configured start date (full history).")
else:
    print(f"FAIL: refresh=True used {captured.get('start')!r} instead of {cfg['start_date']!r} "
         f"-- it is NOT doing a true full refetch.")