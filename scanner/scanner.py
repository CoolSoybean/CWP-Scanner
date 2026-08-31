from __future__ import annotations

import argparse
import importlib
import logging
import os
from pathlib import Path

import pandas as pd
import yaml

from data.base import load_cache, requested_symbols, validate_ohlcv
from engine.cwp_engine import scan_symbol
from engine.market_profiles import get_market_profile
from engine.models import ScanResult
from notification.notifier import format_daily_summary, notify_changes
from notification.telegram import send_telegram
from scanner.result_builder import build_results, save_scan_outputs
from watchlist.watchlist_state import (
    append_signal_history,
    compare_scan_with_state,
    load_watchlist_state,
    save_watchlist_state,
    update_watchlist,
)


LOGGER = logging.getLogger("cwp-scanner")


def load_settings(path: str | Path = "config/scanner.yml") -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_market_adapter(market: str):
    modules = {"sp500": "data.data_us", "hs300": "data.data_cn"}
    key = market.lower()
    if key not in modules:
        raise ValueError(f"Unsupported market {market!r}")
    return importlib.import_module(modules[key])


def handle_scan_error(symbol: str, exception: Exception) -> None:
    LOGGER.error("%s: %s", symbol, exception)


def scan_universe(
    constituents: pd.DataFrame,
    market_data: dict[str, pd.DataFrame],
    market: str,
    min_bars: int = 180,
) -> list[ScanResult]:
    profile = get_market_profile(market)
    metadata = constituents.set_index("symbol").to_dict("index")
    results: list[ScanResult] = []
    for symbol in requested_symbols(constituents):
        frame = market_data.get(symbol)
        if frame is None:
            handle_scan_error(symbol, ValueError("no market data"))
            continue
        valid, errors = validate_ohlcv(frame, min_bars=min_bars)
        if not valid:
            handle_scan_error(symbol, ValueError("; ".join(errors)))
            continue
        details = metadata.get(symbol, {})
        try:
            results.append(
                scan_symbol(
                    symbol=symbol,
                    df=frame,
                    market_profile=profile,
                    name=str(details.get("name", "")),
                    sector=str(details.get("sector", "")),
                    min_bars=min_bars,
                )
            )
        except Exception as exc:  # a single symbol must not stop the market scan
            handle_scan_error(symbol, exc)
    return results


def run_scan(
    market: str,
    bars: int = 800,
    download: bool = True,
    force_constituents: bool = False,
    notify: bool = False,
    dry_run_notifications: bool = False,
    root: str | Path = ".",
) -> pd.DataFrame:
    root_path = Path(root).resolve()
    settings = load_settings(root_path / "config" / "scanner.yml")
    scanner_config = settings.get("scanner", {})
    min_bars = int(scanner_config.get("min_bars", 180))
    max_tracking = int(scanner_config.get("watchlist_max_trading_days", 15))

    previous_cwd = Path.cwd()
    os.chdir(root_path)
    try:
        adapter = get_market_adapter(market)
        constituents = adapter.get_constituents(force_refresh=force_constituents)
        symbols = requested_symbols(constituents)
        if download:
            market_data = adapter.update_cache(symbols, bars=bars)
        elif hasattr(adapter, "load_market_data"):
            market_data = adapter.load_market_data()
        else:
            cache_path = root_path / "cache" / f"{market}_daily.parquet"
            market_data = load_cache(cache_path)

        results = scan_universe(constituents, market_data, market, min_bars=min_bars)
        result_df = build_results(results)
        save_scan_outputs(result_df, market, root=root_path)

        state_path = root_path / "state" / "watchlist.csv"
        previous_state = load_watchlist_state(state_path)
        market_previous = (
            previous_state[previous_state["market"] == market.upper()].copy()
            if not previous_state.empty
            else pd.DataFrame()
        )
        has_previous_market_state = not market_previous.empty
        other_markets = (
            previous_state[previous_state["market"] != market.upper()].copy()
            if not previous_state.empty
            else pd.DataFrame()
        )
        changes = compare_scan_with_state(result_df, market_previous)
        changes_path = root_path / "output" / "alerts" / f"{market}_changes.csv"
        changes.to_csv(changes_path, index=False)
        new_market_state = update_watchlist(
            result_df,
            market_previous,
            max_tracking_days=max_tracking,
        )
        combined_state = pd.concat([other_markets, new_market_state], ignore_index=True)
        save_watchlist_state(combined_state, state_path)
        append_signal_history(changes, root_path / "state" / "signal_history.csv")

        summary = format_daily_summary(result_df, changes, market)
        report_path = root_path / "output" / "reports" / f"{market}_summary.md"
        report_path.write_text(summary + "\n", encoding="utf-8")
        if notify:
            # Bootstrap runs send only the summary, otherwise every existing
            # READY/ENTRY symbol would be misrepresented as a new event.
            if has_previous_market_state:
                notify_changes(
                    changes,
                    root_path / "state" / "notifications.json",
                    dry_run=dry_run_notifications,
                )
            if not dry_run_notifications:
                send_telegram(summary)
        return result_df
    finally:
        os.chdir(previous_cwd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CWP daily market scanner")
    parser.add_argument("--market", choices=["hs300", "sp500"], required=True)
    parser.add_argument("--bars", type=int, default=800)
    parser.add_argument("--root", default=".")
    parser.add_argument("--no-download", action="store_true", help="Use existing Parquet cache")
    parser.add_argument("--force-constituents", action="store_true")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--dry-run-notifications", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    log_path = Path(args.root) / "logs" / "scan_errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )
    result = run_scan(
        market=args.market,
        bars=args.bars,
        download=not args.no_download,
        force_constituents=args.force_constituents,
        notify=args.notify,
        dry_run_notifications=args.dry_run_notifications,
        root=args.root,
    )
    LOGGER.info("Completed %s scan with %s valid symbols", args.market, len(result))


if __name__ == "__main__":
    main()
