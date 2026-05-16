"""Tests for RSS feed fetcher, including age-based filtering."""

# pylint: disable=duplicate-code

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from src.ingestion.rss_fetcher import RssFetcher


def make_mock_entry(
    title: str = "test",
    link: str = "http://example.com",
    published_parsed=None,
    updated_parsed=None,
):
    """Create a mock feedparser entry."""
    entry = Mock()
    entry.title = title
    entry.link = link
    entry.summary = "summary"
    entry.published = "2026-05-16"
    entry.updated = None
    entry.published_parsed = published_parsed
    entry.updated_parsed = updated_parsed
    return entry


def test_fetcher_discards_old_entries() -> None:
    """Entries older than max_age_hours should be filtered out."""
    fetcher = RssFetcher(name="test", url="http://example.com", max_age_hours=24.0)

    now = datetime.now(tz=timezone.utc)

    # Recent entry (1 hour old)
    recent_time = (now - timedelta(hours=1)).timetuple()
    recent_entry = make_mock_entry(
        title="Recent",
        published_parsed=recent_time,
    )

    # Old entry (48 hours old)
    old_time = (now - timedelta(hours=48)).timetuple()
    old_entry = make_mock_entry(
        title="Old",
        published_parsed=old_time,
    )

    mock_parsed = Mock()
    mock_parsed.entries = [recent_entry, old_entry]

    with patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=mock_parsed):
        result = fetcher._parse_feed(b"dummy")

    # Should only have the recent entry
    assert len(result) == 1
    assert result[0]["title"] == "Recent"


def test_fetcher_keeps_entries_without_time_info() -> None:
    """Entries without time info should be kept (assume recent)."""
    fetcher = RssFetcher(name="test", url="http://example.com", max_age_hours=24.0)

    entry_no_time = make_mock_entry(
        title="NoTime",
        published_parsed=None,
        updated_parsed=None,
    )

    mock_parsed = Mock()
    mock_parsed.entries = [entry_no_time]

    with patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=mock_parsed):
        result = fetcher._parse_feed(b"dummy")

    assert len(result) == 1
    assert result[0]["title"] == "NoTime"


def test_fetcher_respects_zero_max_age() -> None:
    """When max_age_hours is 0, all entries should be kept."""
    fetcher = RssFetcher(name="test", url="http://example.com", max_age_hours=0.0)

    now = datetime.now(tz=timezone.utc)
    old_time = (now - timedelta(days=100)).timetuple()
    old_entry = make_mock_entry(
        title="VeryOld",
        published_parsed=old_time,
    )

    mock_parsed = Mock()
    mock_parsed.entries = [old_entry]

    with patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=mock_parsed):
        result = fetcher._parse_feed(b"dummy")

    # Should keep the entry (age filtering disabled)
    assert len(result) == 1
    assert result[0]["title"] == "VeryOld"


def test_fetcher_uses_updated_parsed_if_no_published() -> None:
    """Should use updated_parsed if published_parsed is not available."""
    fetcher = RssFetcher(name="test", url="http://example.com", max_age_hours=24.0)

    now = datetime.now(tz=timezone.utc)
    recent_time = (now - timedelta(hours=1)).timetuple()

    entry = make_mock_entry(
        title="UpdatedOnly",
        published_parsed=None,
        updated_parsed=recent_time,
    )

    mock_parsed = Mock()
    mock_parsed.entries = [entry]

    with patch("src.ingestion.rss_fetcher.feedparser.parse", return_value=mock_parsed):
        result = fetcher._parse_feed(b"dummy")

    assert len(result) == 1
    assert result[0]["title"] == "UpdatedOnly"
