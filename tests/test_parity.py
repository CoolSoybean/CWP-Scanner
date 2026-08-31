from __future__ import annotations

import pandas as pd

from parity.compare_outputs import compare_outputs


def test_parity_detects_field_difference():
    pine = pd.DataFrame([{"date": "2026-08-31", "symbol": "NVDA", "status": "ENTRY"}])
    python = pd.DataFrame([{"date": "2026-08-31", "symbol": "NVDA", "status": "READY"}])
    mismatches = compare_outputs(pine, python, fields=["status"])
    assert len(mismatches) == 1
    assert mismatches.iloc[0]["field"] == "status"
