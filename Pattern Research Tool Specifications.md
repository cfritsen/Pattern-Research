# Market Pattern Research Tool: Project Spec (v1)

Working title. Planned in a separate chat; this document is the full context for the build chat.

## 1. Purpose

A standalone program that mines historical price data for statistical patterns and reports what tended to happen after them, without the user choosing indicators in advance. It is a **research tool**. It does not produce trade signals, place trades, or give investment advice.

Origin: a previous MT5 trading bot (NexusMap) built around one preset strategy failed every backtest that wasn't overfitted. This tool discovers candidate patterns from data and is deliberately skeptical about them.

### Principles
1. **Skepticism over search.** Most discovered patterns are noise. The value of the tool is in the filtering (multiple-testing correction, out-of-sample confirmation, breadth checks), not in the size of the search.
2. **No look-ahead.** Every feature at bar *t* uses only data up to and including *t*. Every outcome uses only bars after *t*. This must be covered by tests.
3. **Outcomes are chosen before a run**, never after seeing results.
4. **Wording:** reports say "followed", never "caused". Rankings are labeled "strongest historical results", never "recommendations".
5. **Local, simple, no accounts, no servers, no LLM/API calls in the core pipeline.**

## 2. Platform and stack

- Runs on the owner's Windows 11 home PC; Mac support later is a bonus, so avoid Windows-only dependencies in the core.
- **Python** (current stable 3.x), in a virtual environment.
- Libraries (proposed): pandas + numpy, pyarrow (parquet cache), scipy + statsmodels (statistics), scikit-learn (decision trees/forests, later), sqlite3 (stdlib) for results.
- Data: **yfinance** (unofficial, may break) for daily prices, with **Stooq** CSVs as a fallback. Paid sources are out of scope for now (owner is not taking subscriptions).
- Output for v1: CSV and simple HTML reports. Desktop GUI later. Packaging to a Windows .exe later (e.g., PyInstaller).
- Settings live in a plain config file (YAML or JSON) that a future settings menu will edit.

## 3. Scope

### In v1
- S&P 500 universe, **hand-built top-10 list** (Section 4)
- **Daily bars** (swing timeframe), ~30 years (configurable)
- **Pooled analysis only** (patterns tested across all stocks together)
- Results stored so several horizons and both data views are available
- Top-N views as queries on the results (Section 9)

### Non-goals for v1
Trading signals or alerts, live trading or broker integration, options data, per-stock individual discovery, intraday data, other indices or asset classes, investor profiles, failed-stock tracking, fundamentals, GUI.

### Roadmap (later, roughly in this order)
1. Intraday bars (~2 years of history; free sources are limited, so finer bars may need a paid or broker source)
2. **Value-context module:** long horizons (3, 6, 12 months), price-only features such as drawdown from the 52-week high, distance below the 200-day average, and trend state. Question: is a falling stock a bargain or a trap? Price-only data shows "cheap vs. its own history", not intrinsic value; real valuation needs fundamentals data.
3. Investor profiles (long-only, long/short, options) that only change which findings are ranked first
4. Other indices (Nasdaq, Dow, Russell) and asset classes (forex majors, top 7 crypto, commodities) via new loaders. Notes: crypto history is only about a decade, forex has no real volume, commodities are futures with expiry/roll issues.
5. Swing data built from intraday bars (needs paid data)
6. Failed-stock tracking and reasons for failure (the reason is not in price data; needs paid data or manual curation)
7. Individual (per-stock) analysis
8. GUI with linked navigation between stock view and pattern view

## 4. Universe: hand-built top-10 list

The owner builds a short list (~30 to 40 tickers), not a year-by-year table:
- Start with the S&P 500 top 10 at the start of the window.
- For each following year, add only the top-10 names that aren't already on the list.

Columns in `universe_sp500_top10.csv`:

| Column | Meaning |
|---|---|
| ticker | Historical ticker |
| company | Company name |
| data_ticker | Ticker the data source uses (renames, mergers, successor tickers) |
| first_top10_year | First year-end the stock ranked top 10 |
| last_top10_year | Last year-end it ranked top 10 (approximation if it dropped out and returned) |
| share_class_note | Which class is used where two exist (e.g., Google, Berkshire) |
| data_status | ok / partial / missing (dead companies may lack free price data; flag them, never silently drop) |

The first draft of the list is compiled from year-end market-cap rankings or index fact sheets and must be checked against a source. Small ranking errors at the edge (rank 9 vs. 11) matter little.

### Membership flag (bias check)
Every stock on the list reached the top 10 at some point, so its rising phases are overrepresented. To measure this, every bar gets a boolean `in_top10`:
- Rankings are known at year-end, so a stock is flagged only from the year **after** it first ranks: years `first_top10_year + 1` through `last_top10_year + 1`.
- Every run reports **two views**: all bars, and flagged bars only. A pattern that only works on unflagged bars is suspect.
- Optional later: a small random control group of non-top-10 stocks.

## 5. Data pipeline

- Fetch daily OHLCV for every ticker in the universe, cache as parquet, and record the data version and fetch date.
- Use **split- and dividend-adjusted** prices for returns. Keep raw volume.
- Data quality report per ticker: date range, missing days, gaps, suspicious jumps, zero-volume bars.
- Index proxy (for relative strength features): S&P 500 index or SPY.
- Known limitation to flag in the reports: free data is survivor-biased; delisted names may be unavailable.

## 6. Features (v1)

All computed from past data only:

- Returns over 1, 3, 5, 10, 20 bars
- Distance from SMA 20/50/200, in ATR units
- RSI(14), MACD histogram
- ATR as % of price; range compression (recent N-day range relative to ATR)
- Gap % (open vs. prior close)
- Candle body and wick ratios; close location within the day's range
- Consecutive up/down days
- Volume relative to its 20-day average
- Day of week, month
- Relative strength vs. the index over 20 bars
- Distance from 52-week high and low; drawdown from high

Continuous features are split into quantile buckets. **Bucket boundaries are computed on the discovery period only** to avoid leaking information from the confirmation period.

## 7. Outcomes and default settings

The forward outcome is the return (and the move) over the next H bars. **Store forward returns for several horizons** (1, 5, 10, 20 bars, plus 63/126/252 for the later value module) so nothing has to be recomputed; v1 *tests* only the default horizon.

| Setting | Default | Notes |
|---|---|---|
| Outcome type | Direction (up and down both) | Magnitude, range (sideways), and volatility outcomes are opt-in later |
| Horizon | 5 daily bars | One horizon limits the number of tests |
| Move size | About 1 ATR, relative to each stock's own volatility | Not a fixed % |
| Success metric | Hit rate of that move vs. baseline hit rate, plus mean return vs. baseline mean | |
| Minimum occurrences | ~300 pooled | Below that, mostly luck |
| Minimum per stock | ~30 (for per-stock rankings) | |
| Breadth | Positive in ≥60% of stocks and ≥60% of years | Prevents one stock or era driving the result |
| Significance | 5% false discovery rate (Benjamini-Hochberg) plus a shuffled-data check | |
| Validation | Chronological split: discover on earliest ~70% of years, confirm on the latest ~30% | |
| Minimum edge | Must beat baseline by more than assumed costs (~0.1% round trip; configurable) | |
| Max conditions | 2 combined (1 to 2) | 3+ explodes the search space |
| Data view | Report both all bars and flagged bars | Section 4 |
| Regime filter (optional) | All / bull only / bear only / sideways only | Regime is a filter on *when* to test; the outcome is *what happens next* |

### Statistical cautions the code must handle
- **Overlapping forward windows** inflate sample size: use non-overlapping samples, block bootstrap, or an effective-sample-size correction.
- **Stocks move together** (mega-caps especially): assess significance with clustering by date, not treating every stock-day as independent.
- Correct across **all** tests run (every condition and outcome), not per condition.

## 8. Search and validation pipeline

1. Compute features and buckets (discovery period only for boundaries).
2. Enumerate 1-condition then 2-condition patterns.
3. For each pattern: occurrences, forward outcome vs. baseline, effect size, significance.
4. Apply minimum occurrences, breadth, multiple-testing correction, and minimum edge.
5. Confirm survivors on the held-out period.
6. Write results to the database; generate reports.

### Sanity checks (required before trusting any output)
- **Shuffle test:** run on shuffled or synthetic random-walk data; expect close to zero passing patterns at the chosen false discovery rate.
- **Look-ahead tests:** unit tests proving features and outcomes use only permitted bars.
- **Known-effects test:** at longer horizons, check whether the tool rediscovers effects documented in the literature (e.g., short-term reversal, multi-month momentum). Failure to find them suggests a bug or too little power; treat as a diagnostic, not proof.

## 9. Results storage

Local **SQLite** file. The owner is new to SQL, so the assistant writes and explains all database code. Proposed tables:

- `runs`: run_id, settings (JSON), created_at, data_version
- `stocks`: ticker, first_top10_year, last_top10_year, data_status, notes
- `patterns`: pattern_id, description, conditions (JSON), n_conditions
- `pattern_results_pooled`: pattern_id, run_id, view (all/flagged), horizon, outcome_type, split (discovery/confirm), n_occurrences, mean_fwd_return, baseline_mean, hit_rate, baseline_hit_rate, effect, p_value, q_value, breadth_stocks, breadth_years, passed
- `pattern_results_by_stock`: pattern_id, run_id, ticker, view, horizon, split, n, mean_fwd_return, hit_rate, effect

### Views (queries, not separate data)
- **Stock view:** best patterns for a given stock (top N, default 5)
- **Pattern view:** best stocks for a given pattern (top N, default 5)

Rules: only patterns that passed the pooled test are broken down; rank on the discovery period and **show the confirmation-period result alongside** (the top-ranked stock is partly the luckiest and will tend to regress); show sample counts; label output "strongest historical results". Both views make the linked-navigation idea (stock to patterns and pattern to stocks) a later UI task, not a data change.

### Example of a report row (illustrative numbers only)
> Condition: price above 200-day average, 3 consecutive down days, volume below 0.8x average. Outcome: next 5-day return. 4,210 occurrences across 34 stocks. Mean +0.9% vs. +0.3% baseline. Positive in 26 of 34 stocks and 24 of 30 years. Passes correction; holds in confirmation period.

Expect modest edges (small shifts in odds), and treat anything spectacular as a probable bug or noise.

## 10. Build order

| Milestone | Deliverable |
|---|---|
| M0 | Python environment on Windows 11 (Python, venv, editor), project folder, git |
| M1 | Universe CSV loader; price fetcher with parquet cache; data-quality report |
| M2 | Feature engine plus look-ahead unit tests |
| M3 | Outcome computation for stored horizons; baselines |
| M4 | Single-condition search, statistics, discovery/confirmation split; results to SQLite |
| M5 | Two-condition search; multiple-testing correction; shuffle test; overlap and clustering handling |
| M6 | Reports (CSV/HTML) and top-N stock and pattern views |
| M7 | Config file for all settings |
| M8 | (later) GUI, then intraday, then roadmap items |

**Definition of done for v1:** the tool runs end to end on the hand-built universe with default settings; the shuffle test passes; look-ahead tests pass; reports show both data views; results are reproducible from the stored run settings and data version.

## 11. Open items for the build chat

- Finalize the hand-built universe list and source-check it; find price data for dead or renamed tickers (or mark them missing)
- Choose the index proxy for relative-strength features
- Choose bucket definitions (quintiles vs. others) and the cost assumption
- Confirm whether the default horizon stays at 5 bars after seeing initial results
- Project name and folder location

## 12. Working notes for the assistant

- The owner prefers direct, efficient, actionable answers and honest, unvarnished assessments.
- Runs everything on a Windows 11 home PC; no paid subscriptions for now.
- New to databases and SQL; explain database code briefly and write it.
- Don't add scope beyond v1 without asking; put new ideas on the roadmap.
- Nothing here is financial advice; keep report wording descriptive.
