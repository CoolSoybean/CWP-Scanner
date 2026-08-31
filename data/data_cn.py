from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd

from data.base import load_cache, normalize_ohlcv, save_cache

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


def _login(bs: Any) -> None:
    login_result = bs.login()
    _check_result(login_result, "login")


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
) -> dict[str, pd.DataFrame]:
    import baostock as bs

    cache = load_cache(cache_path)
    updated = dict(cache)
    _login(bs)
    try:
        for symbol in symbols:
            try:
                # Forward-adjusted history can be restated after a corporate
                # action. Replace the full window rather than mixing adjustment
                # bases across incremental downloads.
                fresh = _query_cn_daily(bs, symbol=symbol, bars=bars)
                if not fresh.empty:
                    updated[symbol] = fresh
            except Exception as exc:  # noqa: BLE001 - isolate third-party failures per symbol
                LOGGER.error("Baostock download failed for %s: %s", symbol, exc)
            if request_pause:
                sleep(request_pause)
    finally:
        bs.logout()

    updated = {symbol: updated[symbol] for symbol in symbols if symbol in updated}
    save_cache(updated, cache_path)
    return updated


def load_cn_market_data(cache_path: str | Path = DEFAULT_CACHE_PATH) -> dict[str, pd.DataFrame]:
    return load_cache(cache_path)


def get_constituents(force_refresh: bool = False) -> pd.DataFrame:
    return get_hs300_constituents(force_refresh=force_refresh)


def update_cache(symbols: list[str], bars: int = 800) -> dict[str, pd.DataFrame]:
    return update_cn_cache(symbols, bars=bars)


def load_market_data() -> dict[str, pd.DataFrame]:
    return load_cn_market_data()
