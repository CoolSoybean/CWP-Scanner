from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
from time import sleep

import pandas as pd

from data.base import load_cache, merge_market_data, normalize_ohlcv, save_cache


DEFAULT_CONSTITUENTS_PATH = Path("cache/constituents/hs300.csv")
DEFAULT_CACHE_PATH = Path("cache/hs300_daily.parquet")
CSV_ENCODING = "utf-8-sig"
LOGGER = logging.getLogger("cwp-scanner.data-cn")
AKSHARE_FAILURE_LIMIT = 5


def normalize_cn_symbol(symbol: str) -> str:
    digits = "".join(character for character in str(symbol) if character.isdigit())
    return digits.zfill(6)[-6:]


def to_yahoo_cn_symbol(symbol: str) -> str:
    code = normalize_cn_symbol(symbol)
    exchange = "SS" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{exchange}"


def get_hs300_constituents(
    force_refresh: bool = False,
    cache_path: str | Path = DEFAULT_CONSTITUENTS_PATH,
) -> pd.DataFrame:
    path = Path(cache_path)
    cache_is_fresh = path.exists() and (
        pd.Timestamp.now().timestamp() - path.stat().st_mtime < timedelta(days=7).total_seconds()
    )
    if cache_is_fresh and not force_refresh:
        return pd.read_csv(path, dtype={"symbol": str}, encoding=CSV_ENCODING)

    import akshare as ak

    raw = ak.index_stock_cons_csindex(symbol="000300")
    columns = {str(column): column for column in raw.columns}
    code_col = next((columns[name] for name in ["成分券代码", "品种代码", "证券代码"] if name in columns), None)
    name_col = next((columns[name] for name in ["成分券名称", "品种名称", "证券简称"] if name in columns), None)
    if code_col is None:
        raise ValueError(f"Could not locate HS300 symbol field; received {list(raw.columns)}")

    result = pd.DataFrame(
        {
            "symbol": raw[code_col].map(normalize_cn_symbol),
            "name": raw[name_col].astype(str) if name_col is not None else "",
            "sector": "",
            "sub_industry": "",
        }
    ).drop_duplicates("symbol")
    path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(path, index=False, encoding=CSV_ENCODING)
    return result


def fetch_cn_daily(
    symbol: str,
    bars: int = 800,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    import akshare as ak

    code = normalize_cn_symbol(symbol)
    end_date = (end or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    if start is None:
        start_ts = pd.Timestamp.now() - pd.Timedelta(days=max(1200, bars * 2))
        start_date = start_ts.strftime("%Y%m%d")
    else:
        start_date = start.replace("-", "")

    raw = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )
    return normalize_ohlcv(raw).tail(bars)


def fetch_cn_daily_yahoo(
    symbols: list[str],
    bars: int = 800,
    start: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Batch fallback for runners that cannot reach AKShare's upstream host."""
    import yfinance as yf

    codes = [normalize_cn_symbol(symbol) for symbol in symbols]
    yahoo_by_code = {code: to_yahoo_cn_symbol(code) for code in codes}
    if not yahoo_by_code:
        return {}
    if start is None:
        start = (pd.Timestamp.now() - pd.Timedelta(days=max(1200, bars * 2))).strftime("%Y-%m-%d")

    downloaded = yf.download(
        tickers=list(yahoo_by_code.values()),
        start=start,
        interval="1d",
        auto_adjust=True,
        actions=False,
        threads=True,
        progress=False,
        group_by="ticker",
    )
    frames: dict[str, pd.DataFrame] = {}
    for code, ticker in yahoo_by_code.items():
        try:
            if len(yahoo_by_code) == 1 and not isinstance(downloaded.columns, pd.MultiIndex):
                raw = downloaded
            else:
                raw = downloaded[ticker]
        except (KeyError, TypeError):
            continue
        if raw.dropna(how="all").empty:
            continue
        frames[code] = normalize_ohlcv(raw).tail(bars)
    return frames


def update_cn_cache(
    symbols: list[str],
    bars: int = 800,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    request_pause: float = 0.05,
    fallback_batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    cache = load_cache(cache_path)
    updated = dict(cache)
    fallback_symbols: list[str] = []
    consecutive_failures = 0
    for position, symbol in enumerate(symbols):
        old = updated.get(symbol)
        start = None
        if old is not None and not old.empty:
            start = (old.index.max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            fresh = fetch_cn_daily(symbol, bars=bars, start=start)
            if not fresh.empty:
                updated[symbol] = merge_market_data(old, fresh, max_bars=bars)
                consecutive_failures = 0
            else:
                LOGGER.warning("AKShare returned empty data for %s", symbol)
                fallback_symbols.append(symbol)
                consecutive_failures += 1
        except Exception as exc:
            # The scanner validates cached data and records symbols that remain unavailable.
            LOGGER.warning("Failed to download HS300 data for %s: %s", symbol, exc)
            fallback_symbols.append(symbol)
            consecutive_failures += 1
        if consecutive_failures >= AKSHARE_FAILURE_LIMIT:
            remaining = symbols[position + 1 :]
            fallback_symbols.extend(remaining)
            LOGGER.warning(
                "AKShare circuit breaker opened after %s consecutive failures; "
                "moving %s remaining symbols to the batch fallback",
                consecutive_failures,
                len(remaining),
            )
            break
        if request_pause:
            sleep(request_pause)

    if fallback_symbols:
        LOGGER.warning(
            "Using Yahoo Finance fallback for %s HS300 symbols",
            len(fallback_symbols),
        )
        cached_fallback = [
            updated[symbol].index.max()
            for symbol in fallback_symbols
            if symbol in updated and not updated[symbol].empty
        ]
        fallback_start = (
            (min(cached_fallback) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
            if cached_fallback and all(symbol in updated for symbol in fallback_symbols)
            else None
        )
        for offset in range(0, len(fallback_symbols), fallback_batch_size):
            batch = fallback_symbols[offset : offset + fallback_batch_size]
            try:
                fallback_data = fetch_cn_daily_yahoo(batch, bars=bars, start=fallback_start)
            except Exception as exc:
                LOGGER.warning("Yahoo Finance HS300 fallback batch failed: %s", exc)
                continue
            for symbol, frame in fallback_data.items():
                updated[symbol] = merge_market_data(updated.get(symbol), frame, max_bars=bars)

    updated = {symbol: updated[symbol] for symbol in symbols if symbol in updated}
    if not updated:
        raise RuntimeError("AKShare returned no usable HS300 market data for any symbol")
    save_cache(updated, cache_path)
    return updated


def load_cn_market_data(cache_path: str | Path = DEFAULT_CACHE_PATH) -> dict[str, pd.DataFrame]:
    return load_cache(cache_path)


def get_constituents(force_refresh: bool = False) -> pd.DataFrame:
    return get_hs300_constituents(force_refresh=force_refresh)


def update_cache(symbols: list[str], bars: int = 800) -> dict[str, pd.DataFrame]:
    return update_cn_cache(symbols, bars=bars)
