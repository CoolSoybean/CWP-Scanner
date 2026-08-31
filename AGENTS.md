# AGENTS.md

This file governs all work in this repository. It is written for Codex and
other coding agents that will maintain CWP Scanner without access to the
original design conversation.

## 1. Read before changing code

Before making a material change, read these files in order:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `README.md`
4. `docs/PORTING_NOTES.md`
5. the files directly affected by the task

For any strategy-engine change, also read:

- `reference/CWP1.8.5.pine.txt`
- `engine/cwp_engine.py`
- `engine/models.py`
- `engine/market_profiles.py`
- `tests/test_engine.py`
- `tests/test_source_state_machine.py`

Do not infer the strategy from names such as `Spring`, `2B`, `3B` or `BRK`.
Their authoritative definitions are the Pine source and the source-mapping
notes.

## 2. Repository mission

CWP Scanner is a daily, end-of-day scanner for:

- the current S&P 500 universe;
- the current CSI 300 / HS300 universe.

It downloads adjusted daily OHLCV, replays the CWP V1.8.5 state machine for
each symbol, classifies the latest state as `ENTRY`, `READY`, `WATCH` or
`NONE`, tracks changes for approximately 2–3 weeks, writes CSV/Markdown
outputs and sends concise Telegram alerts.

This is a research scanner. It is not an execution engine, broker integration,
investment recommendation service or validated commercial market-data system.

## 3. Sources of truth

Use this precedence order when sources conflict:

1. `reference/CWP1.8.5.pine.txt` for strategy semantics and same-bar order.
2. Explicit user requirements for product behavior.
3. `PROJECT_CONTEXT.md` for architecture and operational decisions.
4. Tests for locked regression behavior.
5. `README.md` for operator instructions.

The reference Pine file is immutable unless the user explicitly supplies a
new indicator version. Its SHA-256 is recorded in `PROJECT_CONTEXT.md`.

## 4. Non-negotiable engine invariants

### 4.1 Preserve Pine execution order

The engine must replay bars sequentially. Within one bar, keep this order:

1. market-profile parameters and volatility scaling;
2. confirmed fractals and Chan strokes;
3. stroke structure and recent stroke references;
4. current/active Zhongshu and break reset;
5. Chan regime and regime-before-Zhongshu memory;
6. micro pivots, Micro BOS and PA support events;
7. First Point and Second Buy/Sell lifecycle;
8. Wyckoff climax/test state;
9. Spring/UTAD lifecycle;
10. Zhongshu break registration;
11. direct break entry;
12. Third Buy/Sell lifecycle;
13. final-entry priority;
14. setup-specific risk creation;
15. active-risk lifecycle;
16. scanner-only status derivation.

Do not reorder these stages for apparent cleanliness. Pine `var` state and
same-bar assignments make order observable.

### 4.2 Do not replace state machines with proxies

Forbidden substitutions include:

- moving averages as a replacement for Chan regime;
- rolling quantiles as a replacement for Zhongshu;
- 20-day high/low sweeps as a replacement for 2B/3B/Spring;
- treating setup existence as automatic Micro BOS;
- one generic ATR stop for every setup.

Vectorisation is allowed for stateless reference series such as ATR or volume
SMA. Stateful Chan/Wyckoff/entry transitions must remain sequential unless an
alternative implementation proves identical with trace tests.

### 4.3 Avoid look-ahead

- A raw Chan fractal is confirmed one bar after its candidate bar.
- A micro pivot is registered only after its configured right-side bars exist.
- Store the pivot at its candidate bar but expose it to state only on the
  confirmation bar.
- Never use centred rolling windows as if the pivot were known earlier.

### 4.4 Pine-compatible numerical rules

- ATR14 uses Wilder RMA, not a simple rolling mean.
- Use previous-bar ATR where Pine uses `atr14[1]`.
- Apply market-profile and volatility scaling before using tolerances.
- Apply setup-specific structural anchors before ATR stop buffers.
- Round only at the public result boundary. Keep internal calculations as
  unrounded floats.

### 4.5 Entry priority is fixed

Long priority:

1. Spring
2. Second Buy (`2B`)
3. Third Buy (`3B`)
4. direct Zhongshu breakout (`BRK`)

Short priority:

1. UTAD
2. Second Sell (`2S`)
3. Third Sell (`3S`)
4. direct Zhongshu breakdown (`BRK_SHORT`)

China A-Shares never emit short entries.

### 4.6 Scanner statuses are not Pine strategy constants

`ENTRY / READY / WATCH / NONE` are scanner-layer classifications derived
after the Pine state has been updated:

- `ENTRY`: a final-entry boolean is true on the current bar;
- `READY`: a Pine pending lifecycle remains active;
- `WATCH`: a non-transition Chan/Wyckoff structure exists;
- `NONE`: no current entry, pending or watch state.

Do not describe these four labels as native TradingView outputs.

## 5. Layer boundaries

### `data/`

Owns constituents, ticker normalisation, OHLCV retrieval, adjustment policy,
validation, incremental merge and Parquet cache. It must not contain CWP signal
rules.

### `engine/`

Owns strategy state, market profiles, sequential replay and `ScanResult`. It
must not perform network calls, send messages or write repository state.

### `scanner/`

Owns universe orchestration, per-symbol error isolation, result ranking and
output writing. It must not duplicate strategy rules.

### `watchlist/`

Owns cross-run status comparison and lifecycle fields. It consumes scan
results; it does not recompute signals.

### `notification/`

Owns formatting, transport and notification deduplication. It reports model
facts and must not say `BUY NOW`, `SELL NOW` or imply an executed trade.

### `.github/workflows/`

Owns schedules, dependency installation, tests, scan commands, artifacts and
the controlled commit-back step.

## 6. Market and data contracts

Canonical per-symbol input:

```text
DatetimeIndex named date, ascending, unique
columns exactly: open, high, low, close, volume
numeric OHLC; positive prices; valid high/low envelope
```

Current data policy:

- US OHLCV: `yfinance`, `auto_adjust=True`.
- S&P 500 constituents: public Wikipedia table, cached for seven days.
- China OHLCV: AKShare `stock_zh_a_hist`, `adjust="qfq"`.
- HS300 constituents: AKShare CSI constituent endpoint, cached for seven days.
- First bootstrap: approximately 800 daily bars.
- Subsequent runs: download an overlap window, merge, deduplicate and keep the
  latest configured bar count.

Never silently mix adjusted and unadjusted histories. A corporate-action gap
must be adjusted consistently; a genuine overnight market gap must remain.

The current constituent sets are suitable for present-day scanning, not
survivorship-bias-free historical backtests.

## 7. Direction policy

The engine reproduces Pine defaults:

- HS300: `Long Only` enforced by market rules;
- S&P 500: `Both` by default.

The product's original daily-watchlist objective is primarily long-entry
screening. If a task requires long-only S&P output, pass
`get_market_profile("sp500", "Long Only")` explicitly and add a scanner/config
integration test. Do not assume `config/markets.yml: long_only` currently
controls the engine; at present `scanner.py` calls `get_market_profile(market)`
and `engine/market_profiles.py` is the runtime source of truth.

## 8. Public interfaces to preserve

Avoid breaking these without an explicit migration:

```python
get_market_profile(market, trade_direction=None)
scan_symbol(symbol, df, market_profile, name="", sector="", min_bars=180)
scan_history(df, market_profile)
replay_bars(df, market_profile)
run_scan(market, bars=800, download=True, ...)
```

`ScanResult.to_dict()` must remain serialisable to CSV and retain at least:

```text
symbol, market, signal_date, close
status, status_rank, setup, direction
regime, wyckoff, trigger
zs_zd, zs_zg
entry_price, sl, tp1, tp2
name, sector, notes, engine_version
```

New fields are allowed when old consumers remain compatible.

## 9. Parity and test requirements

### Minimum checks for every change

```bash
python -m compileall -q .
python scripts/smoke_test.py
python scripts/source_parity_smoke.py
pytest -q
```

If the environment lacks `pytest`, state that limitation and run equivalent
test functions directly. CI must still use real `pytest`.

### Engine changes

Any change to `engine/` must include or update tests covering the affected
source lifecycle. Prefer constructed deterministic OHLCV/state fixtures that
prove:

- event registration;
- pending state;
- confirmation;
- invalidation;
- expiry;
- same-bar priority;
- resulting risk anchor and target.

Run a performance check on 800 bars. Target approximately 0.1 seconds per
symbol on the reference environment; investigate material regressions above
0.25 seconds before accepting them.

### Parity hierarchy

1. Exact same OHLCV and TradingView per-bar export, if available.
2. Source-derived deterministic state tests.
3. Chart screenshots or alert logs for selected dates.
4. Latest-signal spot checks only as a weak fallback.

Never claim 100% TradingView parity without level 1 evidence. The current
approved description is `V1.8.5 source port`.

## 10. Watchlist and notification rules

- Active statuses: `WATCH`, `READY`, `ENTRY`.
- Default watch duration: 15 scan/trading days.
- `WATCH` expires after that period; stronger statuses remain tracked.
- Notify immediately only for new/advanced `ENTRY` and `READY` changes.
- Put `DROPPED` in the daily summary rather than sending one immediate message
  per symbol.
- The first run for a market sends a summary only; it must not flood the user
  with every existing setup.
- Deduplicate using market, symbol, signal date, setup and current status.
- Keep HS300 and S&P 500 summaries separate.
- Include direction in US messages.
- Risk values are model outputs, not execution instructions.

## 11. GitHub Actions rules

- Workflows use Python 3.11.
- Run tests before scanning.
- Keep `permissions: contents: write` only on scan workflows that commit state.
- Keep parity/PR workflows read-only.
- Never write tokens or chat IDs into code, YAML defaults, logs or artifacts.
- Required secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Commit only intended cache, output and state paths.
- Preserve notification deduplication state across runs.
- Upload output/log artifacts even when a run fails where practical.
- Treat schedule comments as UTC and reassess daylight-saving assumptions
  before changing cron expressions.
- Keep scan runs idempotent: rerunning the same market/date must not duplicate
  state transitions or notifications.

## 12. Coding and repository discipline

- Python 3.11+; use type hints for public functions.
- Prefer small named state-transition functions over one monolithic rewrite.
- Keep condition evaluation explicit when mirroring Pine.
- Do not catch exceptions silently in new code. Per-symbol failures may be
  isolated, but they must be logged with symbol and cause.
- Preserve existing user changes and unrelated files.
- Do not commit credentials, local `.env`, generated `__pycache__` or virtual
  environments.
- Do not delete cache/state history merely to make a test pass.
- Update `PROJECT_CONTEXT.md`, `README.md`, `ARCHITECTURE.md` and tests when a
  change alters behavior, file ownership, public fields or operating commands.

## 13. Versioning

- Parameter-preserving bug fix: patch version.
- Scanner/output feature with unchanged signal semantics: minor version.
- Any intended change to signal definitions, state order or risk logic: new
  documented strategy version; do not continue calling it V1.8.5.
- A newly supplied Pine source must be stored under `reference/` with its hash
  and mapped before replacing the current engine.

## 14. Definition of done

A task is complete only when:

1. the requested behavior is implemented at the correct layer;
2. V1.8.5 invariants are preserved or the deliberate divergence is documented;
3. relevant tests and source-parity smoke tests pass;
4. output schemas and downstream consumers remain compatible;
5. performance is acceptable for 500 + 300 daily symbols;
6. no secret or personal data is exposed;
7. documentation reflects the final code;
8. the handoff states what was verified and what remains unverified.

## 15. Known limitations agents must not conceal

- TradingView per-bar export was unavailable during the original port.
- Exact numerical parity is therefore not proven.
- Equal-high/equal-low edge behavior of TradingView pivot built-ins may still
  require empirical confirmation.
- Free data sources can change schema, throttle or return partial histories.
- The S&P 500 constituent source is current-universe data, not historical
  membership.
- `config/markets.yml` is not yet wired into runtime profile construction.
- Email transport exists but daily orchestration currently uses Telegram.
- The system does not place orders and must not be extended to do so without a
  separate risk, compliance and execution design.

