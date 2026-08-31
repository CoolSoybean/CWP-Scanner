# Architecture

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
            -> update_strokes()
            -> update_zhongshu()
            -> detect_regime()
            -> update_wyckoff_state()
            -> update_setups()
            -> detect_micro_bos()
            -> determine_scan_status()
          -> calculate_trade_levels()
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

