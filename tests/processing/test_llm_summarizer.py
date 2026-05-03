from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from config.settings import Settings
from src.ingestion.base import FeedItem
from src.processing.llm_summarizer import LlmSummarizer


def make_feed_item() -> FeedItem:
    return FeedItem(
        title="t",
        link="l",
        summary="s",
        published_date="d",
        source_name="n",
    )


def test_process_empty_response_raises() -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x", github_models_base_url="y", llm_model="m"
        ),
    )
    s = LlmSummarizer(settings)
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = {"choices": []}
    s._client = mock_client
    with pytest.raises(RuntimeError):
        s.process([make_feed_item()])


def test_process_returns_content() -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x", github_models_base_url="y", llm_model="m"
        ),
    )
    s = LlmSummarizer(settings)
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = {
        "choices": [{"message": {"content": "結果"}}]
    }
    s._client = mock_client
    result = s.process([make_feed_item()])
    assert "結果" in result
