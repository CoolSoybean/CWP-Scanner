from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.base import frames_to_long, long_to_frames, normalize_ohlcv, validate_ohlcv
from engine.cwp_engine import scan_symbol
from engine.market_profiles import get_market_profile
from notification.notifier import format_entry_alert
from parity.compare_outputs import compare_outputs
from watchlist.watchlist_state import classify_change


def main() -> None:
    dates = pd.bdate_range("2025-01-01", periods=240)
    close = np.linspace(80.0, 120.0, len(dates)) + np.sin(np.arange(len(dates)) / 6)
    frame = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(len(dates), 1_000_000),
        },
        index=dates,
    )

    canonical = normalize_ohlcv(frame)
    valid, errors = validate_ohlcv(canonical, min_bars=180)
    assert valid, errors
    restored = long_to_frames(frames_to_long({"TEST": frame}))["TEST"]
    assert len(restored) == len(frame)

    result = scan_symbol("TEST", frame, get_market_profile("sp500"))
    assert result.status in {"NONE", "WATCH", "READY", "ENTRY"}
    assert classify_change("READY", "ENTRY") == "READY_TO_ENTRY"

    event = result.to_dict()
    event.update({"previous_status": "READY", "current_status": "ENTRY"})
    message = format_entry_alert(event)
    assert "CWP LONG ENTRY" in message

    left = pd.DataFrame([{"date": "2026-08-31", "symbol": "TEST", "status": "ENTRY"}])
    right = pd.DataFrame([{"date": "2026-08-31", "symbol": "TEST", "status": "READY"}])
    assert len(compare_outputs(left, right, fields=["status"])) == 1
    print(f"smoke-ok status={result.status} setup={result.setup} regime={result.regime}")


if __name__ == "__main__":
    main()
