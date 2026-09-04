from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from data.base import save_cache
from data.data_cn import (
    adjustment_basis_changed,
    fetch_cn_daily,
    get_hs300_constituents,
    to_baostock_code,
    update_cn_cache,
)


class FakeResult:
    def __init__(self, fields, rows, error_code="0", error_msg=""):
        self.fields = fields
        self.rows = rows
        self.error_code = error_code
        self.error_msg = error_msg
        self.position = 0

    def next(self):
        if self.position >= len(self.rows):
            return False
        self.position += 1
        return True

    def get_row_data(self):
        return self.rows[self.position - 1]


def test_to_baostock_code():
    assert to_baostock_code("600519") == "sh.600519"
    assert to_baostock_code("688981") == "sh.688981"
    assert to_baostock_code("000001") == "sz.000001"
    assert to_baostock_code("300750") == "sz.300750"


def test_get_hs300_constituents_from_baostock(monkeypatch, tmp_path):
    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_hs300_stocks=lambda: FakeResult(
            ["updateDate", "code", "code_name"],
            [["2026-08-31", "sh.600519", "贵州茅台"], ["2026-08-31", "sz.000001", "平安银行"]],
        ),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    result = get_hs300_constituents(cache_path=tmp_path / "hs300.csv")

    assert result["symbol"].tolist() == ["600519", "000001"]
    assert result["name"].tolist() == ["贵州茅台", "平安银行"]


def test_fetch_cn_daily_uses_qfq_and_filters_suspensions(monkeypatch):
    captured = {}

    def query_history_k_data_plus(**kwargs):
        captured.update(kwargs)
        return FakeResult(
            ["date", "open", "high", "low", "close", "volume", "tradestatus"],
            [
                ["2026-08-28", "10", "11", "9", "10.5", "1000", "1"],
                ["2026-08-29", "10.5", "10.5", "10.5", "10.5", "0", "0"],
                ["2026-08-31", "10.5", "12", "10", "11.5", "1200", "1"],
            ],
        )

    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_history_k_data_plus=query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)

    result = fetch_cn_daily("600519", start="2026-08-01", end="2026-08-31")

    assert captured["code"] == "sh.600519"
    assert captured["frequency"] == "d"
    assert captured["adjustflag"] == "2"
    assert result.index.strftime("%Y-%m-%d").tolist() == ["2026-08-28", "2026-08-31"]
    assert result["close"].tolist() == [10.5, 11.5]


def test_update_cn_cache_replaces_full_qfq_window(monkeypatch, tmp_path):
    captured = {}

    def query_history_k_data_plus(**kwargs):
        captured.update(kwargs)
        return FakeResult(
            ["date", "open", "high", "low", "close", "volume", "tradestatus"],
            [["2026-08-31", "20", "21", "19", "20.5", "2000", "1"]],
        )

    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_history_k_data_plus=query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)
    cache_path = tmp_path / "hs300.parquet"
    old = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [1000]},
        index=pd.DatetimeIndex(["2026-08-20"], name="date"),
    )
    save_cache({"600519": old}, cache_path)

    result = update_cn_cache(["600519"], bars=800, cache_path=cache_path, request_pause=0)

    assert result["600519"].index.strftime("%Y-%m-%d").tolist() == ["2026-08-31"]
    assert captured["start_date"] < "2024-01-01"


def _price_frame(dates, closes):
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=pd.DatetimeIndex(dates, name="date"),
    )


def test_adjustment_basis_changed_uses_price_overlap_only():
    cached = _price_frame(["2026-08-28", "2026-08-31"], [10.0, 11.0])
    recent = cached.copy()
    recent["volume"] = [2000, 3000]

    assert not adjustment_basis_changed(cached, recent)

    recent.loc[pd.Timestamp("2026-08-28"), "close"] = 9.5
    assert adjustment_basis_changed(cached, recent)


def test_update_cn_cache_merges_increment_when_qfq_basis_matches(monkeypatch, tmp_path):
    calls = []

    def query_history_k_data_plus(**kwargs):
        calls.append(kwargs)
        return FakeResult(
            ["date", "open", "high", "low", "close", "volume", "tradestatus"],
            [
                ["2026-08-31", "10", "11", "9", "10", "2000", "1"],
                ["2026-09-01", "11", "12", "10", "11", "2100", "1"],
            ],
        )

    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_history_k_data_plus=query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)
    cache_path = tmp_path / "hs300.parquet"
    save_cache({"600519": _price_frame(["2026-08-31"], [10.0])}, cache_path)
    stats = {}

    result = update_cn_cache(
        ["600519"],
        cache_path=cache_path,
        request_pause=0,
        retry_backoff_seconds=0,
        stats=stats,
    )

    assert len(calls) == 1
    assert calls[0]["start_date"] == "2026-07-17"
    assert result["600519"].index.strftime("%Y-%m-%d").tolist() == [
        "2026-08-31",
        "2026-09-01",
    ]
    assert stats["incremental_success"] == 1
    assert stats["full_refresh"] == 0


def test_update_cn_cache_refreshes_full_window_on_qfq_change(monkeypatch, tmp_path):
    calls = []

    def query_history_k_data_plus(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            rows = [["2026-08-31", "8", "9", "7", "8", "2000", "1"]]
        else:
            rows = [
                ["2026-08-30", "7", "8", "6", "7", "1900", "1"],
                ["2026-08-31", "8", "9", "7", "8", "2000", "1"],
            ]
        return FakeResult(
            ["date", "open", "high", "low", "close", "volume", "tradestatus"], rows
        )

    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_history_k_data_plus=query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)
    cache_path = tmp_path / "hs300.parquet"
    save_cache({"600519": _price_frame(["2026-08-31"], [10.0])}, cache_path)
    stats = {}

    result = update_cn_cache(
        ["600519"],
        cache_path=cache_path,
        request_pause=0,
        retry_backoff_seconds=0,
        stats=stats,
    )

    assert len(calls) == 2
    assert calls[1]["start_date"] < "2024-01-01"
    assert result["600519"]["close"].tolist() == [7.0, 8.0]
    assert stats["full_refresh"] == 1


def test_update_cn_cache_retries_then_preserves_cached_data(monkeypatch, tmp_path):
    attempts = 0

    def query_history_k_data_plus(**kwargs):
        nonlocal attempts
        attempts += 1
        return FakeResult([], [], error_code="1", error_msg="temporary failure")

    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_history_k_data_plus=query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)
    cache_path = tmp_path / "hs300.parquet"
    cached = _price_frame(["2026-08-31"], [10.0])
    save_cache({"600519": cached}, cache_path)
    stats = {}

    result = update_cn_cache(
        ["600519"],
        cache_path=cache_path,
        request_pause=0,
        retry_count=2,
        retry_backoff_seconds=0,
        stats=stats,
    )

    assert attempts == 3
    pd.testing.assert_frame_equal(result["600519"], cached, check_freq=False)
    assert stats["cache_fallback"] == 1


def test_update_cn_cache_force_full_skips_incremental_query(monkeypatch, tmp_path):
    calls = []

    def query_history_k_data_plus(**kwargs):
        calls.append(kwargs)
        return FakeResult(
            ["date", "open", "high", "low", "close", "volume", "tradestatus"],
            [["2026-09-01", "20", "21", "19", "20", "2000", "1"]],
        )

    fake = SimpleNamespace(
        login=lambda: FakeResult([], []),
        logout=lambda: FakeResult([], []),
        query_history_k_data_plus=query_history_k_data_plus,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake)
    cache_path = tmp_path / "hs300.parquet"
    save_cache({"600519": _price_frame(["2026-08-31"], [10.0])}, cache_path)

    result = update_cn_cache(
        ["600519"],
        cache_path=cache_path,
        request_pause=0,
        force_full=True,
        retry_backoff_seconds=0,
    )

    assert len(calls) == 1
    assert calls[0]["start_date"] < "2024-01-01"
    assert result["600519"]["close"].tolist() == [20.0]
