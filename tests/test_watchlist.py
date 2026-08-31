from __future__ import annotations

import pandas as pd

from watchlist.watchlist_state import classify_change, compare_scan_with_state, update_watchlist


def test_classify_change():
    assert classify_change("READY", "ENTRY") == "READY_TO_ENTRY"
    assert classify_change("WATCH", "READY") == "WATCH_TO_READY"
    assert classify_change("WATCH", "NONE") == "DROPPED"


def test_compare_and_update_state():
    scan = pd.DataFrame(
        [{"market": "SP500", "symbol": "NVDA", "status": "ENTRY", "status_rank": 3}]
    )
    previous = pd.DataFrame(
        [{"market": "SP500", "symbol": "NVDA", "current_status": "READY", "days_tracked": 2, "first_seen": "2026-08-28", "highest_status_rank": 2}]
    )
    changes = compare_scan_with_state(scan, previous)
    assert changes.iloc[0]["change_type"] == "READY_TO_ENTRY"
    state = update_watchlist(scan, previous, as_of="2026-08-31")
    assert state.iloc[0]["days_tracked"] == 3
    assert state.iloc[0]["highest_status_rank"] == 3

