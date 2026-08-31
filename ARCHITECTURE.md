# Architecture

`PROJECT_CONTEXT.md` 是完整的 Codex 交接说明；本文件只保留代码层依赖与调用关系速查。

## Layer ownership

```text
data_cn.py / data_us.py
  -> constituents + adjusted daily OHLCV + Parquet cache

cwp_engine.py
  -> sequential replay + structure state + ScanResult

scanner.py
  -> universe orchestration + validation + output

watchlist_state.py
  -> previous/current comparison + 15-day lifecycle

notifier.py
  -> human-readable messages + deduplication
```

## Main call chain

```text
GitHub Actions
  -> scanner.main()
    -> run_scan(market)
      -> get_market_adapter()
      -> adapter.get_constituents()
      -> adapter.update_cache()
        -> fetch_*_daily()
        -> normalize_ohlcv()
        -> merge_market_data()
        -> save_cache()
      -> scan_universe()
        -> validate_ohlcv()
        -> scan_symbol()
          -> replay_bars()
            -> _prepare_indicators()
            -> _process_bar() for every bar
              -> update_strokes()
              -> update_zhongshu()
              -> detect_regime()
              -> _update_micro_structure()
              -> _update_second_points()
              -> update_wyckoff_state()
              -> _update_spring_utad()
              -> _register_breaks()
              -> _update_third_points()
              -> calculate_trade_levels()
              -> _update_risk_lifecycle()
              -> _derive_scanner_state()
          -> build_scan_result()
      -> build_results()
      -> save_scan_outputs()
      -> compare_scan_with_state()
      -> update_watchlist()
      -> append_signal_history()
      -> notify_changes()
        -> build_notification_id()
        -> format_*_alert()
        -> send_telegram()
```

## Dependency rule

Higher layers may depend on lower layers. The engine never imports scanner,
watchlist, notification or GitHub-specific code. Data adapters never contain
signal rules. Notification code never recomputes market state.

The immutable strategy reference is `reference/CWP1.8.5.pine.txt`. Any engine
change that affects a V1.8.5 rule must cite the matching Pine section and add a
source-derived regression scenario.
