"""Telegram delivery channel - concrete implementation of :class:`AbstractNotifier`.

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
    """Split *text* into chunks that remain valid after MarkdownV2 escaping.

    We build chunks from the original (unescaped) text by joining lines until
    escaping the tentative chunk would exceed *max_length*. If a single line
    after escaping is still too long, we hard-split the escaped line while
    ensuring no chunk ends with a dangling backslash (which would break
    MarkdownV2 parsing).
    """
    # Fast-path: whole message fits after escaping
    full_escaped = escape_markdown_v2(text)
    if len(full_escaped) <= max_length:
        return [full_escaped]

    chunks: list[str] = []
    current_lines: list[str] = []

    def _flush_current() -> None:
        if not current_lines:
            return
        escaped: str = escape_markdown_v2("".join(current_lines))
        chunks.append(escaped)
        current_lines.clear()

    for line in text.splitlines(keepends=True):
        tentative = "".join(current_lines) + line
        if len(escape_markdown_v2(tentative)) <= max_length:
            current_lines.append(line)
            continue

        # Tentative chunk would be too long. Flush existing lines first.
        if current_lines:
            _flush_current()

        # Now handle the overflowing line itself.
        escaped_line = escape_markdown_v2(line)
        if len(escaped_line) <= max_length:
            current_lines.append(line)
            continue

        # Hard-split the escaped line into safe pieces.
        s: str = escaped_line
        while len(s) > 0:
            part: str = s[:max_length]
            # Avoid leaving a trailing single backslash at end of chunk.
            if part.endswith("\\") and len(s) > len(part):
                # extend by one char if possible to complete the escape.
                part = s[: len(part) + 1]
            chunks.append(part)
            s = s[len(part) :]

    _flush_current()
    return chunks


class TelegramNotifier(AbstractNotifier):  # pylint: disable=too-few-public-methods
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
        # Split the original message into chunks that remain valid after
        # escaping, then send each escaped chunk.
        chunks = split_message(message)

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
        """Send a single chunk to Telegram, retrying once on transient errors.

        On the first failure we attempt a single retry. All errors are logged
        with context before being re-raised so callers can decide to abort the
        pipeline.
        """
        url = f"{self._api_base}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": True,
        }

        for attempt in (1, 2):
            try:
                response = requests.post(
                    url, json=payload, timeout=TELEGRAM_API_TIMEOUT
                )
                response.raise_for_status()
                logger.info("Sent chunk %d/%d successfully.", part, total)
                return
            except requests.HTTPError as exc:
                if attempt == 1:
                    resp_text = exc.response.text if exc.response is not None else "N/A"
                    logger.warning(
                        "Telegram API HTTP error sending chunk %d/%d; retrying",
                        part,
                        total,
                    )
                    continue
                resp_text = exc.response.text if exc.response is not None else "N/A"
                logger.error(
                    "Telegram API error sending chunk %d/%d; response: %s",
                    part,
                    total,
                    resp_text,
                )
                raise
            except Exception as exc:  # noqa: BLE001
                if attempt == 1:
                    logger.warning(
                        "Unexpected error sending chunk %d/%d to Telegram: %s; "
                        "retrying once",
                        part,
                        total,
                        exc,
                    )
                    continue
                logger.error(
                    "Unexpected error sending chunk %d/%d to Telegram: %s",
                    part,
                    total,
                    exc,
                )
                raise
