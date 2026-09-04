from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import pandas as pd

from data.base import load_cache, merge_market_data, normalize_ohlcv, save_cache

DEFAULT_CONSTITUENTS_PATH = Path("cache/constituents/hs300_baostock.csv")
DEFAULT_CACHE_PATH = Path("cache/hs300_baostock_daily.parquet")
BAOSTOCK_DAILY_FIELDS = "date,open,high,low,close,volume,tradestatus"


LOGGER = logging.getLogger("cwp-scanner")


def normalize_cn_symbol(symbol: str) -> str:
    digits = "".join(character for character in str(symbol) if character.isdigit())
    return digits.zfill(6)[-6:]


def to_baostock_code(symbol: str) -> str:
    code = normalize_cn_symbol(symbol)
    exchange = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{exchange}.{code}"


def _check_result(result: Any, operation: str) -> None:
    if str(result.error_code) != "0":
        raise RuntimeError(f"Baostock {operation} failed: {result.error_code} {result.error_msg}")


def _result_frame(result: Any) -> pd.DataFrame:
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def _login(bs: Any, socket_timeout_seconds: float = 30.0) -> None:
    login_result = bs.login()
    _check_result(login_result, "login")
    if socket_timeout_seconds:
        try:
            from baostock.common import context

            connection = getattr(context, "default_socket", None)
            if connection is not None:
                connection.settimeout(socket_timeout_seconds)
        except (ImportError, AttributeError):
            # Lightweight test doubles do not expose Baostock's internal
            # context. Production Baostock does, so its shared session socket
            # receives a finite connect/read timeout.
            LOGGER.debug("Could not configure Baostock socket timeout")


def get_hs300_constituents(
    force_refresh: bool = False,
    cache_path: str | Path = DEFAULT_CONSTITUENTS_PATH,
) -> pd.DataFrame:
    path = Path(cache_path)
    cache_is_fresh = path.exists() and (
        pd.Timestamp.now().timestamp() - path.stat().st_mtime < timedelta(days=7).total_seconds()
    )
    if cache_is_fresh and not force_refresh:
        return pd.read_csv(path, dtype={"symbol": str})

    import baostock as bs

    logged_in = False
    try:
        _login(bs)
        logged_in = True
        query = bs.query_hs300_stocks()
        _check_result(query, "HS300 constituent query")
        raw = _result_frame(query)
        if raw.empty or "code" not in raw.columns:
            raise ValueError("Baostock returned no HS300 constituents")
        names = raw["code_name"].astype(str) if "code_name" in raw.columns else ""
        result = pd.DataFrame(
            {
                "symbol": raw["code"].map(normalize_cn_symbol),
                "name": names,
                "sector": "",
                "sub_industry": "",
            }
        ).drop_duplicates("symbol")
        path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(path, index=False)
        return result
    except Exception as exc:
        if path.exists():
            LOGGER.warning(
                "Could not refresh HS300 constituents; using cached file %s: %s", path, exc
            )
            return pd.read_csv(path, dtype={"symbol": str})
        raise
    finally:
        if logged_in:
            bs.logout()


def _query_cn_daily(
    bs: Any,
    symbol: str,
    bars: int = 800,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    end_date = end or pd.Timestamp.now().strftime("%Y-%m-%d")
    if start is None:
        start_ts = pd.Timestamp.now() - pd.Timedelta(days=max(1200, bars * 2))
        start_date = start_ts.strftime("%Y-%m-%d")
    else:
        start_date = start

    query = bs.query_history_k_data_plus(
        code=to_baostock_code(symbol),
        fields=BAOSTOCK_DAILY_FIELDS,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",
    )
    _check_result(query, f"daily query for {symbol}")
    raw = _result_frame(query)
    if raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], name="date"))
    if "tradestatus" in raw.columns:
        raw = raw[raw["tradestatus"] == "1"].drop(columns="tradestatus")
    return normalize_ohlcv(raw).tail(bars)


def adjustment_basis_changed(
    cached: pd.DataFrame,
    fresh_overlap: pd.DataFrame,
    tolerance: float = 1e-6,
) -> bool:
    """Return whether overlapping qfq prices use a different adjustment basis.

    Volume is intentionally excluded: vendor volume corrections do not imply
    that historical forward-adjusted prices need to be replaced.
    """
    common_dates = cached.index.intersection(fresh_overlap.index)
    if common_dates.empty:
        return True
    price_columns = ["open", "high", "low", "close"]
    old = cached.loc[common_dates, price_columns].astype(float)
    new = fresh_overlap.loc[common_dates, price_columns].astype(float)
    scale = old.abs().clip(lower=1.0)
    relative_difference = (new - old).abs() / scale
    return bool((relative_difference > tolerance).any().any())


def _query_cn_daily_with_retry(
    bs: Any,
    symbol: str,
    bars: int,
    start: str | None = None,
    end: str | None = None,
    retry_count: int = 2,
    retry_backoff_seconds: float = 1.0,
) -> pd.DataFrame:
    attempts = max(1, retry_count + 1)
    for attempt in range(1, attempts + 1):
        try:
            return _query_cn_daily(bs, symbol=symbol, bars=bars, start=start, end=end)
        except Exception as exc:
            if attempt >= attempts:
                raise
            delay = retry_backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning(
                "Baostock query failed for %s (attempt %s/%s): %s; retrying in %.1fs",
                symbol,
                attempt,
                attempts,
                exc,
                delay,
            )
            if delay:
                sleep(delay)
    raise AssertionError("unreachable")


def fetch_cn_daily(
    symbol: str,
    bars: int = 800,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    import baostock as bs

    _login(bs)
    try:
        return _query_cn_daily(bs, symbol=symbol, bars=bars, start=start, end=end)
    finally:
        bs.logout()


def update_cn_cache(
    symbols: list[str],
    bars: int = 800,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    request_pause: float = 0.02,
    force_full: bool = False,
    overlap_calendar_days: int = 45,
    adjustment_tolerance: float = 1e-6,
    retry_count: int = 2,
    retry_backoff_seconds: float = 1.0,
    socket_timeout_seconds: float = 30.0,
    progress_interval: int = 25,
    stats: dict[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    import baostock as bs

    cache = load_cache(cache_path)
    updated = dict(cache)
    started = perf_counter()
    counters: dict[str, Any] = {
        "constituent_count": len(symbols),
        "incremental_success": 0,
        "full_refresh": 0,
        "cache_fallback": 0,
        "failed": 0,
    }
    _login(bs, socket_timeout_seconds=socket_timeout_seconds)
    try:
        for position, symbol in enumerate(symbols, start=1):
            try:
                cached = cache.get(symbol)
                needs_full = force_full or cached is None or cached.empty
                if needs_full:
                    fresh = _query_cn_daily_with_retry(
                        bs,
                        symbol=symbol,
                        bars=bars,
                        retry_count=retry_count,
                        retry_backoff_seconds=retry_backoff_seconds,
                    )
                    if fresh.empty:
                        raise ValueError("Baostock returned no daily rows")
                    updated[symbol] = fresh
                    counters["full_refresh"] += 1
                else:
                    overlap_start = (
                        cached.index.max() - pd.Timedelta(days=overlap_calendar_days)
                    ).strftime("%Y-%m-%d")
                    recent = _query_cn_daily_with_retry(
                        bs,
                        symbol=symbol,
                        bars=bars,
                        start=overlap_start,
                        retry_count=retry_count,
                        retry_backoff_seconds=retry_backoff_seconds,
                    )
                    if recent.empty:
                        raise ValueError("Baostock returned no recent daily rows")
                    if adjustment_basis_changed(cached, recent, adjustment_tolerance):
                        LOGGER.info("Qfq basis change detected for %s; refreshing full window", symbol)
                        fresh = _query_cn_daily_with_retry(
                            bs,
                            symbol=symbol,
                            bars=bars,
                            retry_count=retry_count,
                            retry_backoff_seconds=retry_backoff_seconds,
                        )
                        if fresh.empty:
                            raise ValueError("Baostock returned no rows for full refresh")
                        updated[symbol] = fresh
                        counters["full_refresh"] += 1
                    else:
                        updated[symbol] = merge_market_data(cached, recent, max_bars=bars)
                        counters["incremental_success"] += 1
            except Exception as exc:  # noqa: BLE001 - isolate third-party failures per symbol
                LOGGER.error("Baostock download failed for %s: %s", symbol, exc)
                if symbol in cache:
                    updated[symbol] = cache[symbol]
                    counters["cache_fallback"] += 1
                else:
                    counters["failed"] += 1
            if request_pause:
                sleep(request_pause)
            if progress_interval and (position % progress_interval == 0 or position == len(symbols)):
                LOGGER.info(
                    "HS300 download progress: %s/%s, incremental=%s, full_refresh=%s, "
                    "fallback=%s, failed=%s, elapsed=%.1fs",
                    position,
                    len(symbols),
                    counters["incremental_success"],
                    counters["full_refresh"],
                    counters["cache_fallback"],
                    counters["failed"],
                    perf_counter() - started,
                )
    finally:
        bs.logout()

    updated = {symbol: updated[symbol] for symbol in symbols if symbol in updated}
    save_cache(updated, cache_path)
    counters["download_seconds"] = round(perf_counter() - started, 3)
    if stats is not None:
        stats.update(counters)
    return updated


def load_cn_market_data(cache_path: str | Path = DEFAULT_CACHE_PATH) -> dict[str, pd.DataFrame]:
    return load_cache(cache_path)


def get_constituents(force_refresh: bool = False) -> pd.DataFrame:
    return get_hs300_constituents(force_refresh=force_refresh)


def update_cache(
    symbols: list[str],
    bars: int = 800,
    **kwargs: Any,
) -> dict[str, pd.DataFrame]:
    return update_cn_cache(symbols, bars=bars, **kwargs)


def load_market_data() -> dict[str, pd.DataFrame]:
    return load_cn_market_data()
