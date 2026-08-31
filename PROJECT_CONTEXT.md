# CWP Scanner — Project Context

## 1. Executive summary

CWP Scanner is a Python end-of-day equity scanner derived from the TradingView
indicator **Chan + Wyckoff + Price Action System V1.8.5**. It scans the current
S&P 500 and HS300 universes, reconstructs the indicator state from daily OHLCV,
classifies the latest bar, tracks candidates over time and sends changes to
Telegram.

The project was designed to run at zero or very low infrastructure cost using
GitHub Actions, free research-grade market-data sources, Parquet caches and
small CSV/JSON state files.

Current package version: `0.2.1`  
Engine identifier: `1.8.5-source-port`  
Python runtime: `3.11+`

## 2. Original goal and operating model

The practical goal is:

```text
After each market close
→ scan every current index constituent
→ identify CWP ENTRY / READY / WATCH structures
→ retain candidates for roughly 2–3 weeks
→ notify only useful state changes
→ retain enough history to audit and improve the model
```

The scanner reports model facts. It does not decide position size, check
earnings/news risk, assess liquidity, place orders or claim that an `ENTRY`
must be traded.

## 3. Authoritative strategy reference

The immutable source used for the Python port is:

```text
reference/CWP1.8.5.pine.txt
SHA-256: 3bca4cac5ec0d236aefd32c6bd6bf7ae6028041f17669feadb7302ad134eef2c
Pine language: version 6
Indicator name: Chan + Wyckoff + Price Action System V1.8.5
```

The Python port covers Pine sections 2–27. Pine sections 28–39 are helpers,
visual rendering, dashboard and alert declarations; they are not required to
calculate the scanner state.

The port was created from source because TradingView sample/state export was
not available. It has deterministic source-derived tests, but it has not been
proven against a TradingView per-bar numerical export.

## 4. High-level architecture

```text
GitHub Actions / local CLI
          |
          v
scanner/scanner.py
          |
          +--> data/data_us.py --> S&P 500 + adjusted US OHLCV
          |
          +--> data/data_cn.py --> HS300 + qfq China OHLCV
          |
          v
data/base.py --> canonical OHLCV + Parquet cache
          |
          v
engine/cwp_engine.py --> sequential V1.8.5 replay
          |
          v
scanner/result_builder.py --> ranked latest result CSVs
          |
          v
watchlist/watchlist_state.py --> cross-run lifecycle/change events
          |
          v
notification/notifier.py --> Telegram alerts and daily summary
```

Dependency direction is one-way. The engine does not know about networks,
files, Telegram, GitHub or watchlists.

## 5. Repository map

| Path | Responsibility |
|---|---|
| `reference/CWP1.8.5.pine.txt` | Immutable strategy reference |
| `engine/models.py` | Enums, market profile, persistent engine state, result schema |
| `engine/market_profiles.py` | Runtime profiles for HS300/S&P500 |
| `engine/cwp_engine.py` | ATR, sequential state machine, risk and trace |
| `data/base.py` | Canonical OHLCV, validation, long-format cache conversion |
| `data/data_us.py` | S&P constituents, yfinance retrieval and cache update |
| `data/data_cn.py` | HS300 constituents, AKShare retrieval and cache update |
| `scanner/scanner.py` | CLI and universe orchestration |
| `scanner/ranking.py` | Status/setup ordering |
| `scanner/result_builder.py` | Latest and current-alert CSV outputs |
| `watchlist/watchlist_state.py` | Change classification and 15-day lifecycle |
| `notification/notifier.py` | Messages, summaries and deduplication |
| `notification/telegram.py` | Telegram Bot API transport |
| `notification/email.py` | Optional SMTP transport, not in daily orchestration |
| `parity/` | Future TradingView/Python CSV comparison harness |
| `tests/` | Unit and source-derived lifecycle tests |
| `scripts/source_parity_smoke.py` | Dependency-light source-port regression check |
| `.github/workflows/` | Scheduled scans and PR parity tests |
| `cache/` | Constituents and combined long-format Parquet history |
| `state/` | Watchlist, signal history and sent-notification IDs |
| `output/` | Latest results, changes and Markdown summaries |

## 6. Engine execution model

### 6.1 Indicator references

The engine prepares only stateless reference series before replay:

- True Range;
- ATR14 using TradingView-compatible Wilder RMA seeding/recurrence;
- 100-bar simple average of ATR14;
- configured volume SMA.

Every state transition then runs one bar at a time. Prepared rows are converted
to in-memory records for performance without changing evaluation order.

Reference benchmark on 800 synthetic daily bars:

```text
approximately 0.09 seconds per symbol
approximately 45 seconds for 500 symbols of pure engine work
```

Network retrieval remains the expected bottleneck.

### 6.2 Market profile

Pine adjusts thresholds by market and current ATR regime.

| Parameter | China A-Shares | US Equities |
|---|---:|---:|
| Minimum bars between strokes | max(input, 5) | max(input, 4) |
| Minimum stroke move | 1.10 ATR | 0.90 ATR |
| Zhongshu tolerance | 0.25 ATR | 0.30 ATR |
| Spring/UTAD tolerance | 1.00 ATR | 1.00 ATR |
| Stop buffer | 0.25 ATR | 0.30 ATR |
| Climax range | 1.50 ATR | 1.50 ATR |
| Climax volume | 1.50 × SMA | 1.50 × SMA |
| Secondary-test tolerance | 0.60 ATR | 0.75 ATR |
| Volume confirmation | hard | hard |
| Gap sensitive | yes | yes |

Dynamic scale:

```text
ATR14 / SMA100(ATR14) > 1.30  -> 1.20
ATR14 / SMA100(ATR14) < 0.80  -> 0.85
otherwise                    -> 1.00
```

The scale applies to stroke ATR, Zhongshu tolerance, Spring tolerance, stop
buffer and secondary-test tolerance, matching Pine.

### 6.3 Chan strokes

Raw fractals:

```text
Top:    high[1] > high[2] and high[1] >= high
Bottom: low[1]  < low[2]  and low[1]  <= low
```

Stroke rules:

- the first confirmed fractal starts the array;
- a same-type fractal replaces the last endpoint only if more extreme;
- an opposite-type fractal requires minimum bar separation;
- it also requires the market/volatility-adjusted ATR move;
- stored strokes are capped at 30 by default.

Four alternating endpoints define `HH/HL` or `LH/LL` structure.

### 6.4 Zhongshu and regime

For the last four stroke endpoints, three segment ranges are formed:

```text
ZG = minimum of the three segment highs
ZD = maximum of the three segment lows
GG = maximum of the three segment highs
DD = minimum of the three segment lows
valid when ZG > ZD
```

An overlapping current zone extends the active Zhongshu. A disjoint valid zone
becomes a new identity, stores the previous boundaries and resets registered
breaks and Wyckoff state.

Chan regime uses:

- registered breaks;
- `HH/HL` or `LH/LL` stroke structure;
- rising/falling Zhongshu;
- close position between ZD and ZG.

It does not use moving-average trend proxies.

### 6.5 Micro structure and PA support

The default micro pivot uses two left and two right bars. A Bull Micro BOS
requires a close above the latest confirmed micro swing high on a bullish
candle. Bear Micro BOS is symmetrical.

The engine also traces liquidity sweeps and engulfing candles because they are
calculated by the Pine source, although V1.8.5 final-entry conditions do not
currently consume them.

### 6.6 Second Buy/Sell

Long sequence:

```text
Bear stroke structure
→ bullish break above latest stroke high = potential 1B
→ within 20 bars, confirmed micro pivot low remains above first-buy low
→ store the current micro swing high
→ close above that confirmation high with Bull Micro BOS
→ 2B ENTRY
```

The lifecycle invalidates below the first-buy low and expires after the
configured window. The short sequence is symmetrical.

### 6.7 Wyckoff inside Zhongshu

Wyckoff processing only occurs while the active Zhongshu has no registered
bull or bear break.

Accumulation sequence:

```text
SC-like near ZD
+ wide range
+ required volume participation
→ Accum Watch
→ secondary test near the climax within 20 bars
+ lower volume/effort
→ Accumulation
```

Distribution uses BC-like and the upper boundary symmetrically. The displayed
text becomes Re-Accumulation/Re-Distribution when the regime before the new
Zhongshu was already trending in that direction.

### 6.8 Spring and UTAD

Spring requires:

- active, unbroken Zhongshu context;
- completed Accumulation state;
- low below ZD but within the ATR tolerance;
- close back above ZD.

It then remains pending for 1–5 bars. Entry requires:

- no lower low below the Spring extreme;
- close above the Spring candle high;
- Bull Micro BOS on the confirmation bar.

UTAD is symmetrical and disabled for China A-Shares.

### 6.9 Zhongshu break, direct entry and Third Point

A fresh break requires a close outside ZG/ZD plus ATR tolerance, or a
meaningful gap followed by a close outside the boundary. Each direction is
registered once per Zhongshu identity.

Direct BRK entry additionally requires same-bar Micro BOS. The same fresh break
also opens a 12-bar Third Buy/Sell retest window. Third Buy requires a retest of
ZG within tolerance, a close back above ZG and Bull Micro BOS. Third Sell is
symmetrical around ZD.

### 6.10 Final entry and risk

Entry priority is Spring/UTAD, then Second Point, then Third Point, then direct
break. Risk is created only on final entry, never merely because a setup is
`READY`.

| Setup | Structural stop anchor | Structural TP1 possibility |
|---|---|---|
| Spring | Spring low | opposite Zhongshu boundary |
| UTAD | UTAD high | opposite Zhongshu boundary |
| 2B | first valid pullback low | no; fallback R multiple |
| 2S | first valid rally high | no; fallback R multiple |
| 3B | breakout-retest low | no; fallback R multiple |
| 3S | breakdown-retest high | no; fallback R multiple |
| BRK Long | lower of current low and former ZG | no |
| BRK Short | higher of current high and former ZD | no |

The ATR buffer is applied outside the structural anchor. Default TP1 fallback
is 2R and TP2 is 3R. Active risk tracks TP1, SL, TP2 and a maximum display
lifecycle, mirroring the source indicator state.

## 7. Scanner output model

`ScanResult` is the stable engine-to-scanner contract.

Important fields:

| Field | Meaning |
|---|---|
| `status` | `ENTRY`, `READY`, `WATCH`, `NONE` |
| `setup` | `SPR`, `UTAD`, `2B`, `2S`, `3B`, `3S`, `BRK`, `BRK_SHORT`, `NONE` |
| `direction` | `LONG`, `SHORT` or empty |
| `regime` | Pine-derived Chan regime text |
| `wyckoff` | Pine-derived Wyckoff state text |
| `trigger` | current Micro BOS or `Waiting` |
| `zs_zd`, `zs_zg` | active Zhongshu boundaries |
| `entry_price`, `sl`, `tp1`, `tp2` | populated on current final entry when risk is valid |
| `engine_version` | `1.8.5-source-port` |

Ranking order is status first, then setup priority, then symbol.

## 8. Data layer

### 8.1 US / S&P 500

- constituents: Wikipedia S&P 500 table;
- refresh interval: seven days based on cache file modification time;
- symbol conversion: `BRK.B -> BRK-B`;
- OHLCV: `yfinance.download`, daily, threaded, 100-symbol batches;
- price adjustment: `auto_adjust=True`;
- update: download from ten days before the latest cached date and merge.

This is appropriate for personal research, not a guaranteed commercial feed.

### 8.2 China / HS300

- constituents: AKShare CSI index constituent endpoint for `000300`;
- refresh interval: seven days;
- symbols normalised to six digits;
- OHLCV: AKShare `stock_zh_a_hist`;
- price adjustment: `qfq`;
- update: one symbol at a time with a small request pause;
- failures preserve existing cache when available and are surfaced later by
  scanner validation/logging.

### 8.3 Cache design

Two combined Parquet files are used instead of hundreds of binary files:

```text
cache/sp500_daily.parquet
cache/hs300_daily.parquet
```

Long schema:

```text
date, symbol, open, high, low, close, volume
```

This reduces Git file-count churn. Git still stores binary history inefficiently,
so repository growth must be monitored.

## 9. Batch scanner flow

`run_scan()` performs:

1. load scanner settings;
2. choose the market adapter;
3. load/refresh constituents;
4. update or load the market cache;
5. validate each symbol independently;
6. replay V1.8.5 and collect `ScanResult`;
7. rank and save the latest/current files;
8. compare against the previous market watchlist;
9. save changes and updated watchlist;
10. append material state changes to signal history;
11. generate a Markdown summary;
12. optionally send immediate alerts and the summary.

One symbol failure is logged and does not abort the entire universe.

## 10. Watchlist lifecycle

Statuses are ranked:

```text
ENTRY = 3
READY = 2
WATCH = 1
NONE  = 0
```

Tracked fields include first seen, days tracked, previous/current status,
highest status rank and last seen. Default tracking is 15 runs/trading days.
Plain `WATCH` names are removed after that period; stronger states can remain.

Change types include:

```text
NEW_ENTRY
READY_TO_ENTRY
WATCH_TO_ENTRY
NEW_READY
WATCH_TO_READY
NEW_WATCH
DROPPED
UNCHANGED
```

## 11. Notification behavior

Immediate Telegram messages are limited to:

- new `ENTRY`;
- transitions to `ENTRY`;
- new `READY`;
- `WATCH -> READY`.

`DROPPED` is included in the daily summary. New `WATCH` names are not pushed
individually. The first run for a market sends only a summary so initial state
does not generate hundreds of false “new” messages.

Deduplication key:

```text
market + symbol + signal_date + setup + current_status
```

Required Telegram environment variables:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

The SMTP adapter exists for a later phase but is disabled in current scanner
orchestration.

## 12. GitHub Actions

### HS300

```text
.github/workflows/scan_hs300.yml
cron: 30 8 * * 1-5 UTC
commented intent: 16:30 China Standard Time
timeout: 30 minutes
```

### S&P 500

```text
.github/workflows/scan_sp500.yml
cron: 30 22 * * 1-5 UTC
intent: after the US regular close with data buffer
timeout: 30 minutes
```

The US cron intentionally trades exact local-time alignment for a fixed UTC
time that remains after the close across daylight-saving changes.

Both scan workflows:

- checkout full history;
- install project plus dev dependencies;
- run `pytest -q`;
- run the selected scan with Telegram enabled;
- upload `output/` and `logs/` for 14 days;
- commit `cache/`, `output/` and `state/` back to the repository.

The parity workflow runs on relevant pull requests and manual dispatch with
read-only repository permission. It runs CSV parity only when the fixture is
populated.

## 13. Output and persistent state

Committed/reusable:

```text
cache/*_daily.parquet
cache/constituents/*.csv
output/latest/*.csv
output/alerts/*_current.csv
output/alerts/*_changes.csv
output/reports/*_summary.md
state/watchlist.csv
state/signal_history.csv
state/notifications.json
```

Workflow artifacts:

```text
output/
logs/
```

Artifacts are for run inspection. Repository state is what the next scan uses.

## 14. Parity strategy

### Available now

- source-to-function mapping in `docs/PORTING_NOTES.md`;
- per-bar internal trace through `scan_history()`;
- deterministic tests for Wilder ATR, strokes, Zhongshu, Wyckoff, Spring,
  Second Buy, Third Buy and structural risk;
- `scripts/source_parity_smoke.py` for fast verification;
- generic CSV field comparator in `parity/compare_outputs.py`.

### If TradingView export becomes available

Use exactly the same:

- ticker;
- exchange;
- daily date range;
- session/timezone;
- adjustment policy;
- V1.8.5 inputs;
- trade direction.

Compare in this order:

1. ATR and confirmed fractals;
2. stroke type/price/bar arrays;
3. active ZD/ZG and new-Zhongshu events;
4. regime and break registration;
5. Wyckoff state/events;
6. pending lifecycles;
7. Micro BOS;
8. final setup/direction;
9. entry, SL, TP1 and TP2.

Do not debug final entries first; upstream state divergence compounds.

## 15. Validation record

At the V1.8.5 source-port handoff:

- Python compile check passed;
- smoke test passed;
- source-parity smoke test passed;
- 19 source-derived and engineering test functions passed;
- ZIP integrity check passed;
- 800-bar single-symbol engine benchmark was approximately 0.09 seconds.

The original execution environment did not expose a `pytest` command, so test
functions were also invoked directly. GitHub workflows install and run real
`pytest`.

## 16. Known issues and design debts

### High priority

1. No TradingView per-bar export has confirmed exact numerical parity.
2. `config/markets.yml` contains `long_only`, but runtime market direction is
   currently sourced from `engine/market_profiles.py`; the YAML value is not
   wired into `scanner.py`.
3. Free market-data endpoints may throttle, change schema or produce partial
   histories.
4. Git history can grow because full combined Parquet binaries are committed
   after updates.

### Medium priority

1. Add explicit exchange trading-calendar freshness checks rather than only
   validating bar count and order.
2. Add retries/backoff and structured failure reporting for both adapters.
3. Add end-to-end scanner tests with local Parquet fixtures.
4. Add explicit bootstrap/run metadata: source timestamp, constituent count,
   success count, failure count and newest market date.
5. Decide whether production S&P scanning should be `Both` or `Long Only` and
   connect the setting end to end.
6. Review simultaneous GitHub manual runs and commit/rebase conflict handling.

### Lower priority

1. Wire optional email summaries if there is a real need.
2. Add signal forward-return analytics only after data consistency is stable.
3. Consider SQLite for signal analytics; do not move raw daily OHLCV there
   prematurely.

## 17. Recommended next work sequence

```text
1. Push the repository and run both workflows manually without notifications
2. Inspect data freshness, symbol success rates and output schemas
3. Run Telegram dry-run / private test chat
4. Operate for 2–3 weeks and review false-positive volume
5. Obtain any possible TradingView trace evidence for 10–20 symbols
6. Resolve pivot/data parity differences before changing strategy rules
7. Only then tune WATCH/READY notification thresholds
```

## 18. Commands for a new Codex session

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m compileall -q .
python scripts/smoke_test.py
python scripts/source_parity_smoke.py
pytest -q

python -m scanner.scanner --market hs300 --bars 800
python -m scanner.scanner --market sp500 --bars 800
python -m scanner.scanner --market sp500 --no-download
python -m scanner.scanner --market sp500 --notify --dry-run-notifications
```

## 19. Handoff decision log

| Decision | Reason |
|---|---|
| One shared engine for both markets | Avoid duplicated strategy logic and simplify parity |
| Market differences in `MarketProfile` | Keep data adapters free of trading rules |
| Full sequential replay each day | Stroke/Zhongshu/pending states depend on history |
| Incremental download plus full local replay | Network is expensive; 800-bar CPU replay is cheap |
| Combined Parquet per market | Avoid hundreds of changing binary files |
| CSV/JSON for watchlist and signal state | Human-readable and adequate at current scale |
| Telegram first, email optional | Immediate and low-friction personal notifications |
| Notify changes, not full universes | Prevent alert fatigue |
| First run summary only | Prevent bootstrap notification flood |
| Separate HS300 and S&P summaries | Different close times and review contexts |
| Commit reusable state; artifact debug output | Next run needs state, but logs need not be permanent |
| `V1.8.5 source port`, not “100% parity” | TradingView per-bar export is unavailable |
