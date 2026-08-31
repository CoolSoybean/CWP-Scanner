from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

import pandas as pd

from data.base import load_cache, merge_market_data, normalize_ohlcv, save_cache


DEFAULT_CONSTITUENTS_PATH = Path("cache/constituents/hs300.csv")
DEFAULT_CACHE_PATH = Path("cache/hs300_daily.parquet")


def normalize_cn_symbol(symbol: str) -> str:
    digits = "".join(character for character in str(symbol) if character.isdigit())
    return digits.zfill(6)[-6:]


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
    result.to_csv(path, index=False)
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


def update_cn_cache(
    symbols: list[str],
    bars: int = 800,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    request_pause: float = 0.05,
) -> dict[str, pd.DataFrame]:
    cache = load_cache(cache_path)
    updated = dict(cache)
    for symbol in symbols:
        old = updated.get(symbol)
        start = None
        if old is not None and not old.empty:
            start = (old.index.max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        try:
            fresh = fetch_cn_daily(symbol, bars=bars, start=start)
            if not fresh.empty:
                updated[symbol] = merge_market_data(old, fresh, max_bars=bars)
        except Exception:
            # The scanner validates cached data and records symbols that remain unavailable.
            if old is None:
                continue
        if request_pause:
            sleep(request_pause)

    updated = {symbol: updated[symbol] for symbol in symbols if symbol in updated}
    save_cache(updated, cache_path)
    return updated


def load_cn_market_data(cache_path: str | Path = DEFAULT_CACHE_PATH) -> dict[str, pd.DataFrame]:
    return load_cache(cache_path)


def get_constituents(force_refresh: bool = False) -> pd.DataFrame:
    return get_hs300_constituents(force_refresh=force_refresh)


def update_cache(symbols: list[str], bars: int = 800) -> dict[str, pd.DataFrame]:
    return update_cn_cache(symbols, bars=bars)
