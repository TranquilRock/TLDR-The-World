"""LLM-based summarizer using GitHub Models (OpenAI-compatible API).

The summarizer sends collected feed items to an LLM, filters for relevance,
and produces a structured daily briefing in English.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

from openai import OpenAI

from config.settings import Settings
from src.ingestion.base import FeedItem
from src.processing.base import AbstractProcessor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert intelligence analyst and editor.

Your task:
1. Review the list of news items provided by the user (formatted as JSON).
2. Keep ONLY those that are highly relevant to either:
    - "AI Agents / AI Technology" (e.g., new models, agentic frameworks, AI safety,
      LLM research, robotics driven by AI, etc.)
    - "Major Geopolitics" (e.g., US–China relations, US–Iran relations, NATO, wars,
      sanctions, diplomatic breakthroughs, major elections with global impact, etc.)
3. Discard clickbait, opinion pieces without substance, celebrity gossip, and items
    that have no clear relevance to the two categories above.
4. For each SELECTED item, produce a structured entry in English with the
    following format:

---
**Title**: <A concise, catchy title in English>
**Source**: <Original publisher/source name from input>
**Tags**: `#AIAgent` `#Geopolitics` (pick the most relevant tags)
**One-line takeaway**: <One-sentence takeaway in English>
**Original link**: <original URL>
---

5. Begin the entire output with a brief daily briefing header in English,
    for example: "📰 Daily Intelligence Briefing — <date>"
6. If NO items pass the relevance filter, reply with a single line:
    "No high-signal intelligence today."
"""

USER_PROMPT_TEMPLATE = """\
Below are today's news items collected from various RSS sources. Please
filter and summarise them according to the instructions.

{items_json}
"""

# Prompt for per-item compact summarisation (returns JSON list)
PER_ITEM_PROMPT = """\
You are an information curator. Given a single news item (as JSON), produce
one compact JSON object with the following fields:

- `title`: the headline
- `source`: original source/publisher name from input
- `one_line_summary`: a one-sentence takeaway in English (max 30 words)
- `tag`: one of `#AIAgent`, `#Geopolitics`, or `#Other` (choose the most relevant)
- `link`: the original URL

Return exactly one JSON object, e.g.:
{"title": ..., "source": ..., "one_line_summary": ..., "tag": ..., "link": ...}
and nothing else.
"""


class LlmSummarizer(AbstractProcessor):  # pylint: disable=too-few-public-methods
    """Filter and summarise feed items using GitHub Models (OpenAI SDK).

    Args:
        settings: Application settings that carry API credentials and model info.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._min_model_call_interval_seconds = max(
            0.0,
            getattr(settings, "github_models_min_interval_seconds", 0.0),
        )
        self._last_model_call_at: float | None = None
        # OpenAI client object - typed as Any because SDK types may vary.
        self._client: Any = OpenAI(
            api_key=settings.github_models_token,
            base_url=settings.github_models_base_url,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process(self, items: list[FeedItem]) -> str:
        """Send *items* to the LLM and return the formatted briefing.

        Args:
            items: Raw feed items collected from all sources.

        Returns:
            A formatted briefing string in English.

        Raises:
            RuntimeError: If the LLM API call fails.
        """
        if not items:
            logger.warning("No feed items to process; skipping LLM call.")
            return "No high-signal intelligence today."

        logger.info(
            "Processing %d item(s) with batched per-item summarisation using "
            "model '%s'.",
            len(items),
            self._settings.llm_model,
        )

        # 1) First pass: produce compact per-item summaries by calling the
        # model once per article.
        summaries: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            try:
                summary = self._summarise_item(item)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Per-item summarisation failed for item %d (%s): %s",
                    idx,
                    item.get("title", "<no title>"),
                    exc,
                )
                continue
            if summary:
                summaries.append(summary)

        if not summaries:
            logger.warning(
                "No per-item summaries produced; skipping final aggregation."
            )
            return "No high-signal intelligence today."

        # 2) Second pass: aggregate the compact summaries into final briefing.
        logger.info(
            "Aggregating %d compact summaries into final briefing.", len(summaries)
        )
        items_payload = [
            {
                "source": s.get("source", ""),
                "title": s.get("title", ""),
                "summary": s.get("one_line_summary", ""),
                "link": s.get("link", ""),
                "tag": s.get("tag", "#Other"),
            }
            for s in summaries
        ]

        user_content = USER_PROMPT_TEMPLATE.format(
            items_json=json.dumps(items_payload, ensure_ascii=False, indent=2)
        )

        try:
            response = self._call_model(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=2048,
            )
        except Exception as exc:
            logger.error("LLM API call failed during aggregation: %s", exc)
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        if not response:
            logger.error("LLM aggregation returned empty result")
            raise RuntimeError("LLM aggregation returned no content")

        logger.info("LLM aggregation complete. Output length: %d chars.", len(response))
        return response

    def _call_model(
        self, messages: list[dict[str, str]], max_tokens: int = 2048
    ) -> str:
        """Call the model and return the response string, handling SDK shapes."""
        max_attempts = getattr(self._settings, "github_models_retry_max_attempts", 1)
        base_backoff = getattr(
            self._settings, "github_models_retry_backoff_base_seconds", 0.5
        )
        max_backoff = getattr(
            self._settings, "github_models_retry_backoff_max_seconds", 8.0
        )

        attempt = 0
        while True:
            attempt += 1
            self._wait_for_next_model_call_slot()
            try:
                resp = self._client.chat.completions.create(
                    model=self._settings.llm_model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=max_tokens,
                )
                break
            except (
                Exception
            ) as exc:  # pragma: no cover - branching tested in unit tests
                # Detect 429 / rate-limit indicators if available on the exception
                status_code = getattr(exc, "status_code", None) or getattr(
                    exc, "http_status", None
                )
                msg = str(exc)
                is_rate_limit = False
                if status_code == 429:
                    is_rate_limit = True
                elif "429" in msg or "RateLimit" in msg or "rate limit" in msg.lower():
                    is_rate_limit = True

                if is_rate_limit and attempt < max_attempts:
                    # exponential backoff with small jitter
                    backoff = min(max_backoff, base_backoff * (2 ** (attempt - 1)))
                    jitter = random.uniform(0, backoff * 0.1)
                    sleep_for = backoff + jitter
                    logger.warning(
                        "Model request rate-limited (attempt %d/%d). Backing off %.2fs",
                        attempt,
                        max_attempts,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                logger.error("Model request failed: %s", exc)
                raise

        # Extract content similar to previous logic
        if isinstance(resp, dict):
            choices = resp.get("choices") or []
            if not choices:
                return ""
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message") or {}
                return msg.get("content") or first.get("text") or ""
            return ""

        # object-like response
        choices = getattr(resp, "choices", None)
        if not choices:
            return ""
        first = choices[0]
        message = getattr(first, "message", None)
        if message is not None:
            return getattr(message, "content", "") or ""
        return getattr(first, "text", "") or ""

    def _wait_for_next_model_call_slot(self) -> None:
        """Keep consecutive model calls spaced apart."""
        if self._min_model_call_interval_seconds <= 0:
            self._last_model_call_at = time.monotonic()
            return

        now = time.monotonic()
        if self._last_model_call_at is not None:
            elapsed = now - self._last_model_call_at
            remaining = self._min_model_call_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)

        self._last_model_call_at = time.monotonic()

    def _summarise_item(self, item: FeedItem) -> dict[str, Any] | None:
        """Produce a compact summary for a single FeedItem.

        Returns a dict with keys: title, one_line_summary, tag, link, source
        or None if summarisation / parsing failed.
        """
        payload = {
            "source": item["source_name"],
            "title": item["title"],
            "summary": item["summary"][:300] if item["summary"] else "",
            "link": item["link"],
            "published": item["published_date"],
        }

        user_content = (
            "Please produce a compact summary for the following single news "
            "item (see instructions):\n\n" + json.dumps(payload, ensure_ascii=False)
        )

        try:
            resp_text = self._call_model(
                messages=[
                    {"role": "system", "content": PER_ITEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=256,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Model call failed for item '%s': %s",
                item.get("title", "<no title>"),
                exc,
            )
            return None

        # Parse JSON from the model output defensively
        try:
            parsed = json.loads(resp_text)
            if isinstance(parsed, dict):
                return {
                    "source": parsed.get("source", payload["source"]),
                    "title": parsed.get("title", payload["title"]),
                    "one_line_summary": parsed.get("one_line_summary", ""),
                    "tag": parsed.get("tag", "#Other"),
                    "link": parsed.get("link", payload["link"]),
                }
        except Exception:  # pylint: disable=broad-except
            # Try to salvage JSON-like substring if model wrapped output
            try:
                start = resp_text.find("{")
                end = resp_text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parsed = json.loads(resp_text[start : end + 1])
                    if isinstance(parsed, dict):
                        return {
                            "source": parsed.get("source", payload["source"]),
                            "title": parsed.get("title", payload["title"]),
                            "one_line_summary": parsed.get("one_line_summary", ""),
                            "tag": parsed.get("tag", "#Other"),
                            "link": parsed.get("link", payload["link"]),
                        }
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to parse JSON for item '%s'. Response: %s",
                    payload["title"],
                    resp_text,
                )

        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(items: list[FeedItem]) -> list[dict[str, Any]]:
        """Convert FeedItems into a compact JSON-serialisable representation."""
        return [
            {
                "source": item["source_name"],
                "title": item["title"],
                "summary": item["summary"][:500] if item["summary"] else "",
                "link": item["link"],
                "published": item["published_date"],
            }
            for item in items
        ]
