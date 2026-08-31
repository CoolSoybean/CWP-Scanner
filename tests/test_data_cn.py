from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from data.base import save_cache
from data.data_cn import (
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
