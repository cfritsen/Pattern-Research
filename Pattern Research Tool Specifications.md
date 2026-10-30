# Market Pattern Research Tool: Project Spec (v1.3)

Working title. v1.3 folds in the multi-index work (S&P 500, 400 and 600, each with its own data) and a rewritten roadmap; see the changelog at the end for what moved since v1.2. **As of this version, M0-M8 (the entire v1 pipeline plus the desktop GUI and aesthetic pass) are complete.** Everything below "v1 scope" is now post-v1 roadmap work — see Section 3 and Section 13.

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
- S&P 500 universe, **fetched automatically** from the current constituent list (Section 4). Post-v1, S&P 400 Mid Cap and S&P 600 Small Cap loaders were added, each with its own data folders (Section 13).
- **Daily bars** (swing timeframe), ~30 years (configurable)
- **Pooled analysis only** (patterns tested across all stocks together)
- Results stored so several horizons and both data views are available
- Top-N views as queries on the results (Section 9)

### Non-goals for v1
Trading signals or alerts, live trading or broker integration, options data, per-stock individual discovery, intraday data, other indices or asset classes, investor profiles, failed-stock tracking, fundamentals, GUI, cross-asset/lead-lag features (see Roadmap).

### Roadmap (post-v1)

**No committed order.** The app is fully functional, so features are now taken in whatever order makes sense rather than from a fixed queue. A candidate next step is to **compile/package the current version** (Windows .exe; see Section 2).

**Frontloaded (do soon):**
- **Horizon-following labels.** The hard-coded "5-day" labels in `index.html` and `humanize.py` should follow the `horizon` setting.
- **Per-index cost settings.** One flat cost (default ~0.1% round trip) currently applies to every index. Cost should be a per-index setting, since small caps (S&P 600) trade with wider spreads than large caps.

**Gated on EODHD (nothing in this group can start before the EODHD integration exists):**
- **EODHD API integration (the gate for everything in this group).** Deliberately scoped as its own step *before* Intraday work, not bundled into it — EODHD's value (full daily EOD history including dividends/splits) isn't exclusive to intraday use, so build it as a standalone data-provider module first. Provider chosen over Massive/Polygon.io (both gate multi-user/hosted redistribution behind enterprise pricing; EODHD has a similar restriction but was still judged the better overall option). Real confirmed pricing: a $29.99/mo "EOD + Intraday" tier with 30 years of history (an earlier $99.99/mo figure from a reference plugin's table was wrong). A stdlib-only Python REST client script seen in that same reference repo may be a useful starting point for the fetch module. **Postponed:** no subscription for now.
- **Intraday bars**, now that a provider is chosen. Design already settled: poll/recompute once per bar boundary (e.g. every 5 min), not continuous tick streaming — cheaper feed and compute, and there's no interest in 1-2 minute granularity (5 min is the practical floor). The live-scan feature this enables (see item 3 under "Not yet ordered") reads already-validated bucket edges and only has to compute "distance to threshold" per stock/feature at each refresh — cheap; the real cost is the live data feed itself, not the math.
- **Dividends as a stock-attribute filter** (e.g. dividend yield) — architecturally a new "stock list" screening view, not a pattern condition; **Prerequisite: EODHD integration.** (yfinance `Ticker.dividends` was the originally considered source.)
- **Earnings as a pattern condition** (e.g. days since/until earnings) — a new event-anchored feature type, not price-derived. Best data source found: the third-party `stocks-earnings-dates` package (SEC EDGAR 8-K Item 2.02-based, ~21yr history, S&P 500 + top 100 Nasdaq) — notably more reliable than yfinance's own earnings calendar, which has known gaps. Needs the same spot-check validation diligence as every other data source, plus care that "days until next earnings" is only used if it reflects what was actually publicly announced at time *t* (a look-ahead risk otherwise). **Prerequisite: EODHD integration** (possibly its higher ~$100/mo tier — unconfirmed).
- **Comprehensive ETF loader and Mutual-Fund loader.** **Prerequisite: EODHD** (a full ETF list ranked by AUM; the mutual-fund loader possibly, since it needs an even narrower start: multiple share classes, thinner AUM data, NAV-based daily pricing, and it won't support intraday regardless). Also flagged: a larger future universe (2000+ names) will be slower even with multithreading and bucket controls already built — not a solved problem yet.
- Swing data built from intraday bars (needs paid data)

**Free-data work, no committed order:**
- **Confirmation/exit-timing search mode.** Deliberately deferred until the GUI was finished (it now is) rather than built right after M7 where it was first slotted. Uses `exit_day_mask` (already built as a research script) run through the full search pipeline as an alternative to entry-day occurrence counting — lets a pattern's stats optionally be based on "pattern just stopped being true" instead of "pattern is true." A spot-check on discovery data (10 top patterns) found exit-day effects unanimously lower than entry-day effects — plausible if reversal-style patterns give up much of the move before confirmation, but not treated as a validated finding, just the motivation for building this.
- **Curated ETF loader (no EODHD needed).** A starter universe of 75 funds is saved in `data/universe/etf_candidates_2026-10-29.csv` (raw probe output: `etf_probe_2026-10-29.csv`, produced by `scripts/etf_probe.py`). Built from 156 hand-picked large, liquid, plain-vanilla ETFs (no leveraged or inverse funds) and filtered to AUM of at least $2B, average volume of at least 1M shares, at least 10 years of history, one fund per underlying exposure, and no cash-like funds. Findings from the probe: Yahoo returned AUM, category and price history for all 156, but it has no way to list ETFs, and Vanguard's `totalAssets` counts all share classes, so AUM is not comparable across fund families and is best used as a floor, not a ranking. ETFs have no join dates, so Index-Only would equal All Data. Not yet built as a loader; judged too many new variables to be the second loader (the S&P 400 took that role).
- **Cross-asset lead-lag patterns** (e.g. an ETF reacting to its top-holding stock's price, or sector-peer pairs). Requires: a point-in-time holdings/relationship file (curated and source-checked, similar in spirit to the old hand-built universe list); new cross-referenced lagged features (stock B's data as an input to stock A's row); dedicated look-ahead tests, since cross-referencing two securities' update timing is a new leak risk; and a wider multiple-testing budget, since every pair tested multiplies the search space right as it's already strained by 2-condition patterns.
- **Run/save/revisit/export reports** feature for the GUI (also a prerequisite for ever distributing the app: users need exportable results; `scripts/m6_reports.py` is retained as the starting point, or it can be replaced) (supersedes an earlier "Open Folder" buttons idea for `data_dir`/`report_dir`, which was deliberately removed from Settings in favor of this).
- **Configurable indicator periods** (MA, RSI, MACD, ATR, etc. — 9 settings covering 16 of the original 23 features; the later-added indicators have fixed windows). Always requires the full long/weekly reprocessing chain (M2-M5), never nightly, since changing a period redefines the feature across all history. Flagged as a likely paid-tier candidate (exponentially increasing processing time if multiple parameter sets get tested per indicator) — see Section 13's packaging notes. **Prerequisite for the multi-parameter optimizer. On the chopping block** together with the optimizer (kept for now).
- **Multi-parameter-set "optimizer" feature** (MT5 Strategy Tester optimizer analogy: run several indicator presets at once with per-run progress and a streaming results table). This is the identified trigger for finally moving the GUI from vanilla JS to React — genuine multi-component state, unlike a single progress bar. **Requires configurable indicator periods. The processing time is so large that this and configurable periods are both on the chopping block (kept for now).**
- **Restricted 3-condition search mode**: first two conditions must be continuous (non-calendar) features, third must be `month`. Reduces the combination space from the full C(23,3) (~1771 triples — why unrestricted 3-condition was ruled impractical) down to the already-bounded continuous-pair set x 2 calendar options. Bucket-combination cost and a third joint-FDR-correction tier still apply, and minimum-occurrence attrition would likely be severe. Motivated by a day-of-week/month on/off diagnostic run during GUI work (day of week has since been removed from the tool), which showed how much of the passed-pattern set is calendar-driven — this mode would answer "which specific continuous-pair+calendar combos are strong" directly instead of inferring it from toggle comparisons. **On the chopping block (kept for now).**
- Failed-stock tracking and reasons for failure (the reason isn't in price data; needs paid data or manual curation)
- Investor profiles (long-only, long/short, options) that only change which findings are ranked first
- **Value-context module:** long horizons (3, 6, 12 months), price-only features such as drawdown from the 52-week high, distance below the 200-day average, and trend state. Question: is a falling stock a bargain or a trap? Price-only data shows "cheap vs. its own history", not intrinsic value; real valuation needs fundamentals data.

**Done since v1 (for reference):** S&P 400 Mid Cap and S&P 600 Small Cap loaders; per-index data folders and per-index discovery/confirm split; multithreading for M4/M5; day of week removed from the feature set; VIX card and Day/Month/Year index cards in Market Insights; "Market Pattern" link from Stock Research to a single-pattern view in Market Research; sidebar index labels; the indicator-redundancy sandbox (`scripts/indicator_sandbox.py`) and the eight indicators added from its results.

**Explicitly NOT on this roadmap:** a crash-similarity analysis (comparing current feature vectors to historical crash windows like 2000/2008/COVID) was considered and deliberately filed as a *separate* possible future project, not part of this tool.

**Also dropped:** Nasdaq-100 and Dow Jones index loaders. Both consist almost entirely of S&P 500 stocks, so they would add no new data, and the Dow's 30 stocks is too few for the current occurrence and breadth thresholds. The Russell loader was dropped too: the Russell 1000 largely covers the S&P 500 and 400, the Russell 2000 is expected to contain most of the S&P 600, and what is left is roughly 1,400 of the least liquid, most survivorship-biased names (and it would need EODHD for constituents). Overlap with the S&P indices was never measured.

## 4. Universe: auto-fetched current index constituents

**Changed from v1.** The original plan was a hand-built, source-checked top-10-by-year list. That gave the cleanest bias picture but required ongoing manual curation and couldn't update itself. The owner wants the tool to run unattended and sees automatic updating as a base for a possible future paid product, so v1.1 fetches the **current constituent list** of the selected index instead.

- Source: the index's public constituent table (S&P 500, S&P MidCap 400 and S&P SmallCap 600 via Wikipedia's lists). No account or key required.
- Fetched once per index and cached as a dated snapshot (`data/universe/<index>_<date>.csv`); a run uses the latest snapshot unless refreshed, so results stay reproducible from a stored snapshot.
- `index` is a config setting with a small provider registry, so another index — or a future paid, point-in-time constituents provider — can be added without changing the pipeline. This is the natural slot for a paid tier if the tool becomes a product; a licensed data source would also be needed before selling results commercially (the owner should check data licensing and how results are described before any sale — not legal advice).
- Each row carries the stock's official index-join date where the source provides one. The S&P 500 table has one; the S&P 400 and 600 tables do not, so every stock there counts as a long-standing member and the Index-Only view equals All Data (Pre-Index Bias reads 0%).
- Each index owns its own data: `data/<index>/raw`, `features` and `outcomes`, plus `results_<index>.db` and a manifest. A refresh or rebuild on one index never touches another's. A ticker a later stage cannot find data for (for example a symbol Yahoo does not carry) is skipped and reported, not fatal.

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

- Fetch daily OHLCV for every ticker in the universe snapshot, cache as parquet (`data/<index>/raw/`), and record the data version and fetch date.
- Use **split- and dividend-adjusted** prices for returns (`adj_open/high/low/close`), computed from yfinance's raw vs. adjusted close ratio. Keep raw volume.
- Data quality report per ticker: date range, missing days, gaps, suspicious jumps, zero-volume bars, nonpositive prices, high-below-low bars (`m1_fetch.py` → `reports/data_quality.csv`).
- Index proxy (for relative strength features): one per index — SPY (S&P 500), MDY (S&P 400), IJR (S&P 600).
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
- Month (categorical, not quantile-bucketed). Day of week was originally included and later removed entirely (it added noise in insignificant areas).
- Relative strength vs. the index over 20 bars
- Distance from 52-week high and from 52-week low (drawdown from high is this same quantity, not a separate feature)
- **Added after the redundancy-sandbox study (Section 13):** `adx_14` (trend strength, 0-100), `vol_ratio_5_20` (ATR(5)/ATR(20)), `vol_state_1y` (current ATR% vs the stock's own trailing-year average), `mom_12_1` (return from 12 months ago to 1 month ago), `days_since_52w_low`, `cmf_20` (Chaikin money flow), and two **market-level** features, `mkt_dist_sma200` (index proxy vs its 200-day average) and `vix_pct_252` (VIX percentile over the trailing year). The market-level ones have the same value for every stock on a given date (Section 13).
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
| Validation | Chronological split: discovery on the earliest ~70% of years (by date, rounded to a calendar year boundary; computed per index from the first and last price dates across that index's own tickers), confirm on the rest | An observation whose outcome window would reach past the cutoff is excluded from discovery ("purged"), not just its start date checked, so no confirmation-period return leaks into a discovery-period statistic |
| Minimum edge | Must beat baseline by more than assumed costs (~0.1% round trip; configurable, per-index setting planned — Section 3) | |
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
- **Shuffle test:** run on shuffled or synthetic random-walk data; expect close to zero passing patterns at the chosen false discovery rate. (Does not catch universe-level survivorship bias — see Section 4.) **Status: never built as a full-pipeline test.** The narrower check that exists is `tests/test_stats.py`, which runs the cluster bootstrap on pure noise over 60 seeds and requires a false-positive rate below 15% at the 5% level (the measured rate was about 4%).
- **Look-ahead tests:** unit tests proving features and outcomes use only permitted bars, including a deliberately-leaky feature planted in the test suite to prove the detector actually fails when it should.
- **Known-effects test:** at longer horizons, check whether the tool rediscovers effects documented in the literature (e.g., short-term reversal, multi-month momentum). The M4 run's top results (reversal firing across several correlated features) are an early version of this signal — a genuine sign the pipeline is finding a real, known effect, not proof the pipeline is bug-free. Failure to find such effects suggests a bug or too little power; treat as a diagnostic, not proof.

## 9. Results storage

One local **SQLite** file per index (`data/results_<index>.db`). The owner is new to SQL; the assistant writes and explains all database code. Tables:

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
| M5 | Two-condition search; breadth and cost filters applied as pass/fail; per-stock results table and views | Done — 723 passed on the real run; year-breakdown spot-checks on the top 15 confirmed a genuine recurring seasonal effect, with one pattern correctly flagged and traced to crash-recovery-year concentration rather than a clean calendar effect |
| M6 | Reports (CSV/HTML) and top-N stock and pattern views, with the two-baseline and survivorship-bias disclosures built in | Done — extensive build-out beyond the original spec; see Section 13 |
| M7 | Config file for all settings | Done — consolidated `config.yaml` with inline comments, a validated `cost` setting, and full `validate_config` (horizon/discovery_frac/corr_prune_threshold/cost/jump_threshold/pause_seconds/booleans/index/start_overrides) |
| M8 | Desktop GUI (pywebview + Flask + vanilla JS), then the full aesthetic pass | **Done.** See Section 13 for what got built. Post-M8 roadmap work (Section 3) is now the active front. |

**Definition of done for v1:** the tool runs end to end on the auto-fetched universe with default settings; the cluster-bootstrap false-positive-rate test and the look-ahead tests pass (a full-pipeline shuffle test was never built — Section 11); reports show both data views, both baselines, and the survivorship-bias and collinearity disclosures; results are reproducible from the stored run settings, data version, and universe snapshot.

## 11. Open items

- Bucket definitions: quintiles confirmed as the v1 default.
- Cost assumption: ~0.1% round-trip confirmed as the v1 default (configurable).
- Index proxy: one per index (SPY, MDY, IJR) for relative-strength features.
- Full-pipeline shuffle test (Section 8): never built. Optional, since the bootstrap calibration is covered by a unit test.
- "Cases Found" in the reports is the occurrence count *before* thinning (`MIN_OCCURRENCES` is also checked before thinning); the sample the statistics actually use is smaller. Not yet changed or relabeled.
- Whether the confirm-period result should be independently significance-tested (currently: no, it's reported alongside the discovery-period pass/fail — see Section 8, step 5).
- Whether/how to de-duplicate correlated single-condition patterns before they compound into 2-condition patterns in M5 (see Section 7 caveat) — not resolved; M5 ran anyway via the Spearman correlation + bucket-pair overlap pruning described in Section 13, labeled "overlapping conditions" in reports rather than suppressed.
- ~~Project name and folder location~~ **Resolved:** `F:\Development\Pattern-Research` on the owner's Windows PC ("chris-gaming-pc"), git-tracked, package name `patternlab`.
- Data licensing/compliance for any future commercial/hosted version is still unexamined (not legal advice territory the assistant should resolve) — flagged again here since EODHD integration (Section 3, item 1) makes this more concrete than it was in v1.
- Paywall/tier boundaries for a future product are deliberately left undefined for now — see Section 13's packaging notes for the reasoning already settled (hosted vs. app-tier split) without formally drawing the lines.

## 12. Working notes for the assistant

- The owner prefers direct, efficient, actionable answers and honest, unvarnished assessments.
- Runs everything on a Windows 11 home PC; no paid subscriptions for now.
- New to databases and SQL; explain database code briefly and write it.
- Don't add scope beyond v1 without asking; put new ideas on the roadmap.
- Nothing here is financial advice; keep report wording descriptive.
- **Implementation note for the eventual finished product (not yet built):** the feature engine (M2) will need to be re-run every time the program is opened, since the price cache can pick up a new trading day between sessions and feature files must stay in sync with it. During current milestone-by-milestone development this is just re-run manually as needed.
- The owner sees potential to sell this as a product later; a paid, point-in-time data source is the natural upgrade path (Section 4), and licensing/compliance for a commercial version should be checked separately — this spec and the assistant's guidance are not legal advice.

## 13. M5-M8 as actually built (detail beyond the build-order table)

### M5/M6: search and reports build-out
- **Collinearity handled, not solved**, per the Section 7 caveat: a cheap Spearman feature-feature correlation matrix prunes near-duplicate feature pairs before 2-condition testing; surviving pairs also get a per-bucket-pair overlap check (all 25 bucket combinations, not just matching numbers). Labeled "overlapping conditions" in reports, deliberately not "redundant" (that would overstate confidence that it's *the same* effect).
- A bug was found and fixed in this phase: `thin_non_overlapping` was comparing occurrence *rank* instead of actual trading-bar distance; fixed via a new `bar_pos` column. M4 rerun after the fix: 104/512 passed 5% FDR (up from 96).
- M6 reports ended up far beyond the original spec: dual All/Index-Only Data columns, Pre-Index Bias %, vs. Best Single Condition comparison, Conditions Overlap %, a Year Concentration flag (top-year share of occurrences/effect — catches patterns that look like a clean calendar effect but are actually concentrated in a few crash-recovery years), a direction-agreement filter (drops patterns whose confirm-period result flipped sign from discovery, judged only on views the pattern actually passed), and a "Weakest historical results" section (found zero qualifying negative patterns on this dataset — consistent with negative/contrarian effects tending to fail the breadth filter — made fully silent when empty).
- Per-stock breakdown switched to full history (not the 70/30 split) since confirm-period samples were too thin per stock; two related bugs found via AMD (joined S&P 500 2017) and fixed: thin-sample rows were being dropped entirely instead of keeping the count and nulling only the unreliable stats, and a pattern with zero flagged-view occurrences showed "--" instead of the correct 100% Pre-Index Bias.
- Lead-lag results (once item 3's cross-asset work exists) are specced to live in their own report/section, not merged into the main pattern table, to avoid flooding it with near-duplicate rows.

### M1 redesign (incremental fetch)
The original "nightly processing is cheap" assumption was never actually implemented — M1 was all-or-nothing (use cache as-is, or `--refresh` redownloads a ticker's entire history). Split into two real modes: **Update Price Data** (cheap, incremental, append-only — reads the cached file's last date and fetches only newer bars; a no-op if nothing's new) vs. **Full Rediscovery** (purges and fully refetches from scratch). This bounds the adjusted-price retroactive-rescaling drift risk (a new dividend/split between fetches isn't reflected in old cached `adj_close` until the next full refetch) to at most one Full Rediscovery interval. Confirmed this won't directly reuse for Intraday later — same incremental principle, but a different data source/timestamp granularity needs its own implementation.

### M8: GUI architecture
- **Stack:** pywebview (chrome-less native window via the OS's built-in WebView2/WebKit, not Electron) wrapping a local Flask server (`scripts/gui_server.py`) and a single-file vanilla-JS frontend (`web/static/index.html`). React deferred until the multi-parameter-set optimizer (Section 3) actually needs real multi-component state. `pattern_view`/`build_pattern_context`/`stock_view` logic lives in shared `src/patternlab/reports.py` so the CLI and GUI use identical logic.
- **Background jobs:** `src/patternlab/jobs.py` runs job chains (Update Price Data = M1+M2, Full Rediscovery = M1-M6) as sequential subprocesses in a background thread, with per-stage logs in `data/logs/`. A per-index `discovery_log_<index>.json` tracks last Full Rediscovery completion + a config hash, driving a dashboard staleness banner (30+ days or a settings change since last run). A parallel `price_update_log_<index>.json` tracks the last time M1 actually fetched (via either button, since both run M1) — both timestamps now show together on the dashboard, Price Data Update first, same order as the buttons.
- **Multi-index unification:** one sidebar selector (not a split Settings-target / view-filter) drives both what's displayed on every page and what Update Price Data/Full Rediscovery process when triggered, via a shared `currentIndex` global and a `POST /api/set-index` endpoint. Settings and Market Research no longer have their own index controls. `discovery_status()` already handles index-switching correctly (compares each index's current hash against *that same index's* last-recorded hash) with no new suppression logic needed. The dropdown shows a friendly label (`INDEX_LABELS` map: "S&P 500 Large Cap", "S&P 400 Mid Cap", "S&P 600 Small Cap"; key order is the display order) while the underlying value stays the raw provider key used in every `?index=` fetch.
- **Watchlist:** eligible patterns = any passed pattern regardless of All/Index-only view; a live match = both conditions true at the most recently closed bar (not intraday-live yet, sets precedent for when it is). Never framed as a buy recommendation. Architecture decision made to support two *future* views (per-stock search; click-a-pattern-to-see-matching-stocks) without rework: the matching computation returns FLAT `(ticker, pattern_id, return, badge-info)` rows, not pre-grouped-by-ticker — the watchlist page groups/filters client-side, and the future views are just different filters on the same flat dataset. Deep-links from a watchlist card to Market Research auto-toggle the All/Index-only view on mismatch rather than showing blank.
- **Date Insights page** (what historically happened most in month X) built as its own page — one of the four items in "GUI finished" (Section 3 note below).
- **Dashboard Market Insights:** anchored to the most recently completed trading session rather than live-refreshing, to preserve the tool's research/daily-bar identity — not a live quote feed. Implemented via `_session_in_progress()` (America/New_York timezone-aware, 4pm ET close cutoff); a known, accepted gap is early-close days (e.g. day after Thanksgiving), which get misjudged as still-in-progress until 4pm. A related, separate, pre-existing quirk (adjustment-backfill lag for 3 of 4 index-insight tickers, compounding with an explicit design decision to sync all four cards to the earliest common date) can make the reported date look up to a couple of days behind; accepted as-is for end users, diagnosed case-by-case when it recurs (direct parquet inspection, not guessing).
- **Aesthetic pass** (deliberately last): "Ledger & Brass" palette (dark ink + brass/copper accent), chosen over two alternatives via an interactive mockup; every Return/Edge value colored green/red by sign across every table and card; navbar restructured (reserved index-selector space, groupings, Settings pinned to the bottom); "Pattern Stocks" renamed to "Stocks by Pattern" in every display label (internal `pattern-stocks` route/hash untouched); a scrollbar-drift bug traced to CSS padding/height values that could silently diverge, fixed by tying them to one shared custom property instead of just patching the symptom.
- **"GUI finished" was formally defined as four things, all now done:** (1) the pywebview wrapper, (2) watchlist deep-links to Market Research, (3) the Date Insights page, (4) the full aesthetic pass.

### Multi-index build-out (post-M8)
- **Separate data per index, by decision.** Sharing price files between indices was considered and rejected. Full Rediscovery purges and refetches a ticker's whole history so that retroactive split/dividend adjustments leave the data whole; reusing a ticker another index fetched would need a "last full refresh" stamp separate from "last bar date", a reuse window, and a data-version check between indices. The saving (a few minutes of fetching per new index, against a Stage 5 that dominates run time) did not justify that, and sharing also left relative strength, the latest-feature snapshot and the market-mean file overwritable by whichever index ran last. Each index now has `data/<index>/raw`, `features`, `outcomes`, its own snapshot and market-mean files, plus `results_<index>.db`; a test (`tests/test_index_isolation.py`) checks that two indices can never resolve to the same folders.
- **Per-index discovery/confirm split.** The boundary was originally pinned to SPY's date range so shared outcome files would agree across indices. With separate data it is computed per index from the earliest and latest price date across that index's own tickers (rounded to a calendar year, as before). For the S&P 500 this gives the same 2018-01-01 cutoff, so existing results stayed valid.
- **Loaders:** `sp400` (proxy MDY, 380-420 constituents accepted) and `sp600` (proxy IJR, 570-630 accepted), both parsed from Wikipedia's constituents tables by one shared function. Each index has its own acceptable constituent-count range, because the S&P 500 range would have rejected the 400.
- **Failed tickers:** the first S&P 600 run crashed in M4 because one listed symbol (CWEN-A) has no data on Yahoo, and the search assumed every universe ticker had feature files. The panel loader now skips and reports tickers with no feature or outcome data.
- **Why these indices:** the S&P 500, 400 and 600 are a non-overlapping split of the US market by size, built from the same source. Nasdaq-100 and the Dow were dropped for overlap with the S&P 500. A forex loader was discussed and judged a different kind of project (about 7 independent currencies behind the pairs, no volume data, spread-based costs, an ambiguous daily close, no carry in price bars, and no meaning for index-based features) rather than a test of the multi-index setup.

### Indicator study and feature additions (post-M8)
- **Sandbox:** `scripts/indicator_sandbox.py` (shared code in `src/patternlab/redundancy.py` and `candidates.py`) measures overlap using rank correlation and R-squared against the other features, from already-cached data. It scores candidates against existing features, and has trim modes (backward elimination, re-scoring after every removal): existing features only, candidates only, and a combined run (`--trim --include ... --exclude ...`). It measures overlap only, not whether an indicator predicts anything.
- **Existing-set trim:** rsi14, dist_sma20_atr, body_ratio, dist_sma200_atr and ret_1 were each 0.88-0.99 explained by the others. Disabling the five (Settings feature toggles / `disabled_features`) and rerunning discovery changed almost nothing: one reorder in the watchlist's top 20 and the same top patterns. Body ratio and the two wick ratios sum to exactly 1, so one of the three is redundant by construction. The combined run with the new indicators also flagged `ret_20` (0.87).
- **Added (8):** `adx_14`, `vol_ratio_5_20`, `vol_state_1y`, `mom_12_1`, `days_since_52w_low`, `cmf_20`, `mkt_dist_sma200`, `vix_pct_252` (definitions in `src/patternlab/indicators.py`; the VIX series is refreshed or read from cache by M2). Stochastic %K, Bollinger %B and bandwidth, the cross-sectional return rank and days-since-52-week-high were rejected as redundant (0.64-0.96 explained by existing features).
- **Market-level features and the date-matched baseline:** significance is tested on each occurrence's return minus the same-day market mean. A condition on a market-level feature (or `month`) selects the whole market on those dates, so its excess return is ~0 by construction. Consequences, implemented: market-level features are not tested alone in M4, and M5 skips any pair in which both features are date-level (`buckets.DATE_LEVEL`: `month`, `mkt_dist_sma200`, `vix_pct_252`). The useful case is a market-level feature paired with a stock-level one (a stock-level pattern within a regime). The Effect column is still calculated against the raw baseline, so such a condition would show a large Effect but cannot pass the significance test; breadth across stocks is meaningless for it, breadth across years is the real check.
- **Cost:** more features means more pairs. With extreme buckets only (the default), M5 tests 4 bucket combinations per continuous pair.

### Product/packaging notes (not yet formally drawn into pricing tiers)
- Full pipeline reruns are wanted limited to the first run only, with later runs incrementally adding new data — realized for M1 via Update Price Data/Full Rediscovery above; M2-M5 still require a full rerun when settings change (configurable indicator periods, in particular, always require this — see Section 3).
- Envisioned split if this becomes a product: **free hosted** = curated presets on the owner's schedule (like a free tier of a charting platform — not user-triggered); **paid hosted** = more presets / faster refresh, still owner-scheduled, not user-driven; a **one-time-fee desktop app tier** is where true user-driven flexibility (arbitrary horizons, custom indicator params) belongs, since the user's own hardware/schedule is already the limiting factor there, not shared server cost. Compute-heavy candidates (horizon flexibility, multi-parameter indicator testing, finer intraday granularity, true arbitrary hosted tuning) are flagged as they come up; no formal paywall lines drawn yet, since current work is core functionality regardless of eventual packaging.
- A "live pattern scan" (apply already-validated patterns to today's feature values, report historical-alignment matches with stats, never framed as predictions) is expected to be one of the most-used features even though the research/discovery side is the most valuable part — pairs naturally with a future scheduled nightly reprocessing + cached display model for a hosted/subscription version.

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

## Changelog from v1.1 to v1.2

- **Title/intro**: marked M0-M8 complete — the entire v1 pipeline plus the desktop GUI and aesthetic pass are done; everything past that is now post-v1 roadmap.
- **Section 3 (Roadmap)**: fully rewritten. Split into a committed near-term order (EODHD integration -> Intraday -> confirmation/exit-timing search mode -> indicator-redundancy sandbox) and a larger "filed, no committed order" list (dividends, earnings, cross-asset lead-lag, other index loaders, ETF/mutual-fund loaders, configurable indicator periods, the multi-parameter optimizer, multithreading, a restricted 3-condition search mode, run/save/export reports, and the original value-context/investor-profiles/failed-stock-tracking items). Added the explicit note that a crash-similarity analysis was considered and filed as a separate project, not this roadmap.
- **Section 10**: M5-M8 all marked Done with brief outcome notes; M8 points to the new Section 13 for detail.
- **Section 11**: resolved the project-folder-location open item (`F:\Development\Pattern-Research`); added two new open items surfaced by the EODHD/roadmap work (data licensing for a commercial version, and undrawn paywall tier boundaries).
- **New Section 13** added: what M5-M8 actually built beyond the original spec (collinearity handling, report feature build-out, the M1 Fetch-New/Full-Rediscovery redesign, the full GUI architecture — stack, background jobs, multi-index unification, watchlist, Date Insights, Market Insights session-awareness, the aesthetic pass — and the as-discussed-but-undrawn product/packaging notes).

## Changelog from v1.2 to v1.3

- **Section 3 (Roadmap)**: rewritten. The committed order was dropped; the roadmap is now unordered, with a frontloaded pair (horizon-following labels, per-index cost settings), an EODHD-gated group (EODHD, Intraday, Dividends, Earnings, comprehensive ETF loader, mutual-fund loader, intraday swing data), and a free-data group. Compiling the current version is a candidate next step. Configurable indicator periods, the multi-parameter optimizer and the restricted 3-condition mode are on the chopping block. Multithreading moved to done; Nasdaq-100, Dow and Russell loaders were dropped.
- **Sections 4, 5, 7, 9**: per-index data folders, results databases and proxies (SPY, MDY, IJR); per-index discovery/confirm split; S&P 400/600 tables have no join dates.
- **Sections 8, 10, 11**: the shuffle test is recorded as never built (with the narrower bootstrap test that exists); "Cases Found" counting pre-thinning occurrences added as an open item.
- **Sections 6, 13**: indicator study (sandbox, trims, eight added indicators incl. two market-level features) and the date-level skip rule for M4/M5.
- **Section 13**: new multi-index build-out subsection; sidebar labels updated; Date Insights is month-only now that day of week is gone.
