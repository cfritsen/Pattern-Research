import sys
from pathlib import Path
from patternlab.config import load_config
from patternlab.fetch import get_prices

ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
cfg = load_config()
path = Path(cfg["data_dir"]) / "raw" / f"{ticker}.parquet"

before_mtime = path.stat().st_mtime if path.exists() else None
df_before, meta_before = get_prices(ticker, cfg)   # cache-as-is read, no fetch
print(f"Before: {meta_before['rows']} rows, {meta_before['first']} -> {meta_before['last']}, "
     f"fetched_at={meta_before['fetched_at']}, file mtime={before_mtime}")

df_after, meta_after = get_prices(ticker, cfg, refresh=True)
after_mtime = path.stat().st_mtime
print(f"After:  {meta_after['rows']} rows, {meta_after['first']} -> {meta_after['last']}, "
     f"fetched_at={meta_after['fetched_at']}, file mtime={after_mtime}")

print()
if meta_after["fetched_at"] is None:
    print("FAIL: refresh=True did not perform a real fetch (fetched_at is still None).")
elif before_mtime is not None and after_mtime <= before_mtime:
    print("FAIL: refresh=True ran but the cache file was never rewritten (mtime unchanged).")
elif meta_before["rows"] and abs(meta_after["rows"] - meta_before["rows"]) > 5:
    print(f"CHECK: row count changed by {meta_after['rows'] - meta_before['rows']} -- "
         f"expected for a near-identical refetch, investigate if this looks wrong.")
else:
    print("PASS: refresh=True performed a genuine re-fetch (new fetched_at, updated file, consistent row count).")