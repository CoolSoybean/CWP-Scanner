from __future__ import annotations

import logging
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from data.base import load_cache, merge_market_data, normalize_ohlcv, save_cache

DEFAULT_CONSTITUENTS_PATH = Path("cache/constituents/sp500.csv")
DEFAULT_CACHE_PATH = Path("cache/sp500_daily.parquet")
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SP500_PAGE = "List of S&P 500 companies"
WIKIPEDIA_USER_AGENT = (
    "CWP-Scanner/0.3.1 (https://github.com/CoolSoybean/CWP-Scanner)"
)


LOGGER = logging.getLogger("cwp-scanner")


def normalize_us_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".", "-")


def _fetch_sp500_constituent_table() -> pd.DataFrame:
    response = requests.get(
        WIKIPEDIA_API_URL,
        params={
            "action": "parse",
            "page": WIKIPEDIA_SP500_PAGE,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": WIKIPEDIA_USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    html = payload["parse"]["text"]
    tables = pd.read_html(StringIO(html))
    required = {"Symbol", "Security", "GICS Sector", "GICS Sub-Industry"}
    raw = next((table for table in tables if required.issubset(table.columns)), None)
    if raw is None:
        raise ValueError("Wikipedia response did not contain the S&P 500 constituent table")
    return raw


def get_sp500_constituents(
    force_refresh: bool = False,
    cache_path: str | Path = DEFAULT_CONSTITUENTS_PATH,
) -> pd.DataFrame:
    path = Path(cache_path)
    cache_is_fresh = path.exists() and (
        pd.Timestamp.now().timestamp() - path.stat().st_mtime < timedelta(days=7).total_seconds()
    )
    if cache_is_fresh and not force_refresh:
        return pd.read_csv(path, dtype={"symbol": str})

    try:
        raw = _fetch_sp500_constituent_table()
    except (requests.RequestException, KeyError, TypeError, ValueError, IndexError) as exc:
        if path.exists():
            LOGGER.warning(
                "Could not refresh S&P 500 constituents; using cached file %s: %s",
                path,
                exc,
            )
            return pd.read_csv(path, dtype={"symbol": str})
        raise RuntimeError(
            "Could not retrieve S&P 500 constituents from the Wikipedia API "
            "and no cached constituent file is available"
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
    result.to_csv(path, index=False)
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
