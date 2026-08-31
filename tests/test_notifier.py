from __future__ import annotations

import pandas as pd

from notification.notifier import format_daily_summary, format_entry_alert, notify_changes


def _entry_event():
    return {
        "market": "SP500",
        "symbol": "NVDA",
        "name": "NVIDIA",
        "signal_date": "2026-08-31",
        "setup": "3B",
        "regime": "Bull Trend",
        "wyckoff": "Re-Accumulation",
        "trigger": "Bull Micro BOS",
        "close": 184.25,
        "zs_zd": 176.4,
        "zs_zg": 181.8,
        "entry_price": 184.25,
        "sl": 178.9,
        "tp1": 194.95,
        "tp2": 200.3,
        "previous_status": "READY",
        "current_status": "ENTRY",
        "change_type": "READY_TO_ENTRY",
        "status": "ENTRY",
        "direction": "LONG",
    }


def test_entry_format():
    message = format_entry_alert(_entry_event())
    assert "CWP LONG ENTRY" in message
    assert "READY → ENTRY" in message
    assert "not an order instruction" in message


def test_dry_run_does_not_write_dedupe(tmp_path):
    messages = notify_changes(pd.DataFrame([_entry_event()]), tmp_path / "sent.json", dry_run=True)
    assert len(messages) == 1
    assert not (tmp_path / "sent.json").exists()


def test_summary_counts():
    scan = pd.DataFrame([_entry_event()])
    changes = scan.copy()
    summary = format_daily_summary(scan, changes, "sp500")
    assert "ENTRY: 1" in summary
