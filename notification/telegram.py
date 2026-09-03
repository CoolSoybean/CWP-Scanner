from __future__ import annotations

import os

import requests


def _parse_chat_ids(value: str) -> list[str]:
    chat_ids: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        chat_id = item.strip()
        if chat_id and chat_id not in seen:
            seen.add(chat_id)
            chat_ids.append(chat_id)
    return chat_ids


def send_telegram(message: str, token: str | None = None, chat_id: str | None = None) -> None:
    bot_token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id_value = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id_value:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    target_chats = _parse_chat_ids(chat_id_value)
    if not target_chats:
        raise RuntimeError("TELEGRAM_CHAT_ID must contain at least one chat ID")

    failures: list[requests.RequestException] = []
    for target_chat in target_chats:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": target_chat,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            failures.append(exc)

    if failures:
        raise RuntimeError(
            f"Telegram delivery failed for {len(failures)} of {len(target_chats)} recipients"
        ) from failures[0]
