"""Abstract base class for all delivery / notification channels."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractNotifier(ABC):
    """Interface that every delivery channel must implement."""

    @abstractmethod
    def send(self, message: str) -> None:
        """Deliver *message* to the target channel.

        Args:
            message: The formatted briefing text to be delivered.
        """
