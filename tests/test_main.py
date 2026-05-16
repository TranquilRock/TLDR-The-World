"""End-to-end tests for the main pipeline orchestration."""

# pylint: disable=duplicate-code

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from config.settings import Settings
from src.main import fetch_all_feeds, run_pipeline


def make_mock_entry(
    title: str = "test",
    link: str = "http://example.com",
    published_parsed=None,
):
    """Create a mock feedparser entry."""
    entry = Mock()
    entry.title = title
    entry.link = link
    entry.summary = "summary"
    entry.published = "2026-05-16"
    entry.updated = None
    # If no published_parsed provided, use current time
    if published_parsed is None:
        now = datetime.now(tz=timezone.utc)
        published_parsed = now.timetuple()
    entry.published_parsed = published_parsed
    return entry


def test_fetch_all_feeds_respects_age_filter() -> None:
    """fetch_all_feeds should apply age filtering when max_age_hours is set."""
    now = datetime.now(tz=timezone.utc)

    # Recent entry (1 hour old)
    recent_time = (now - timedelta(hours=1)).timetuple()
    recent_entry = make_mock_entry(title="Recent", published_parsed=recent_time)

    # Old entry (48 hours old)
    old_time = (now - timedelta(hours=48)).timetuple()
    old_entry = make_mock_entry(title="Old", published_parsed=old_time)

    mock_parsed = Mock()
    mock_parsed.entries = [recent_entry, old_entry]

    sources = [{"name": "TestFeed", "url": "http://example.com"}]

    with patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=mock_parsed):
        # With 24-hour age limit
        items = fetch_all_feeds(sources, max_items_per_source=8, max_age_hours=24.0)

    # Should only have the recent entry
    assert len(items) == 1
    assert items[0]["title"] == "Recent"


def test_fetch_all_feeds_disables_age_filter_when_zero() -> None:
    """When max_age_hours is 0, all items should be kept."""
    now = datetime.now(tz=timezone.utc)
    old_time = (now - timedelta(days=100)).timetuple()
    old_entry = make_mock_entry(title="VeryOld", published_parsed=old_time)

    mock_parsed = Mock()
    mock_parsed.entries = [old_entry]

    sources = [{"name": "TestFeed", "url": "http://example.com"}]

    with patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=mock_parsed):
        items = fetch_all_feeds(sources, max_items_per_source=8, max_age_hours=0.0)

    assert len(items) == 1
    assert items[0]["title"] == "VeryOld"


def test_run_pipeline_end_to_end(monkeypatch) -> None:
    """Test the full pipeline with all components mocked."""
    # Mock settings
    settings = cast(
        Settings,
        SimpleNamespace(
            github_models_token="x",
            github_models_base_url="y",
            llm_model="m",
            github_models_min_interval_seconds=0,
            rss_max_items_per_source=8,
            rss_max_age_hours=48.0,
            telegram_bot_token="bot",
            telegram_chat_id="chat",
        ),
    )

    # Mock RSS feed data
    mock_entry = make_mock_entry(title="TestArticle", link="http://example.com")
    mock_parsed = Mock()
    mock_parsed.entries = [mock_entry]

    # Track calls
    calls = {"requests_get": 0, "model_calls": 0, "telegram_post": 0}

    def mock_requests_get(url, timeout, headers):
        # reference parameters to avoid 'unused argument' warnings
        _ = (url, timeout, headers)
        calls["requests_get"] += 1
        resp = Mock()
        resp.content = b"dummy"
        resp.raise_for_status = Mock()
        return resp

    def mock_feedparser_parse(content):
        _ = content
        return mock_parsed

    def mock_model_create(**kwargs):
        _ = kwargs
        calls["model_calls"] += 1
        if calls["model_calls"] == 1:
            # per-item summarisation
            json_str = (
                '{"title":"Test","one_line_summary":"Summary",'
                '"tag":"#AIAgent","link":"http://example.com","source":"TestFeed"}'
            )
            return {"choices": [{"message": {"content": json_str}}]}
        # aggregation
        return {"choices": [{"message": {"content": "Daily Briefing"}}]}

    def mock_telegram_post(url, json, timeout):
        _ = (url, json, timeout)
        calls["telegram_post"] += 1
        resp = Mock()
        resp.raise_for_status = Mock()
        return resp

    # Mock at the src.main import level
    monkeypatch.setattr("src.main.get_settings", lambda: settings)
    monkeypatch.setattr(
        "src.main.load_sources",
        lambda: [{"name": "TestFeed", "url": "http://example.com"}],
    )
    monkeypatch.setattr("src.ingestion.rss_fetcher.requests.get", mock_requests_get)
    monkeypatch.setattr(
        "src.ingestion.rss_fetcher.feedparser.parse", mock_feedparser_parse
    )

    # Mock LLM client
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = mock_model_create

    def mock_openai_init(**kwargs):
        _ = kwargs
        return mock_client

    monkeypatch.setattr("src.processing.llm_summarizer.OpenAI", mock_openai_init)
    monkeypatch.setattr(
        "src.delivery.telegram_notifier.requests.post", mock_telegram_post
    )

    # Run the pipeline
    run_pipeline()

    # Verify all components were called
    assert calls["requests_get"] == 1, "RSS feed should be fetched"
    assert calls["model_calls"] == 2, "Model should be called twice"
    assert calls["telegram_post"] >= 1, "Telegram message should be sent"
