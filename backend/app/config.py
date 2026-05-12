"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the chat backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    fireworks_api_key: str = Field(default="", alias="FIREWORKS_API_KEY")
    fireworks_base_url: str = Field(
        default="https://api.fireworks.ai/inference/v1",
        alias="FIREWORKS_BASE_URL",
    )

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    data_dir: str = Field(default="./data", alias="DATA_DIR")

    allowed_origins: str = Field(default="*", alias="ALLOWED_ORIGINS")

    static_dir: str = Field(default="./static", alias="STATIC_DIR")

    request_timeout_seconds: float = Field(default=120.0, alias="REQUEST_TIMEOUT_SECONDS")

    # --- freetheai.xyz provider ---
    freetheai_api_key: str = Field(default="", alias="FREETHEAI_API_KEY")
    freetheai_base_url: str = Field(
        default="https://api.freetheai.xyz/v1",
        alias="FREETHEAI_BASE_URL",
    )
    freetheai_min_interval_seconds: float = Field(
        default=6.5, alias="FREETHEAI_MIN_INTERVAL_SECONDS",
    )

    # --- Telegram bot ---
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    # --- Gemini AI Studio (key rotation proxy) ---
    # Comma-separated list of API keys, optionally with project names:
    # "key1:project1,key2:project2,key3:project3"
    # or just "key1,key2,key3" (auto-named project_1, project_2, etc.)
    gemini_api_keys: str = Field(default="", alias="GEMINI_API_KEYS")

    def gemini_api_keys_parsed(self) -> list[tuple[str, str]]:
        """Parse GEMINI_API_KEYS into list of (key, project_name) tuples."""
        raw = self.gemini_api_keys.strip()
        if not raw:
            return []
        keys: list[tuple[str, str]] = []
        for i, part in enumerate(raw.split(","), 1):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                key, name = part.split(":", 1)
                keys.append((key.strip(), name.strip()))
            else:
                keys.append((part, f"project_{i}"))
        return keys

    # --- web-search providers ---
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    serper_api_key: str = Field(default="", alias="SERPER_API_KEY")
    firecrawl_api_key: str = Field(default="", alias="FIRECRAWL_API_KEY")

    def resolve_database_url(self) -> str:
        """Return a SQLAlchemy async URL, defaulting to a SQLite file in ``data_dir``."""

        if self.database_url:
            return self.database_url
        path = Path(self.data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path / 'chat.db'}"

    def cors_origins(self) -> list[str]:
        raw = self.allowed_origins.strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
