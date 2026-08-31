from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
LONG_COLUMNS = ["date", "symbol", *OHLCV_COLUMNS]


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return a canonical, ascending daily OHLCV frame.

    Input column names are matched case-insensitively. Dates may be supplied in
    a date/datetime column or in the index. Prices are coerced to numeric and
    rows without a valid OHLC bar are discarded.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS, index=pd.DatetimeIndex([], name="date"))

    frame = df.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    rename = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "vol": "volume",
    }
    frame = frame.rename(columns=rename)

    if "date" in frame.columns:
        dates = pd.to_datetime(frame.pop("date"), errors="coerce")
        frame.index = dates
    else:
        frame.index = pd.to_datetime(frame.index, errors="coerce")

    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"OHLCV fields missing: {missing}")

    frame = frame[OHLCV_COLUMNS]
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame[~frame.index.isna()]
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame.index.name = "date"
    return frame


def validate_ohlcv(df: pd.DataFrame, min_bars: int = 180) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if df is None or df.empty:
        return False, ["empty data"]
    if len(df) < min_bars:
        errors.append(f"only {len(df)} bars; requires {min_bars}")
    if list(df.columns) != OHLCV_COLUMNS:
        errors.append(f"columns must be {OHLCV_COLUMNS}")
    if not isinstance(df.index, pd.DatetimeIndex):
        errors.append("index must be DatetimeIndex")
    elif not df.index.is_monotonic_increasing:
        errors.append("dates are not ascending")
    if df.index.has_duplicates:
        errors.append("duplicate dates")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        errors.append("non-positive OHLC price")
    if (df["high"] < df[["open", "close", "low"]].max(axis=1)).any():
        errors.append("high below another OHLC field")
    if (df["low"] > df[["open", "close", "high"]].min(axis=1)).any():
        errors.append("low above another OHLC field")
    return not errors, errors


def merge_market_data(
    cached_df: pd.DataFrame | None,
    new_df: pd.DataFrame,
    max_bars: int = 800,
) -> pd.DataFrame:
    old = normalize_ohlcv(cached_df) if cached_df is not None and not cached_df.empty else None
    new = normalize_ohlcv(new_df)
    merged = new if old is None else pd.concat([old, new])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged.tail(max_bars)


def frames_to_long(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for symbol, frame in frames.items():
        item = normalize_ohlcv(frame).reset_index()
        item.insert(1, "symbol", symbol)
        parts.append(item[LONG_COLUMNS])
    if not parts:
        return pd.DataFrame(columns=LONG_COLUMNS)
    return pd.concat(parts, ignore_index=True).sort_values(["symbol", "date"])


def long_to_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if frame is None or frame.empty:
        return {}
    required = set(LONG_COLUMNS)
    if not required.issubset(frame.columns):
        raise ValueError(f"Long cache missing columns: {sorted(required - set(frame.columns))}")
    return {
        str(symbol): normalize_ohlcv(group.drop(columns="symbol"))
        for symbol, group in frame.groupby("symbol", sort=False)
    }


def load_cache(path: str | Path) -> dict[str, pd.DataFrame]:
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    return long_to_frames(pd.read_parquet(cache_path))


def save_cache(frames: dict[str, pd.DataFrame], path: str | Path) -> None:
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    frames_to_long(frames).to_parquet(cache_path, index=False)


def select_recent_start(frames: dict[str, pd.DataFrame], fallback_days: int = 1200) -> str:
    latest_dates = [frame.index.max() for frame in frames.values() if not frame.empty]
    if not latest_dates:
        return (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=fallback_days)).strftime(
            "%Y-%m-%d"
        )
    return (min(latest_dates) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")


def requested_symbols(constituents: pd.DataFrame) -> list[str]:
    if "symbol" not in constituents.columns:
        raise ValueError("Constituent table requires a symbol column")
    return [str(value) for value in constituents["symbol"].dropna().drop_duplicates()]


def trim_frames(frames: dict[str, pd.DataFrame], symbols: Iterable[str], bars: int) -> dict[str, pd.DataFrame]:
    wanted = set(symbols)
    return {symbol: frame.tail(bars) for symbol, frame in frames.items() if symbol in wanted}

