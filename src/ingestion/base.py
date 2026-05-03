"""Abstract base class for all data-ingestion sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class FeedItem(TypedDict):
    """Standardised representation of a single feed entry."""

    title: str
    link: str
    summary: str
    published_date: str
    source_name: str


class AbstractSource(ABC):
    """Interface that every ingestion source must implement."""

    @abstractmethod
    def fetch(self) -> list[FeedItem]:
        """Fetch items from the underlying source.

        Returns:
            A (possibly empty) list of :class:`FeedItem` dicts.  Implementations
            must NOT raise exceptions for transient network errors; instead they
            should log the error and return an empty list.
        """
