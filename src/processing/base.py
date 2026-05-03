"""Abstract base class for all processing / summarisation strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.ingestion.base import FeedItem


class AbstractProcessor(ABC):  # pylint: disable=too-few-public-methods
    """Interface that every processing strategy must implement."""

    @abstractmethod
    def process(self, items: list[FeedItem]) -> str:
        """Filter and summarise a list of feed items.

        Args:
            items: Raw feed items collected from all sources.

        Returns:
            A formatted briefing string ready for delivery.
        """
