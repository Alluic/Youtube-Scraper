from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from youtube_digest.config import AppConfig, get_telegram_token
from youtube_digest.ollama_client import OllamaClient
from youtube_digest.telegram import TelegramClient
from youtube_digest.youtube import build_youtube_service


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def run_checks(config: AppConfig, logger: Any) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            "OAuth client",
            config.oauth_client_path.exists(),
            str(config.oauth_client_path),
        )
    )
    results.append(
        CheckResult(
            "OAuth token",
            config.oauth_token_path.exists(),
            str(config.oauth_token_path),
        )
    )

    ollama = OllamaClient(config.ollama_url, config.ollama_model, logger)
    try:
        ollama.ensure_running()
        response = ollama._request(  # noqa: SLF001 - health diagnostic
            "POST", "/api/show", {"model": config.ollama_model}, timeout=30
        )
        details = response.get("details", {})
        results.append(
            CheckResult(
                "Ollama",
                True,
                f"{config.ollama_model} {details.get('parameter_size', '')} "
                f"{details.get('quantization_level', '')}".strip(),
            )
        )
    except Exception as exc:
        results.append(CheckResult("Ollama", False, str(exc)))

    try:
        service = build_youtube_service(config.oauth_token_path)
        response = (
            service.subscriptions()
            .list(part="id", mine=True, maxResults=1)
            .execute()
        )
        total = response.get("pageInfo", {}).get("totalResults", "?")
        results.append(
            CheckResult(
                "YouTube API",
                True,
                f"Authenticated; total subscriptions: {total}",
            )
        )
    except Exception as exc:
        results.append(CheckResult("YouTube API", False, str(exc)))

    try:
        telegram = TelegramClient(get_telegram_token(), config.telegram_chat_id)
        bot = telegram.get_me()
        chat = telegram.get_chat()
        results.append(
            CheckResult(
                "Telegram",
                True,
                f"bot @{bot.get('username', '?')} → chat {chat.get('id', config.telegram_chat_id)}",
            )
        )
    except Exception as exc:
        results.append(CheckResult("Telegram", False, str(exc)))

    return results
