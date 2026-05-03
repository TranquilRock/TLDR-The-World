"""LLM-based summarizer using GitHub Models (OpenAI-compatible API).

The summarizer sends all collected feed items to an LLM and asks it to
filter for relevance and produce a structured daily briefing in Traditional
Chinese (繁體中文).
"""

from __future__ import annotations

import json
import logging
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
4. For each SELECTED item, produce a structured entry in **Traditional Chinese (繁體中文)**
   with the following format:

---
**標題**：<A concise, catchy title in Traditional Chinese>
**標籤**：`#AIAgent` `#Geopolitics` (pick the most relevant tags)
**一句重點**：<One-sentence takeaway in Traditional Chinese>
**原始連結**：<original URL>
---

5. Begin the entire output with a brief daily briefing header in Traditional Chinese,
   for example: "📰 每日情報簡報 — <date>"
6. If NO items pass the relevance filter, reply with a single line:
   "今日無高信號情報。"
"""

USER_PROMPT_TEMPLATE = """\
以下是今日從各 RSS 來源收集到的新聞條目，請依照指示進行過濾與摘要：

{items_json}
"""


class LlmSummarizer(AbstractProcessor):
    """Filter and summarise feed items using GitHub Models (OpenAI SDK).

    Args:
        settings: Application settings that carry API credentials and model info.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = OpenAI(
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
            A formatted briefing string in Traditional Chinese.

        Raises:
            RuntimeError: If the LLM API call fails.
        """
        if not items:
            logger.warning("No feed items to process; skipping LLM call.")
            return "今日無高信號情報。"

        logger.info(
            "Sending %d item(s) to LLM model '%s'.",
            len(items),
            self._settings.llm_model,
        )

        items_payload = self._build_payload(items)
        user_content = USER_PROMPT_TEMPLATE.format(
            items_json=json.dumps(items_payload, ensure_ascii=False, indent=2)
        )

        try:
            response = self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
        except Exception as exc:
            logger.error("LLM API call failed: %s", exc)
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        result = response.choices[0].message.content or ""
        logger.info("LLM processing complete. Output length: %d chars.", len(result))
        return result

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
