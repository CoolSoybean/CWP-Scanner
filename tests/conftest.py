from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def daily_ohlcv() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=240)
    close = np.linspace(80.0, 120.0, len(dates)) + np.sin(np.arange(len(dates)) / 6)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(len(dates), 1_000_000),
        },
        index=dates,
    )

