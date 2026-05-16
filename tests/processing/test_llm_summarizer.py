from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

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


def test_process_empty_response_returns_no_content() -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x",
            github_models_base_url="y",
            llm_model="m",
            github_models_min_interval_seconds=0,
        ),
    )
    s = LlmSummarizer(settings)
    mock_client = Mock()
    mock_client.chat.completions.create.return_value = {"choices": []}
    s._client = mock_client
    result = s.process([make_feed_item()])
    assert result == "No high-signal intelligence today."


def test_process_returns_content() -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x",
            github_models_base_url="y",
            llm_model="m",
            github_models_min_interval_seconds=0,
        ),
    )
    s = LlmSummarizer(settings)
    mock_client = Mock()
    # First call: per-item summariser returns a JSON object as string
    per_item_json = (
        '{"title":"t","one_line_summary":"summary","tag":"#AIAgent",'
        '"link":"l","source":"n"}'
    )
    per_item_resp = {"choices": [{"message": {"content": per_item_json}}]}
    # Second call: aggregation returns the final briefing text
    aggregation_resp = {"choices": [{"message": {"content": "Final briefing content"}}]}
    mock_client.chat.completions.create.side_effect = [per_item_resp, aggregation_resp]
    s._client = mock_client
    result = s.process([make_feed_item()])
    assert "Final briefing content" in result


def test_model_called_n_plus_one_times() -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x",
            github_models_base_url="y",
            llm_model="m",
            github_models_min_interval_seconds=0,
        ),
    )
    s = LlmSummarizer(settings)
    mock_client = Mock()
    # per-item response JSON and aggregation response
    per_item_json = (
        '{"title":"t","one_line_summary":"summary","tag":"#AIAgent",'
        '"link":"l","source":"n"}'
    )
    per_item_resp = {"choices": [{"message": {"content": per_item_json}}]}
    aggregation_resp = {"choices": [{"message": {"content": "Final briefing content"}}]}

    n = 3
    # side_effect: n per-item responses, then one aggregation response
    mock_client.chat.completions.create.side_effect = [per_item_resp] * n + [
        aggregation_resp
    ]
    s._client = mock_client

    items = [make_feed_item() for _ in range(n)]
    result = s.process(items)

    # model should be called once per item, plus one aggregation call
    assert mock_client.chat.completions.create.call_count == n + 1
    assert "Final briefing content" in result


def test_model_calls_are_throttled(monkeypatch) -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x",
            github_models_base_url="y",
            llm_model="m",
            github_models_min_interval_seconds=4.5,
        ),
    )
    s = LlmSummarizer(settings)
    mock_client = Mock()
    per_item_json = (
        '{"title":"t","one_line_summary":"summary","tag":"#AIAgent",'
        '"link":"l","source":"n"}'
    )
    per_item_resp = {"choices": [{"message": {"content": per_item_json}}]}
    aggregation_resp = {"choices": [{"message": {"content": "Final briefing content"}}]}
    mock_client.chat.completions.create.side_effect = [per_item_resp, aggregation_resp]
    s._client = mock_client

    current_time = [100.0]
    slept: list[float] = []

    def fake_monotonic() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        current_time[0] += seconds

    monkeypatch.setattr("src.processing.llm_summarizer.time.monotonic", fake_monotonic)
    monkeypatch.setattr("src.processing.llm_summarizer.time.sleep", fake_sleep)

    result = s.process([make_feed_item()])

    assert slept == [4.5]
    assert "Final briefing content" in result
