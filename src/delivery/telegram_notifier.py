"""Telegram delivery channel - concrete implementation of :class:`AbstractNotifier`.

Sends the daily briefing as one or more Telegram messages using the Bot API.
Long messages (> 4096 characters) are automatically split into chunks while
preserving the original text and line breaks.

When MarkdownV2 is enabled, the notifier rebuilds the outgoing message from
the briefing's known structure instead of forwarding raw LLM markdown. That
keeps formatting readable while still escaping Telegram's special characters.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import requests

from src.delivery.base import AbstractNotifier

logger = logging.getLogger(__name__)

# Telegram message length limit (characters).
MAX_MESSAGE_LENGTH: int = 4096

TELEGRAM_API_TIMEOUT: int = 30  # seconds

_TITLE_RE = re.compile(r"^\*\*Title\*\*:\s*(.+)$")
_SOURCE_RE = re.compile(r"^\*\*Source\*\*:\s*(.+)$")
_TAGS_RE = re.compile(r"^\*\*Tags\*\*:\s*(.+)$")
_TAKEAWAY_RE = re.compile(r"^\*\*One-line takeaway\*\*:\s*(.+)$")
_LINK_RE = re.compile(r"^\*\*Original link\*\*:\s*(.+)$")
_FIELD_PATTERNS = (
    ("title", _TITLE_RE),
    ("source", _SOURCE_RE),
    ("tags", _TAGS_RE),
    ("takeaway", _TAKEAWAY_RE),
    ("link", _LINK_RE),
)


def _capture_block_field(line: str, current_block: dict[str, str]) -> bool:
    """Capture a known structured briefing field from a single line."""
    for key, pattern in _FIELD_PATTERNS:
        if match := pattern.match(line):
            current_block[key] = match.group(1).strip()
            return True
    return False


def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split *text* into chunks while preserving line breaks and wording.

    The text is treated as plain text. Chunk boundaries are chosen so each
    piece stays within Telegram's message limit without rewriting the content.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []

    def _flush_current() -> None:
        if not current_lines:
            return
        chunks.append("".join(current_lines))
        current_lines.clear()

    for line in text.splitlines(keepends=True):
        tentative = "".join(current_lines) + line
        if len(tentative) <= max_length:
            current_lines.append(line)
            continue

        # Tentative chunk would be too long. Flush existing lines first.
        if current_lines:
            _flush_current()

        # Now handle the overflowing line itself.
        if len(line) <= max_length:
            current_lines.append(line)
            continue

        # Hard-split the oversized line into plain-text pieces.
        s: str = line
        while len(s) > 0:
            part: str = s[:max_length]
            chunks.append(part)
            s = s[len(part) :]

    _flush_current()
    return chunks


def _escape_markdown_v2(text: str) -> str:
    """Escape MarkdownV2 control characters in *text*."""
    escaped = text
    for char in r"_*[]()~`>#+-=|{}.!":
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def _render_markdown_v2_message(message: str) -> str:
    """Render the pipeline briefing into Telegram MarkdownV2 safely.

    The summariser emits a predictable block structure. We parse that structure
    and re-emit it with Telegram-safe formatting so only the content is escaped
    and the layout stays readable.
    """
    stripped = message.strip()
    if not stripped:
        return ""

    if stripped == "No high-signal intelligence today.":
        return _escape_markdown_v2(stripped)

    date_str = datetime.now(timezone.utc).date().isoformat()
    header = _escape_markdown_v2(f"📰 Daily Intelligence Briefing — {date_str}")

    lines = message.splitlines()
    rendered_blocks: list[str] = []
    current_block: dict[str, str] = {}

    def _flush_block() -> None:
        if not current_block:
            return
        title = _escape_markdown_v2(current_block.get("title", ""))
        source = _escape_markdown_v2(current_block.get("source", ""))
        tags = _escape_markdown_v2(current_block.get("tags", ""))
        takeaway = _escape_markdown_v2(current_block.get("takeaway", ""))
        link = _escape_markdown_v2(current_block.get("link", ""))
        source_label = _escape_markdown_v2("Source")
        tags_label = _escape_markdown_v2("Tags")
        takeaway_label = _escape_markdown_v2("One-line takeaway")
        link_label = _escape_markdown_v2("Original link")

        block_lines = [
            f"*{title}*" if title else "",
            f"• *{source_label}:* {source}" if source else "",
            f"• *{tags_label}:* {tags}" if tags else "",
            f"• *{takeaway_label}:* {takeaway}" if takeaway else "",
            f"• *{link_label}:* {link}" if link else "",
        ]
        rendered_blocks.append("\n".join(line for line in block_lines if line))
        current_block.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line == "---":
            _flush_block()
            continue

        if _capture_block_field(line, current_block):
            continue

    _flush_block()

    if not rendered_blocks:
        return f"{header}\n\n{_escape_markdown_v2(message)}".strip()

    body = "\n\n".join(block for block in rendered_blocks if block).strip()
    return f"{header}\n\n{body}".strip()


def _split_markdown_message(
    text: str, max_length: int = MAX_MESSAGE_LENGTH
) -> list[str]:
    """Split a rendered MarkdownV2 message on block boundaries."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []

    def _flush_current() -> None:
        if current_lines:
            chunks.append("\n".join(current_lines).strip())
            current_lines.clear()

    for block in text.split("\n\n"):
        tentative = "\n\n".join(current_lines + [block]) if current_lines else block
        if len(tentative) <= max_length:
            current_lines.append(block)
            continue

        if current_lines:
            _flush_current()

        if len(block) <= max_length:
            current_lines.append(block)
            continue

        # Fallback: split a single oversized block by lines.
        lines = block.splitlines()
        chunk_lines: list[str] = []
        for line in lines:
            tentative_line = "\n".join(chunk_lines + [line]) if chunk_lines else line
            if len(tentative_line) <= max_length:
                chunk_lines.append(line)
                continue
            if chunk_lines:
                chunks.append("\n".join(chunk_lines).strip())
                chunk_lines.clear()
            if len(line) <= max_length:
                chunk_lines.append(line)
                continue
            start = 0
            while start < len(line):
                chunks.append(line[start : start + max_length])
                start += max_length
        if chunk_lines:
            chunks.append("\n".join(chunk_lines).strip())

    _flush_current()
    return [chunk for chunk in chunks if chunk]


class TelegramNotifier(AbstractNotifier):  # pylint: disable=too-few-public-methods
    """Send messages to a Telegram chat via the Bot HTTP API.

    Args:
        bot_token: Telegram bot token obtained from @BotFather.
        chat_id:   Target chat or channel ID.
        parse_mode: Telegram message parse mode.  Defaults to ``None``.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        parse_mode: str | None = "MarkdownV2",
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

        MarkdownV2 is rendered from the briefing structure when enabled, and
        the final message is split into chunks if it exceeds Telegram's
        4096-character limit.

        Args:
            message: The formatted briefing text.
        """
        rendered_message = (
            _render_markdown_v2_message(message)
            if self._parse_mode == "MarkdownV2"
            else message
        )
        chunks = (
            _split_markdown_message(rendered_message)
            if self._parse_mode == "MarkdownV2"
            else split_message(rendered_message)
        )

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
            "disable_web_page_preview": True,
        }
        if self._parse_mode:
            payload["parse_mode"] = self._parse_mode

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
