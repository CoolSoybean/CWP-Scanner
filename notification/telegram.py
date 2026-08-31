from __future__ import annotations

import os

def send_telegram(message: str, token: str | None = None, chat_id: str | None = None) -> None:
    import requests

    bot_token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not target_chat:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": target_chat, "text": message, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
