"""Telegram delivery channel – concrete implementation of :class:`AbstractNotifier`.

Sends the daily briefing as one or more Telegram messages using the Bot API.
Long messages (> 4096 characters) are automatically split into chunks.

Telegram MarkdownV2 requires many punctuation characters to be escaped with a
leading backslash.  The :func:`escape_markdown_v2` helper handles this so that
messages render correctly without throwing API errors.
"""

from __future__ import annotations

import logging

import requests

from src.delivery.base import AbstractNotifier

logger = logging.getLogger(__name__)

# Telegram MarkdownV2 characters that must be escaped.
MARKDOWN_V2_SPECIAL_CHARS: str = r"_*[]()~`>#+-=|{}.!"

# Telegram message length limit (characters).
MAX_MESSAGE_LENGTH: int = 4096

TELEGRAM_API_TIMEOUT: int = 30  # seconds


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 parse mode.

    All characters listed in ``_MARKDOWN_V2_SPECIAL_CHARS`` are prefixed with
    a backslash so Telegram's parser treats them as literal characters rather
    than formatting markers.

    Args:
        text: Raw text that may contain Telegram MarkdownV2 special characters.

    Returns:
        Escaped text safe to send with ``parse_mode="MarkdownV2"``.
    """
    for char in MARKDOWN_V2_SPECIAL_CHARS:
        text = text.replace(char, f"\\{char}")
    return text


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split *text* into chunks no longer than *max_length* characters.

    Splits are made on newline boundaries where possible to avoid breaking
    mid-sentence.

    Args:
        text: The full message text.
        max_length: Maximum characters per chunk.

    Returns:
        A list of string chunks, each at most *max_length* characters long.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_length: int = 0

    for line in text.splitlines(keepends=True):
        if current_length + len(line) > max_length:
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_length = 0
            # If a single line exceeds max_length, hard-split it.
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
        current_chunk.append(line)
        current_length += len(line)

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


class TelegramNotifier(AbstractNotifier):
    """Send messages to a Telegram chat via the Bot HTTP API.

    Args:
        bot_token: Telegram bot token obtained from @BotFather.
        chat_id:   Target chat or channel ID.
        parse_mode: Telegram message parse mode.  Defaults to ``"MarkdownV2"``.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        parse_mode: str = "MarkdownV2",
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._parse_mode = parse_mode
        self._api_base = f"https://api.telegram.org/bot{bot_token}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send(self, message: str) -> None:
        """Deliver *message* to the configured Telegram chat.

        The message is escaped for MarkdownV2 and split into chunks if it
        exceeds Telegram's 4096-character limit.

        Args:
            message: The formatted briefing text.
        """
        escaped = escape_markdown_v2(message)
        chunks = split_message(escaped)

        logger.info(
            "Sending %d message chunk(s) to Telegram chat %s.",
            len(chunks),
            self._chat_id,
        )

        for index, chunk in enumerate(chunks, start=1):
            self._send_chunk(chunk, part=index, total=len(chunks))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send_chunk(self, text: str, *, part: int, total: int) -> None:
        """Send a single chunk to Telegram, retrying once on failure."""
        url = f"{self._api_base}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(url, json=payload, timeout=TELEGRAM_API_TIMEOUT)
            response.raise_for_status()
            logger.info("Sent chunk %d/%d successfully.", part, total)
        except requests.HTTPError as exc:
            logger.error(
                "Telegram API error sending chunk %d/%d: %s – response: %s",
                part,
                total,
                exc,
                exc.response.text if exc.response is not None else "N/A",
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error sending chunk %d/%d to Telegram: %s",
                part,
                total,
                exc,
            )
            raise
