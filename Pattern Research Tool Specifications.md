# Market Pattern Research Tool: Project Spec (v1.1)

Working title. v1.1 folds in decisions made during the build; see the changelog at the end for what moved since v1.

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
- Libraries: pandas + numpy, pyarrow (parquet cache), scipy + statsmodels (statistics), scikit-learn (decision trees/forests, later), sqlite3 (stdlib) for results, requests + lxml (universe fetch).
- Data: **yfinance** (unofficial, may break) for daily prices, with **Stooq** CSVs as a fallback. Paid sources are out of scope for now (owner is not taking subscriptions).
- Output for v1: CSV and simple HTML reports. Desktop GUI later. Packaging to a Windows .exe later (e.g., PyInstaller).
- Settings live in `config.yaml`, edited by hand for now; a future settings menu will edit it.

## 3. Scope

### In v1
- S&P 500 universe, **fetched automatically** from the current constituent list (Section 4)
- **Daily bars** (swing timeframe), ~30 years (configurable)
- **Pooled analysis only** (patterns tested across all stocks together)
- Results stored so several horizons and both data views are available
- Top-N views as queries on the results (Section 9)

### Non-goals for v1
Trading signals or alerts, live trading or broker integration, options data, per-stock individual discovery, intraday data, other indices or asset classes, investor profiles, failed-stock tracking, fundamentals, GUI, cross-asset/lead-lag features (see Roadmap).

### Roadmap (later, roughly in this order)
1. Intraday bars (~2 years of history; free sources are limited, so finer bars may need a paid or broker source)
2. **Value-context module:** long horizons (3, 6, 12 months), price-only features such as drawdown from the 52-week high, distance below the 200-day average, and trend state. Question: is a falling stock a bargain or a trap? Price-only data shows "cheap vs. its own history", not intrinsic value; real valuation needs fundamentals data.
3. Investor profiles (long-only, long/short, options) that only change which findings are ranked first
4. **Cross-asset lead-lag patterns** (e.g. an ETF reacting to its top-holding stock's price, or sector-peer pairs). Requires: a point-in-time holdings/relationship file (curated and source-checked, similar in spirit to the old hand-built universe list); new cross-referenced lagged features (stock B's data as an input to stock A's row); dedicated look-ahead tests, since cross-referencing two securities' update timing is a new leak risk; and a wider multiple-testing budget, since every pair tested multiplies the search space right as it's already strained by 2-condition patterns.
5. Other indices (Nasdaq, Dow, Russell) and asset classes (forex majors, top 7 crypto, commodities) via new loaders. Notes: crypto history is only about a decade, forex has no real volume, commodities are futures with expiry/roll issues.
6. Swing data built from intraday bars (needs paid data)
7. Failed-stock tracking and reasons for failure (the reason is not in price data; needs paid data or manual curation)
8. Individual (per-stock) analysis
9. GUI with linked navigation between stock view and pattern view

## 4. Universe: auto-fetched current index constituents

**Changed from v1.** The original plan was a hand-built, source-checked top-10-by-year list. That gave the cleanest bias picture but required ongoing manual curation and couldn't update itself. The owner wants the tool to run unattended and sees automatic updating as a base for a possible future paid product, so v1.1 fetches the **current constituent list** of the selected index instead.

- Source: the index's public constituent table (S&P 500 via Wikipedia's list for now). No account or key required.
- Fetched once per index and cached as a dated snapshot (`data/universe/<index>_<date>.csv`); a run uses the latest snapshot unless refreshed, so results stay reproducible from a stored snapshot.
- `index` is a config setting with a small provider registry, so another index — or a future paid, point-in-time constituents provider — can be added without changing the pipeline. This is the natural slot for a paid tier if the tool becomes a product; a licensed data source would also be needed before selling results commercially (the owner should check data licensing and how results are described before any sale — not legal advice).
- Each row carries the stock's official index-join date where the source provides one.

### Membership flag (bias check): `in_index`
Renamed from the original `in_top10`, and computed differently:
- A bar is flagged `in_index = True` from the stock's official index-join date onward. A missing join date is treated as long-standing membership.
- Every run reports **two views**: all bars, and flagged bars only. A pattern that only works on unflagged bars is suspect.

### Known limitation: survivorship bias (accepted tradeoff)
A **current** constituent list contains only companies that succeeded enough to still be in the index; it has no delisted, merged, or long-dropped names. This is a stronger bias than the original hand-built-list design and is not fully caught by the `in_index` flag:
- Bars *before* a stock's join date are the most contaminated (the stock was added because it had already risen). Bars after are less contaminated but not clean, since stocks that were later removed for underperforming aren't in the data at all.
- Dip-buying and mean-reversion-style patterns will tend to look better than they actually were, because stocks that dipped and never recovered are absent.
- The shuffle test (Section 8) does not catch this — it tests the statistics, not which stocks were selected.
- Every report must carry a standing survivorship-bias warning, not just the two-view breakdown.
- Baseline returns are also inflated by this (see Section 7).

## 5. Data pipeline

- Fetch daily OHLCV for every ticker in the universe snapshot, cache as parquet (`data/raw/`), and record the data version and fetch date.
- Use **split- and dividend-adjusted** prices for returns (`adj_open/high/low/close`), computed from yfinance's raw vs. adjusted close ratio. Keep raw volume.
- Data quality report per ticker: date range, missing days, gaps, suspicious jumps, zero-volume bars, nonpositive prices, high-below-low bars (`m1_fetch.py` → `reports/data_quality.csv`).
- Index proxy (for relative strength features): SPY.
- Known limitation to flag in reports: free data is survivor-biased at the universe level (Section 4); delisted names are absent entirely, not just missing data for existing names.

### Cleaning rules (added; not in original v1)
Applied on top of the raw cache, non-destructively (the raw parquet is untouched; cleaning happens on read):
1. **Drop any bar dated today or later.** A same-day fetch can include an incomplete session; only fully closed bars are used.
2. **Trim leading prehistory with mostly-zero volume.** If 50% or more of a rolling 60-bar window has zero volume, that stretch is trimmed from the start of the series. This was found to catch cases where a ticker's Yahoo history includes a foreign listing or predecessor entity's prehistory before its real US-listed trading began (confirmed for SW, FERG, AMCR; CRH's zero-volume bars were checked and found to be ordinary thin ADR trading, not a wrong listing, and were left in place beyond the trim). The threshold was tuned up from an initial 20%, which incorrectly trimmed genuinely thin-trading 1990s small caps (MNST, ODFL, TTWO).
3. **Manual start-date overrides** (`config.yaml: start_overrides`) for known-bad prehistory the automated rule can't catch structurally — e.g. JCI, whose pre-2007-07-02 history is inherited from Tyco pre-spinoff and isn't comparable to JCI's own trading.
4. **Standing limitation:** Yahoo keys history by ticker, so a renamed or reused ticker can carry another entity's price history. The volume-based check only catches the cases where that shows up as a zero-volume gap; a same-volume-profile substitution wouldn't be caught. Noted as a report-level limitation alongside survivorship bias.

## 6. Features (v1)

All computed from past data only, verified by look-ahead tests (Section 8):

- Returns over 1, 3, 5, 10, 20 bars
- Distance from SMA 20/50/200, in ATR units
- RSI(14), MACD histogram (as % of price)
- ATR as % of price; range compression (10-day high-low range relative to ATR)
- Gap % (open vs. prior close)
- Candle body and wick ratios; close location within the day's range (zero-range bars treated as missing, not divide-by-zero)
- Consecutive up/down days (signed streak length)
- Volume relative to its trailing 20-day average, computed from the 20 bars *before* the current bar so a volume spike doesn't dilute its own ratio; zero-volume bars are treated as missing, not zero, so nothing divides by zero
- Day of week, month (categorical, not quantile-bucketed)
- Relative strength vs. the index over 20 bars
- Distance from 52-week high and from 52-week low (drawdown from high is this same quantity, not a separate feature)
- `tradable` flag (volume > 0) carried alongside features, used downstream to exclude non-trading bars from pattern occurrences

Continuous features are split into quantile buckets (quintiles by default). **Bucket boundaries are computed on the discovery period only** to avoid leaking information from the confirmation period; values in the confirmation period are assigned using those same discovery-period edges, with out-of-range values falling into the outermost bucket rather than creating a new one.

## 7. Outcomes and default settings

The forward outcome is the return (and the move) over the next H bars, from the close at bar *t*. **Forward returns are stored for several horizons** (1, 5, 10, 20, plus 63/126/252 for the later value module) so nothing has to be recomputed; v1 *tests* only the default horizon.

| Setting | Default | Notes |
|---|---|---|
| Outcome type | Direction (up and down both) | Magnitude, range (sideways), and volatility outcomes are opt-in later |
| Horizon | 5 daily bars | One horizon limits the number of tests |
| Move size | About 1 ATR, relative to each stock's own volatility (`atr_pct` at *t*) | Not a fixed % |
| Success metric | Hit rate of that move vs. baseline hit rate, plus mean return vs. baseline mean | |
| Minimum occurrences | ~300 pooled | Below that, mostly luck |
| Minimum per stock | ~30 (for per-stock rankings) | |
| Breadth | Positive in ≥60% of stocks and ≥60% of years | Computed at pattern-discovery time; used as a pass/fail filter starting in M5, alongside the FDR filter |
| Significance | 5% false discovery rate (Benjamini-Hochberg), applied across all single-condition tests run in a pass; date-clustered (block-bootstrap) p-values, not per-row | Reapplied across the combined pool once 2-condition patterns are added, per the "correct across all tests" rule below |
| Validation | Chronological split: discovery on the earliest ~70% of years (by date, rounded to a calendar year boundary), confirm on the rest | An observation whose outcome window would reach past the cutoff is excluded from discovery ("purged"), not just its start date checked, so no confirmation-period return leaks into a discovery-period statistic |
| Minimum edge | Must beat baseline by more than assumed costs (~0.1% round trip; configurable) | |
| Max conditions | **2 combined (1 to 2), confirmed as a hard v1 limit** | 3+ conditions explodes the search space combinatorially, thins occurrence counts below the minimum, and is the same overfitting failure mode that sank NexusMap. A 3+-condition search, if wanted later, is its own roadmap milestone with its own occurrence and correction budget — not a flag on the existing 2-condition search. |
| Data view | Report both `all` bars and `flagged` (in_index) bars | Section 4 |
| Baseline | **Two baselines are stored**: (a) the raw baseline — mean/hit-rate over all bars in the same view and split; (b) a **date-matched baseline** — the same-day mean across the universe, for the same view and split | Added beyond the original spec. With a ~500-stock pooled universe, a pattern that simply fires more often in rising markets would look like an edge against the raw baseline alone; the date-matched baseline lets that be checked. Reports show both. |
| Regime filter (optional) | All / bull only / bear only / sideways only | Regime is a filter on *when* to test; the outcome is *what happens next* |

### Statistical cautions the code must handle
- **Overlapping forward windows** inflate sample size: occurrences are thinned per stock so no two kept occurrences fall within one horizon-window of each other (a non-overlapping-ish sample), rather than using a block bootstrap or effective-sample-size correction directly.
- **Stocks move together** (mega-caps especially): significance is assessed with a cluster (block) bootstrap grouped by calendar date, not by treating every stock-day as independent.
- Multiple-testing correction is applied across **all** tests run in a pass (every condition and view), not per condition.

### Known interpretation caveat (found during the build, not yet fixed in code)
Several single-feature v1 patterns that pass the FDR filter are highly correlated with each other — e.g. `ret_1`, `ret_3`, `ret_5`, `ret_10`, `rsi14`, `macd_hist_pct`, `dist_sma20_atr`, and `dist_52w_high` all firing on "the stock has recently fallen" and all showing a similar reversal effect. BH correction treats these as independent hypotheses, which is statistically correct per-test, but it means a headline count like "96 patterns passed" can overstate how many *distinct* effects were found — it may be closer to one effect (short-term reversal) counted several times. This matters more once 2-condition patterns combine two correlated single-condition winners, which will look like a stronger discovery while adding little new information. No code change has been made for this yet; it's a flag for how M5 results are reported and possibly de-duplicated by correlation before ranking.

## 8. Search and validation pipeline

1. Compute features and buckets (discovery period only for boundaries).
2. Enumerate 1-condition then 2-condition patterns.
3. For each pattern: occurrences, forward outcome vs. both baselines, effect size, cluster-bootstrap significance, breadth.
4. Apply minimum occurrences, breadth, multiple-testing correction, and minimum edge.
5. Confirm survivors on the held-out period. (v1.1: the confirm-period row is not independently re-tested for significance; a pattern's pass/fail is set by its discovery-period result and the confirm-period row is reported alongside it, per Section 9's original intent. This can be changed to an independent confirm-period gate if wanted.)
6. Write results to the database; generate reports.

### Sanity checks (required before trusting any output)
- **Shuffle test:** run on shuffled or synthetic random-walk data; expect close to zero passing patterns at the chosen false discovery rate. (Does not catch universe-level survivorship bias — see Section 4.)
- **Look-ahead tests:** unit tests proving features and outcomes use only permitted bars, including a deliberately-leaky feature planted in the test suite to prove the detector actually fails when it should.
- **Known-effects test:** at longer horizons, check whether the tool rediscovers effects documented in the literature (e.g., short-term reversal, multi-month momentum). The M4 run's top results (reversal firing across several correlated features) are an early version of this signal — a genuine sign the pipeline is finding a real, known effect, not proof the pipeline is bug-free. Failure to find such effects suggests a bug or too little power; treat as a diagnostic, not proof.

## 9. Results storage

Local **SQLite** file (`data/results.db`). The owner is new to SQL; the assistant writes and explains all database code. Tables:

- `runs`: run_id, settings (JSON), created_at, data_version, universe_snapshot
- `patterns`: pattern_id, description, conditions (JSON, unique), n_conditions
- `pattern_results_pooled`: pattern_id, run_id, view (all/flagged), horizon, outcome_type, split (discovery/confirm), n_occurrences, mean_fwd_return, baseline_mean, hit_rate, baseline_hit_rate, effect, p_value, q_value, ci_low, ci_high, breadth_stocks, breadth_years, passed
- `pattern_results_by_stock` (M5): pattern_id, run_id, ticker, view, horizon, split, n, mean_fwd_return, hit_rate, effect

### Views (queries, not separate data)
- **Stock view:** best patterns for a given stock (top N, default 5)
- **Pattern view:** best stocks for a given pattern (top N, default 5)

Rules: only patterns that passed the pooled test are broken down; rank on the discovery period and **show the confirmation-period result alongside** (the top-ranked stock is partly the luckiest and will tend to regress); show sample counts; label output "strongest historical results". Both views make linked navigation (stock ↔ pattern) a later UI task, not a data change.

### Example of a report row (illustrative numbers only)
> Condition: price above 200-day average, 3 consecutive down days, volume below 0.8x average. Outcome: next 5-day return. 4,210 occurrences across 34 stocks. Mean +0.9% vs. +0.3% baseline. Positive in 26 of 34 stocks and 24 of 30 years. Passes correction; holds in confirmation period.

Expect modest edges (small shifts in odds) as the norm; treat anything spectacular as a probable bug or noise — and, per Section 7's added caveat, treat a cluster of *different* features all showing the same "spectacular" result as likely one effect, not several.

## 10. Build order

| Milestone | Deliverable | Status |
|---|---|---|
| M0 | Python environment on Windows 11 (Python, venv, editor), project folder, git | Done |
| M1 | Universe auto-fetch (Section 4); price fetcher with parquet cache; cleaning rules (Section 5); data-quality report | Done |
| M2 | Feature engine (Section 6) plus look-ahead unit tests | Done |
| M3 | Outcome computation for stored horizons; discovery/confirm split with purging; both baselines | Done |
| M4 | Single-condition search, statistics (thinning, cluster bootstrap, BH correction), breadth computed; results to SQLite | Done — 96 of 512 tested combinations passed 5% FDR on the first real run; see the collinearity caveat in Section 7 |
| M5 | Two-condition search; breadth and cost filters applied as pass/fail; shuffle test; per-stock results table and views | In progress |
| M6 | Reports (CSV/HTML) and top-N stock and pattern views, with the two-baseline and survivorship-bias disclosures built in | Not started |
| M7 | Config file for all settings | Partially done (config.yaml exists and grows with each milestone; a settings menu is not built) |
| M8 | (later) GUI, then intraday, then roadmap items | Not started |

**Definition of done for v1:** the tool runs end to end on the auto-fetched universe with default settings; the shuffle test passes; look-ahead tests pass; reports show both data views, both baselines, and the survivorship-bias and collinearity disclosures; results are reproducible from the stored run settings, data version, and universe snapshot.

## 11. Open items

- Bucket definitions: quintiles confirmed as the v1 default.
- Cost assumption: ~0.1% round-trip confirmed as the v1 default (configurable).
- Index proxy: SPY confirmed for relative-strength features.
- Whether the confirm-period result should be independently significance-tested (currently: no, it's reported alongside the discovery-period pass/fail — see Section 8, step 5).
- Whether/how to de-duplicate correlated single-condition patterns before they compound into 2-condition patterns in M5 (see Section 7 caveat).
- Project name and folder location (currently `Pattern-Research` / `patternlab` package name — either can still change).

## 12. Working notes for the assistant

- The owner prefers direct, efficient, actionable answers and honest, unvarnished assessments.
- Runs everything on a Windows 11 home PC; no paid subscriptions for now.
- New to databases and SQL; explain database code briefly and write it.
- Don't add scope beyond v1 without asking; put new ideas on the roadmap.
- Nothing here is financial advice; keep report wording descriptive.
- **Implementation note for the eventual finished product (not yet built):** the feature engine (M2) will need to be re-run every time the program is opened, since the price cache can pick up a new trading day between sessions and feature files must stay in sync with it. During current milestone-by-milestone development this is just re-run manually as needed.
- The owner sees potential to sell this as a product later; a paid, point-in-time data source is the natural upgrade path (Section 4), and licensing/compliance for a commercial version should be checked separately — this spec and the assistant's guidance are not legal advice.

## Changelog from v1

- **Section 4** replaced: hand-built top-10 list → auto-fetched current index constituents. Bias flag renamed `in_top10` → `in_index`, computed from index-join date instead of year-end rank. Survivorship bias is now a known, accepted, and stronger tradeoff (explicitly documented as such) in exchange for zero manual curation and automatic updates, and as a possible seed for a future paid tier.
- **Section 5** gained explicit cleaning rules: drop same-day incomplete bars; trim mostly-zero-volume prehistory (>=50% zero-volume in a trailing 60-bar window); manual per-ticker start-date overrides; a standing limitation noted about ticker reuse/renames.
- **Section 6**: no functional change; documented that `tradable` and zero-handling are part of the spec now, not just implementation detail.
- **Section 7**: added the date-matched baseline alongside the raw baseline; confirmed max-conditions=2 as unchanged; added the collinearity interpretation caveat found in the first real M4 run.
- **Section 8**: noted that the look-ahead test suite includes a deliberately-leaky planted test, and that confirm-period results aren't independently gated (open item).
- **Section 9**: no structural change; `pattern_results_by_stock` deferred to M5 as planned.
- **Roadmap**: added a new item, cross-asset lead-lag patterns (ETF-to-holding, sector pairs), between the original items 3 and 4.
- **Section 10**: build order updated with current status (M0–M4 done, M5 in progress).
- **Section 12**: added the m2_features-rerun-on-launch implementation note, and the paid-product/licensing note.
