# V1.8.5 source-port notes

## Scope

The Python engine follows the executable logic in Pine sections 2–27. Visual
objects, labels, tables and alert declarations in sections 28–39 do not affect
signal state and are not reproduced inside the engine.

## Source mapping

| Pine section | Python implementation |
|---|---|
| 2–4 Market/Profile | `MarketProfile`, `_bar_parameters()` |
| 3 Core references | `_rma()`, `_prepare_indicators()` |
| 6–7 Fractal/Stroke | `update_strokes()` |
| 8–9 Structure refs | `_stroke_structure()`, `_recent_strokes()` |
| 10–12 Zhongshu/Break state | `update_zhongshu()` |
| 13–14 Regime/memory | `detect_regime()`, `_regime_text()` |
| 15–16 Micro/PA | `_update_micro_structure()`, `_process_bar()` |
| 17 Second point | `_update_second_points()` |
| 18 Wyckoff | `update_wyckoff_state()` |
| 19 Spring/UTAD | `_update_spring_utad()` |
| 20–21 Break/direct entry | `_register_breaks()` |
| 22 Third point | `_update_third_points()` |
| 23 Entry priority | `_process_bar()` |
| 24–27 Risk | `calculate_trade_levels()`, `_update_risk_lifecycle()` |

## Execution-order rule

The engine intentionally replays one bar at a time. Within each bar it keeps
the Pine order: stroke → Zhongshu → regime → micro structure → second point →
Wyckoff → Spring/UTAD → break registration → third point → final entry → risk.
Reordering these stages changes same-bar state transitions.

## Scanner-only extension

`ENTRY / READY / WATCH / NONE` is not a Pine constant set. It is an external
scanner classification derived after all source states have been updated:

- `ENTRY`: a Pine final-entry boolean is true on the current bar;
- `READY`: one of the Pine pending states remains active;
- `WATCH`: a non-transition Chan/Wyckoff state exists;
- `NONE`: no actionable or watch state.

The underlying setup, regime, ZD/ZG, event and risk calculations come from the
ported source state machine.

## Remaining verification boundary

Without TradingView bar-state export, exact numerical parity cannot be proven.
The built-in pivot tie rule and upstream OHLCV adjustment are the principal
remaining variables. Use `scan_history()` to compare every available field if
TradingView exports become available later.

