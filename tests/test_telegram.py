from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from notification.telegram import send_telegram


class FakeResponse:
    def __init__(self, error: requests.RequestException | None = None) -> None:
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error


def test_single_chat_id_remains_supported(monkeypatch):
    calls = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setattr(
        "notification.telegram.requests.post",
        lambda *args, **kwargs: calls.append(SimpleNamespace(args=args, kwargs=kwargs))
        or FakeResponse(),
    )

    send_telegram("test message")

    assert [call.kwargs["json"]["chat_id"] for call in calls] == ["123456"]


def test_multiple_chat_ids_are_trimmed_and_deduplicated(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "notification.telegram.requests.post",
        lambda *args, **kwargs: calls.append(SimpleNamespace(args=args, kwargs=kwargs))
        or FakeResponse(),
    )

    send_telegram(
        "test message",
        token="secret-token",
        chat_id=" 123456, -100987654,123456, , -100987654 ",
    )

    assert [call.kwargs["json"]["chat_id"] for call in calls] == [
        "123456",
        "-100987654",
    ]
    assert all(call.kwargs["json"]["text"] == "test message" for call in calls)


def test_missing_credentials_are_rejected(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(RuntimeError, match="are required"):
        send_telegram("test message")


def test_blank_chat_id_list_is_rejected():
    with pytest.raises(RuntimeError, match="at least one chat ID"):
        send_telegram("test message", token="secret-token", chat_id=" , , ")


def test_failure_does_not_stop_remaining_recipients_or_expose_ids(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(SimpleNamespace(args=args, kwargs=kwargs))
        if len(calls) == 1:
            return FakeResponse(requests.HTTPError("403 Forbidden"))
        return FakeResponse()

    monkeypatch.setattr("notification.telegram.requests.post", fake_post)

    with pytest.raises(RuntimeError, match="1 of 2 recipients") as error:
        send_telegram("test message", token="secret-token", chat_id="123456,-100987654")

    assert len(calls) == 2
    assert "123456" not in str(error.value)
    assert "-100987654" not in str(error.value)
