from __future__ import annotations

import getpass
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_DIR_NAME = "YoutubeFinanceDigest"
KEYRING_SERVICE = "YoutubeFinanceDigest"
KEYRING_TELEGRAM_USER = "telegram_bot_token"


def app_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME
    return Path.home() / "AppData" / "Local" / APP_DIR_NAME


@dataclass(slots=True)
class AppConfig:
    data_dir: Path = field(default_factory=app_dir)
    oauth_client_path: Path | None = None
    oauth_token_path: Path | None = None
    telegram_chat_id: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:12b"
    timezone: str = "America/New_York"
    digest_time: str = "07:30"
    language: str = "en"
    whisper_model: str = "medium.en"
    transcript_retention_days: int = 30
    include_confidence: float = 0.70
    exclude_confidence: float = 0.85
    max_attempts: int = 3
    include_channels: tuple[str, ...] = ()
    exclude_channels: tuple[str, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.oauth_client_path = (
            Path(self.oauth_client_path).expanduser().resolve()
            if self.oauth_client_path
            else self.data_dir / "client_secret.json"
        )
        self.oauth_token_path = (
            Path(self.oauth_token_path).expanduser().resolve()
            if self.oauth_token_path
            else self.data_dir / "oauth_token.json"
        )

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.toml"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "digest.db"

    @property
    def transcript_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.transcript_dir,
            self.log_dir,
            self.temp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(item) for item in value)


def load_config(path: Path | None = None) -> AppConfig:
    expected = path or app_dir() / "config.toml"
    if not expected.exists():
        raise FileNotFoundError(
            f"Configuration not found at {expected}. Run `youtube-digest configure`."
        )
    with expected.open("rb") as handle:
        raw = tomllib.load(handle)
    app = raw.get("app", {})
    filters = raw.get("filters", {})
    config = AppConfig(
        data_dir=Path(app.get("data_dir", expected.parent)),
        oauth_client_path=app.get("oauth_client_path"),
        oauth_token_path=app.get("oauth_token_path"),
        telegram_chat_id=str(app.get("telegram_chat_id", "")),
        ollama_url=str(app.get("ollama_url", "http://127.0.0.1:11434")).rstrip("/"),
        ollama_model=str(app.get("ollama_model", "gemma4:12b")),
        timezone=str(app.get("timezone", "America/New_York")),
        digest_time=str(app.get("digest_time", "07:30")),
        language=str(app.get("language", "en")),
        whisper_model=str(app.get("whisper_model", "medium.en")),
        transcript_retention_days=int(app.get("transcript_retention_days", 30)),
        include_confidence=float(app.get("include_confidence", 0.70)),
        exclude_confidence=float(app.get("exclude_confidence", 0.85)),
        max_attempts=int(app.get("max_attempts", 3)),
        include_channels=_as_tuple(filters.get("include_channels")),
        exclude_channels=_as_tuple(filters.get("exclude_channels")),
        include_keywords=_as_tuple(filters.get("include_keywords")),
        exclude_keywords=_as_tuple(filters.get("exclude_keywords")),
    )
    config.ensure_directories()
    return config


def _toml_string(value: str | Path) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def write_config(config: AppConfig) -> Path:
    config.ensure_directories()
    content = "\n".join(
        [
            "[app]",
            f"data_dir = {_toml_string(config.data_dir)}",
            f"oauth_client_path = {_toml_string(config.oauth_client_path)}",
            f"oauth_token_path = {_toml_string(config.oauth_token_path)}",
            f"telegram_chat_id = {_toml_string(config.telegram_chat_id)}",
            f"ollama_url = {_toml_string(config.ollama_url)}",
            f"ollama_model = {_toml_string(config.ollama_model)}",
            f"timezone = {_toml_string(config.timezone)}",
            f"digest_time = {_toml_string(config.digest_time)}",
            f"language = {_toml_string(config.language)}",
            f"whisper_model = {_toml_string(config.whisper_model)}",
            f"transcript_retention_days = {config.transcript_retention_days}",
            f"include_confidence = {config.include_confidence}",
            f"exclude_confidence = {config.exclude_confidence}",
            f"max_attempts = {config.max_attempts}",
            "",
            "[filters]",
            f"include_channels = {_toml_array(config.include_channels)}",
            f"exclude_channels = {_toml_array(config.exclude_channels)}",
            f"include_keywords = {_toml_array(config.include_keywords)}",
            f"exclude_keywords = {_toml_array(config.exclude_keywords)}",
            "",
        ]
    )
    config.config_path.write_text(content, encoding="utf-8")
    return config.config_path


def set_telegram_token(token: str) -> None:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - installation guard
        raise RuntimeError("Install project dependencies before configuring keyring.") from exc
    keyring.set_password(KEYRING_SERVICE, KEYRING_TELEGRAM_USER, token)


def get_telegram_token() -> str:
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - installation guard
        raise RuntimeError("The `keyring` package is not installed.") from exc
    token = keyring.get_password(KEYRING_SERVICE, KEYRING_TELEGRAM_USER)
    if not token:
        raise RuntimeError("Telegram token is absent from Windows Credential Manager.")
    return token


def interactive_configure() -> Path:
    target_dir = app_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    current_path = target_dir / "config.toml"
    current = load_config(current_path) if current_path.exists() else AppConfig(data_dir=target_dir)

    oauth_input = input(
        f"Google OAuth client JSON [{current.oauth_client_path}]: "
    ).strip()
    oauth_source = (
        Path(oauth_input).expanduser().resolve()
        if oauth_input
        else current.oauth_client_path
    )
    if not oauth_source or not oauth_source.exists():
        raise FileNotFoundError(f"OAuth client JSON not found: {oauth_source}")
    oauth_target = target_dir / "client_secret.json"
    if oauth_source != oauth_target:
        shutil.copy2(oauth_source, oauth_target)

    chat_id = input(f"Telegram chat ID [{current.telegram_chat_id}]: ").strip()
    current.telegram_chat_id = chat_id or current.telegram_chat_id
    if not current.telegram_chat_id:
        raise ValueError("Telegram chat ID is required.")

    token = getpass.getpass("Telegram bot token (leave blank to keep existing): ").strip()
    if token:
        set_telegram_token(token)
    else:
        get_telegram_token()

    current.data_dir = target_dir
    current.oauth_client_path = oauth_target
    current.oauth_token_path = target_dir / "oauth_token.json"
    return write_config(current)
