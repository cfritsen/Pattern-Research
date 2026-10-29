# scripts/time_watchlist.py
import time
from patternlab.config import load_config
from patternlab.universe_fetch import get_universe
from patternlab.db import connect
from patternlab.reports import build_pattern_context
from patternlab.watchlist import get_snapshot, bucket_snapshot, load_edges, compute_watchlist

cfg = load_config()
uni = get_universe(cfg)
conn = connect(cfg)

t0 = time.time()
context = build_pattern_context(conn)
t1 = time.time()
print(f"build_pattern_context: {t1 - t0:.2f}s ({len(context)} patterns)")

snapshot = get_snapshot(cfg, uni)
t2 = time.time()
print(f"get_snapshot: {t2 - t1:.2f}s ({len(snapshot)} tickers)")

edges = load_edges(conn)
bucketed = bucket_snapshot(snapshot, edges)
t3 = time.time()
print(f"bucket_snapshot: {t3 - t2:.2f}s")

matches = compute_watchlist(cfg, uni, conn)
t4 = time.time()
print(f"compute_watchlist total: {t4 - t3:.2f}s ({len(matches)} matches)")