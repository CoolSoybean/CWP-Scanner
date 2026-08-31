from __future__ import annotations

import os

import pandas as pd
import pytest
import requests

from data.data_us import get_sp500_constituents


class FakeResponse:
    def __init__(self, html: str) -> None:
        self.html = html

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"parse": {"text": self.html}}


def test_get_sp500_constituents_uses_mediawiki_api(monkeypatch, tmp_path):
    html = pd.DataFrame(
        {
            "Symbol": ["BRK.B", "AAPL"],
            "Security": ["Berkshire Hathaway", "Apple"],
            "GICS Sector": ["Financials", "Information Technology"],
            "GICS Sub-Industry": ["Multi-Sector Holdings", "Technology Hardware"],
        }
    ).to_html(index=False)
    request_args = {}

    def fake_get(url, **kwargs):
        request_args["url"] = url
        request_args.update(kwargs)
        return FakeResponse(html)

    monkeypatch.setattr("data.data_us.requests.get", fake_get)
    cache_path = tmp_path / "sp500.csv"

    result = get_sp500_constituents(cache_path=cache_path)

    assert result["symbol"].tolist() == ["BRK-B", "AAPL"]
    assert request_args["params"]["action"] == "parse"
    assert request_args["headers"]["User-Agent"].startswith("CWP-Scanner/")
    assert cache_path.exists()


def test_get_sp500_constituents_falls_back_to_stale_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "sp500.csv"
    expected = pd.DataFrame(
        [{"symbol": "AAPL", "name": "Apple", "sector": "Tech", "sub_industry": "Hardware"}]
    )
    expected.to_csv(cache_path, index=False)
    old_timestamp = cache_path.stat().st_mtime - 8 * 24 * 60 * 60
    os.utime(cache_path, (old_timestamp, old_timestamp))

    def fail_get(*args, **kwargs):
        raise requests.HTTPError("403 Forbidden")

    monkeypatch.setattr("data.data_us.requests.get", fail_get)

    result = get_sp500_constituents(cache_path=cache_path)

    pd.testing.assert_frame_equal(result, expected)


def test_get_sp500_constituents_fails_without_cache(monkeypatch, tmp_path):
    def fail_get(*args, **kwargs):
        raise requests.HTTPError("403 Forbidden")

    monkeypatch.setattr("data.data_us.requests.get", fail_get)

    with pytest.raises(RuntimeError, match="no cached constituent file"):
        get_sp500_constituents(cache_path=tmp_path / "missing.csv")
