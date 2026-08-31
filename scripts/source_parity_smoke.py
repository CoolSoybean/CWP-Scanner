from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from engine.cwp_engine import _prepare_indicators, scan_history, update_zhongshu
from engine.market_profiles import get_market_profile
from engine.models import EngineState


def _zigzag() -> pd.DataFrame:
    anchors = [100, 110, 100, 112, 102, 114, 104, 116, 106, 118, 108, 120]
    values: list[float] = []
    for start, end in zip(anchors[:-1], anchors[1:]):
        values.extend(np.linspace(start, end, 6, endpoint=False))
    values.extend([anchors[-1]] * 20)
    close = np.asarray(values, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1_000_000,
        },
        index=pd.bdate_range("2025-01-01", periods=len(close)),
    )


def main() -> None:
    profile = get_market_profile("sp500")
    frame = _zigzag()
    prepared = _prepare_indicators(frame, profile)
    seed = prepared["true_range"].iloc[:14].mean()
    assert abs(prepared["atr14"].iloc[13] - seed) < 1e-12
    expected_next = (seed * 13 + prepared["true_range"].iloc[14]) / 14
    assert abs(prepared["atr14"].iloc[14] - expected_next) < 1e-12

    state = EngineState(
        stroke_prices=[10.0, 5.0, 9.0, 6.0],
        stroke_types=[1, -1, 1, -1],
        stroke_bars=[1, 5, 9, 13],
    )
    assert update_zhongshu(state)
    assert (state.zs_zd, state.zs_zg, state.zs_dd, state.zs_gg) == (6.0, 9.0, 5.0, 10.0)

    trace = scan_history(frame, profile)
    latest = trace.iloc[-1]
    assert latest["stroke_count"] >= 8
    assert bool(latest["zs_active"])
    assert latest["zs_zg"] > latest["zs_zd"]
    assert latest["regime"] == "Bull Trend"
    print(
        "source-parity-smoke-ok",
        f"strokes={latest['stroke_count']}",
        f"zs={latest['zs_zd']:.2f}-{latest['zs_zg']:.2f}",
        f"regime={latest['regime']}",
    )


if __name__ == "__main__":
    main()
