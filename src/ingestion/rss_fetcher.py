"""RSS feed fetcher - concrete implementation of :class:`AbstractSource`."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests

from src.ingestion.base import AbstractSource, FeedItem

logger = logging.getLogger(__name__)

# Conservative defaults to avoid hammering servers or hanging the pipeline.
REQUEST_TIMEOUT: int = 15  # seconds


class RssFetcher(AbstractSource):  # pylint: disable=too-few-public-methods
    """Fetch and normalise entries from a single RSS / Atom feed URL.

    Args:
        name: Human-readable label for the feed (used in logging and as
              ``source_name`` on each :class:`FeedItem`).
        url:  Full URL of the RSS / Atom feed.
        max_items: Maximum number of items to return per fetch.  Defaults to
               8 to keep LLM prompt sizes manageable.
    """

    def __init__(
        self, name: str, url: str, max_items: int = 8, max_age_hours: float = 48.0
    ) -> None:
        self.name = name
        self.url = url
        self.max_items = max_items
        self.max_age_hours = max(0.0, max_age_hours)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch(self) -> list[FeedItem]:
        """Fetch and return up to *max_items* entries from the feed.

        On any network or parse error the method logs a warning and returns an
        empty list so the rest of the pipeline continues unaffected.
        """
        logger.info("Fetching RSS feed: %s (%s)", self.name, self.url)
        try:
            raw_content = self._download_feed()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Failed to download feed '%s' from %s: %s",
                self.name,
                self.url,
                exc,
            )
            return []

        try:
            return self._parse_feed(raw_content)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Failed to parse feed '%s': %s",
                self.name,
                exc,
            )
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _download_feed(self) -> bytes:
        """Download the raw feed bytes via *requests* (respects timeout)."""
        response = requests.get(
            self.url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "TLDR-The-World/1.0 (RSS Pipeline)"},
        )
        response.raise_for_status()
        return response.content

    def _parse_feed(self, raw_content: bytes) -> list[FeedItem]:
        """Parse *raw_content* with feedparser and normalise into FeedItems.

        Items older than *max_age_hours* are discarded.
        """
        parsed = feedparser.parse(raw_content)

        items: list[FeedItem] = []
        for entry in parsed.entries[: self.max_items]:
            # Skip items that are too old.
            if self.max_age_hours > 0 and self._is_entry_too_old(entry):
                logger.debug(
                    "Feed '%s': skipping entry older than %d hours: %s",
                    self.name,
                    self.max_age_hours,
                    getattr(entry, "title", "<no title>"),
                )
                continue
            items.append(self._normalise_entry(entry))

        logger.info("Feed '%s': fetched %d item(s).", self.name, len(items))
        return items

    def _is_entry_too_old(self, entry: Any) -> bool:
        """Check if *entry* is older than *max_age_hours*."""
        if self.max_age_hours <= 0:
            return False

        # Try to extract parsed time from feedparser's result.
        struct_time = getattr(entry, "published_parsed", None) or getattr(
            entry, "updated_parsed", None
        )

        if struct_time is None:
            # No time info; assume it's recent.
            return False

        try:
            entry_dt = datetime.fromtimestamp(time.mktime(struct_time), tz=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            age = now - entry_dt
            max_age = timedelta(hours=self.max_age_hours)
            return age > max_age
        except (ValueError, OSError, OverflowError):
            # If we can't parse, assume it's recent.
            return False

    def _normalise_entry(self, entry: Any) -> FeedItem:
        """Convert a feedparser entry object into a :class:`FeedItem`."""
        title: str = getattr(entry, "title", "") or ""
        link: str = getattr(entry, "link", "") or ""

        # feedparser exposes several possible summary fields.
        summary: str = (
            getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        )

        # Prefer a pre-formatted date string; fall back to an empty string.
        published_date: str = (
            getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
        )

        return FeedItem(
            title=title.strip(),
            link=link.strip(),
            summary=summary.strip(),
            published_date=published_date.strip(),
            source_name=self.name,
        )
