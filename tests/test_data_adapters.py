from __future__ import annotations

import pandas as pd
import pytest
import requests

from data import data_cn, data_us


SP500_HTML = """
<table id="constituents">
  <thead><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th></tr></thead>
  <tbody><tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector Holdings</td></tr></tbody>
</table>
"""


class _Response:
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text = text
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error


def test_sp500_download_uses_identified_request(monkeypatch, tmp_path):
    observed: dict = {}

    def fake_get(url, *, headers, timeout):
        observed.update(url=url, headers=headers, timeout=timeout)
        return _Response(SP500_HTML)

    monkeypatch.setattr(data_us.requests, "get", fake_get)
    result = data_us.get_sp500_constituents(
        force_refresh=True,
        cache_path=tmp_path / "sp500.csv",
    )

    assert result.iloc[0]["symbol"] == "BRK-B"
    assert "CWP-Scanner" in observed["headers"]["User-Agent"]
    assert observed["timeout"] == 30


def test_sp500_refresh_failure_uses_stale_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "sp500.csv"
    expected = pd.DataFrame(
        [{"symbol": "AAPL", "name": "Apple", "sector": "IT", "sub_industry": "Hardware"}]
    )
    expected.to_csv(cache_path, index=False, encoding=data_us.CSV_ENCODING)

    def fake_get(*args, **kwargs):
        return _Response(error=requests.HTTPError("403 Forbidden"))

    monkeypatch.setattr(data_us.requests, "get", fake_get)
    result = data_us.get_sp500_constituents(force_refresh=True, cache_path=cache_path)

    pd.testing.assert_frame_equal(result, expected)


def test_hs300_all_downloads_failed_raise_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        data_cn,
        "fetch_cn_daily",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.ConnectionError("blocked")),
    )
    monkeypatch.setattr(data_cn, "fetch_cn_daily_yahoo", lambda *args, **kwargs: {})

    with pytest.raises(RuntimeError, match="no usable HS300 market data"):
        data_cn.update_cn_cache(
            ["000001", "000002"],
            cache_path=tmp_path / "hs300.parquet",
            request_pause=0,
        )


def test_hs300_uses_batch_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(data_cn, "fetch_cn_daily", lambda *args, **kwargs: pd.DataFrame())
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    fallback = pd.DataFrame(
        {
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1000.0,
        },
        index=dates,
    )
    monkeypatch.setattr(
        data_cn,
        "fetch_cn_daily_yahoo",
        lambda symbols, **kwargs: {symbol: fallback for symbol in symbols},
    )

    result = data_cn.update_cn_cache(
        ["000001", "600000"],
        cache_path=tmp_path / "hs300.parquet",
        request_pause=0,
    )

    assert set(result) == {"000001", "600000"}
    assert len(result["000001"]) == 200
    assert data_cn.to_yahoo_cn_symbol("000001") == "000001.SZ"
    assert data_cn.to_yahoo_cn_symbol("600000") == "600000.SS"
