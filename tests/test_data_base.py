from __future__ import annotations

import pandas as pd

from data.base import frames_to_long, long_to_frames, normalize_ohlcv, validate_ohlcv


def test_normalize_chinese_columns(daily_ohlcv):
    raw = daily_ohlcv.reset_index().rename(
        columns={"index": "日期", "open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量"}
    )
    result = normalize_ohlcv(raw)
    valid, errors = validate_ohlcv(result, min_bars=200)
    assert valid, errors
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]


def test_long_cache_round_trip(daily_ohlcv):
    frames = {"AAA": daily_ohlcv, "BBB": daily_ohlcv * 2}
    restored = long_to_frames(frames_to_long(frames))
    pd.testing.assert_frame_equal(restored["AAA"], daily_ohlcv, check_freq=False, check_names=False)
