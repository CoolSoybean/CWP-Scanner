from __future__ import annotations

import numpy as np
import pandas as pd

from engine.cwp_engine import _prepare_indicators, scan_history, scan_symbol, update_zhongshu
from engine.market_profiles import get_market_profile
from engine.models import EngineState


def test_scan_symbol_returns_canonical_result(daily_ohlcv):
    result = scan_symbol("TEST", daily_ohlcv, get_market_profile("sp500"))
    assert result.symbol == "TEST"
    assert result.market == "SP500"
    assert result.status in {"NONE", "WATCH", "READY", "ENTRY"}
    assert result.engine_version == "1.8.5-source-port"


def test_uptrend_produces_valid_chan_state(daily_ohlcv):
    result = scan_symbol("TREND", daily_ohlcv, get_market_profile("sp500"))
    assert result.status in {"NONE", "WATCH", "READY", "ENTRY"}
    assert result.regime in {
        "Unknown",
        "Transition",
        "Bull Trend",
        "Bear Trend",
        "Bullish Zhongshu",
        "Bearish Zhongshu",
        "Neutral Zhongshu",
    }


def test_atr_uses_wilder_rma(daily_ohlcv):
    profile = get_market_profile("sp500")
    prepared = _prepare_indicators(daily_ohlcv, profile)
    tr = prepared["true_range"]
    expected_seed = tr.iloc[:14].mean()
    assert prepared["atr14"].iloc[13] == expected_seed
    expected_next = (expected_seed * 13 + tr.iloc[14]) / 14
    assert prepared["atr14"].iloc[14] == expected_next


def test_zhongshu_is_three_segment_overlap():
    state = EngineState(
        stroke_prices=[10.0, 5.0, 9.0, 6.0],
        stroke_types=[1, -1, 1, -1],
        stroke_bars=[1, 5, 9, 13],
    )
    assert update_zhongshu(state)
    assert state.zs_zg == 9.0
    assert state.zs_zd == 6.0
    assert state.zs_gg == 10.0
    assert state.zs_dd == 5.0


def test_trace_exposes_source_state(daily_ohlcv):
    trace = scan_history(daily_ohlcv, get_market_profile("sp500"))
    required = {
        "stroke_count",
        "zs_active",
        "regime",
        "wyckoff",
        "spring_event",
        "second_buy_entry",
        "third_buy_entry",
        "fresh_bullish_zs_break",
    }
    assert required.issubset(trace.columns)
    assert len(trace) == len(daily_ohlcv)


def test_zigzag_builds_alternating_strokes_and_zhongshu():
    anchors = [100, 110, 100, 112, 102, 114, 104, 116, 106, 118, 108, 120]
    values: list[float] = []
    for start, end in zip(anchors[:-1], anchors[1:]):
        values.extend(np.linspace(start, end, 6, endpoint=False))
    values.extend([anchors[-1]] * 20)
    close = np.asarray(values, dtype=float)
    frame = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1_000_000,
        },
        index=pd.bdate_range("2025-01-01", periods=len(close)),
    )
    trace = scan_history(frame, get_market_profile("sp500"))
    assert trace.iloc[-1]["stroke_count"] >= 8
    assert bool(trace.iloc[-1]["zs_active"])
    assert trace.iloc[-1]["zs_zg"] > trace.iloc[-1]["zs_zd"]
