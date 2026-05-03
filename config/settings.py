"""Global application settings managed via Pydantic BaseSettings.

Environment variables are loaded from the shell environment (or a .env file
during local development).  All fields are validated at startup so
misconfiguration is caught immediately before any network calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    github_models_token: str = Field(
        ...,
        description="Personal access token for GitHub Models API.",
    )
    github_models_base_url: str = Field(
        default="https://models.inference.ai.azure.com",
        description="Base URL for GitHub Models (OpenAI-compatible) endpoint.",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier to use for summarisation.",
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(
        ...,
        description="Telegram bot token obtained from @BotFather.",
    )
    telegram_chat_id: str = Field(
        ...,
        description="Telegram chat / channel ID to deliver the briefing to.",
    )

    @field_validator("github_models_token", "telegram_bot_token", "telegram_chat_id")
    @classmethod
    def _must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Value must not be empty or whitespace-only.")
        return v


def load_sources(sources_path: Path | None = None) -> list[dict[str, Any]]:
    """Load RSS feed source definitions from *sources.json*.

    Args:
        sources_path: Explicit path to the JSON file.  Defaults to
            ``<repo_root>/config/sources.json`` resolved relative to this
            module's location.

    Returns:
        A list of feed dictionaries, each containing at minimum ``name`` and
        ``url`` keys.
    """
    if sources_path is None:
        sources_path = Path(__file__).parent / "sources.json"

    with sources_path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    return data.get("rss_feeds", [])


_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Return the application settings singleton, creating it on first call.

    Using a factory function instead of a module-level instantiation prevents
    Pydantic from raising validation errors during import when environment
    variables are not yet set (e.g., in unit tests or static analysis).
    """
    global _settings_instance  # noqa: PLW0603
    if _settings_instance is None:
        _settings_instance = Settings()  # type: ignore[call-arg]
    return _settings_instance
