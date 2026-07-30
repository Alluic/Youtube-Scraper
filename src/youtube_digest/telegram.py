from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def _call(self, method: str, values: dict[str, Any]) -> dict[str, Any]:
        body = urllib.parse.urlencode(values).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{method}",
            data=body,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error: {payload}")
        return payload

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe", {}).get("result", {})

    def get_chat(self) -> dict[str, Any]:
        return self._call("getChat", {"chat_id": self.chat_id}).get("result", {})

    def send_message(self, html: str) -> str:
        result = self._call(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": html,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
        ).get("result", {})
        return str(result.get("message_id", ""))
