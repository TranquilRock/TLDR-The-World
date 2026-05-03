"""Global application settings managed via Pydantic BaseSettings.

Environment variables are loaded from the shell environment (or a .env file
during local development).  All fields are validated at startup so
misconfiguration is caught immediately before any network calls are made.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
        validation_alias="GITHUB_MODELS_TOKEN",
    )
    github_models_base_url: str = Field(
        default="https://models.inference.ai.azure.com",
        description="Base URL for GitHub Models (OpenAI-compatible) endpoint.",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier to use for summarisation.",
    )
    rss_max_items_per_source: int = Field(
        default=8,
        ge=1,
        description="Maximum RSS items to keep per source before LLM processing.",
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

    try:
        with sources_path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to read sources.json at %s: %s", sources_path, exc)
        return []

    raw_feeds = data.get("rss_feeds", [])
    valid_feeds: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw_feeds):
        if not isinstance(entry, dict):
            logger.warning("sources.json: entry %d is not an object, skipping", idx)
            continue
        name = entry.get("name")
        url = entry.get("url")
        if not name or not url or not isinstance(name, str) or not isinstance(url, str):
            logger.warning(
                "sources.json: entry %d missing or invalid 'name'/'url', skipping", idx
            )
            continue
        valid_feeds.append({"name": name, "url": url})

    return valid_feeds


_SETTINGS_INSTANCE: Settings | None = None


def get_settings() -> Settings:
    """Return the application settings singleton, creating it on first call.

    Using a factory function instead of a module-level instantiation prevents
    Pydantic from raising validation errors during import when environment
    variables are not yet set (e.g., in unit tests or static analysis).
    """
    global _SETTINGS_INSTANCE  # pylint: disable=global-statement
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = Settings()  # type: ignore[call-arg]
    return _SETTINGS_INSTANCE
