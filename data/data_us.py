from __future__ import annotations

from datetime import timedelta
from io import StringIO
import logging
from pathlib import Path

import pandas as pd
import requests

from data.base import load_cache, merge_market_data, normalize_ohlcv, save_cache


DEFAULT_CONSTITUENTS_PATH = Path("cache/constituents/sp500.csv")
DEFAULT_CACHE_PATH = Path("cache/sp500_daily.parquet")
WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CSV_ENCODING = "utf-8-sig"
LOGGER = logging.getLogger("cwp-scanner.data-us")
WIKIPEDIA_HEADERS = {
    "User-Agent": "CWP-Scanner/0.2 (+https://github.com/CoolSoybean/CWP-Scanner)",
    "Accept-Language": "en-GB,en;q=0.9",
}


def normalize_us_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".", "-")


def _read_constituents_cache(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"symbol": str}, encoding=CSV_ENCODING)


def _download_sp500_constituents() -> pd.DataFrame:
    response = requests.get(
        WIKIPEDIA_SP500_URL,
        headers=WIKIPEDIA_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text), attrs={"id": "constituents"})
    if not tables:
        raise ValueError("S&P 500 constituent table was not found")
    return tables[0]


def get_sp500_constituents(
    force_refresh: bool = False,
    cache_path: str | Path = DEFAULT_CONSTITUENTS_PATH,
) -> pd.DataFrame:
    path = Path(cache_path)
    cache_is_fresh = path.exists() and (
        pd.Timestamp.now().timestamp() - path.stat().st_mtime < timedelta(days=7).total_seconds()
    )
    if cache_is_fresh and not force_refresh:
        return _read_constituents_cache(path)

    try:
        raw = _download_sp500_constituents()
    except Exception as exc:
        if path.exists():
            LOGGER.warning(
                "Unable to refresh S&P 500 constituents; using cached file %s: %s",
                path,
                exc,
            )
            return _read_constituents_cache(path)
        raise RuntimeError(
            "Unable to download S&P 500 constituents and no cached file is available"
        ) from exc

    result = pd.DataFrame(
        {
            "symbol": raw["Symbol"].map(normalize_us_symbol),
            "name": raw["Security"].astype(str),
            "sector": raw["GICS Sector"].astype(str),
            "sub_industry": raw["GICS Sub-Industry"].astype(str),
        }
    ).drop_duplicates("symbol")
    path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(path, index=False, encoding=CSV_ENCODING)
    return result


def fetch_us_daily(
    symbols: list[str] | str,
    bars: int = 800,
    start: str | None = None,
) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    tickers = [normalize_us_symbol(symbol) for symbol in ([symbols] if isinstance(symbols, str) else symbols)]
    if not tickers:
        return {}
    if start is None:
        start = (pd.Timestamp.utcnow().tz_localize(None) - timedelta(days=max(1200, bars * 2))).strftime(
            "%Y-%m-%d"
        )

    downloaded = yf.download(
        tickers=tickers,
        start=start,
        interval="1d",
        auto_adjust=True,
        actions=False,
        threads=True,
        progress=False,
        group_by="ticker",
    )
    frames: dict[str, pd.DataFrame] = {}
    if len(tickers) == 1 and not isinstance(downloaded.columns, pd.MultiIndex):
        frames[tickers[0]] = normalize_ohlcv(downloaded).tail(bars)
        return frames

    for symbol in tickers:
        try:
            raw = downloaded[symbol]
        except (KeyError, TypeError):
            continue
        if raw.dropna(how="all").empty:
            continue
        frames[symbol] = normalize_ohlcv(raw).tail(bars)
    return frames


def update_us_cache(
    symbols: list[str],
    bars: int = 800,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    batch_size: int = 100,
) -> dict[str, pd.DataFrame]:
    cache = load_cache(cache_path)
    if cache:
        latest = max(frame.index.max() for frame in cache.values() if not frame.empty)
        start = (latest - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    else:
        start = None

    updated = dict(cache)
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        fresh = fetch_us_daily(batch, bars=bars, start=start)
        for symbol, frame in fresh.items():
            updated[symbol] = merge_market_data(updated.get(symbol), frame, max_bars=bars)

    updated = {symbol: updated[symbol] for symbol in symbols if symbol in updated}
    save_cache(updated, cache_path)
    return updated


def load_us_market_data(cache_path: str | Path = DEFAULT_CACHE_PATH) -> dict[str, pd.DataFrame]:
    return load_cache(cache_path)


def get_constituents(force_refresh: bool = False) -> pd.DataFrame:
    return get_sp500_constituents(force_refresh=force_refresh)


def update_cache(symbols: list[str], bars: int = 800) -> dict[str, pd.DataFrame]:
    return update_us_cache(symbols, bars=bars)
