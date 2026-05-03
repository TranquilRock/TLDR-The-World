"""Application entry point – orchestrates the AI Information Pipeline.

Flow:
    1. Load configuration (settings + RSS feed sources).
    2. Fetch all RSS feeds concurrently (graceful per-source error handling).
    3. Pass collected items to the LLM summariser.
    4. Deliver the resulting briefing via Telegram.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.settings import get_settings, load_sources
from src.delivery.telegram_notifier import TelegramNotifier
from src.ingestion.base import FeedItem
from src.ingestion.rss_fetcher import RssFetcher
from src.processing.llm_summarizer import LlmSummarizer

# ---------------------------------------------------------------------------
# Logging setup – structured enough for GitHub Actions console output.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def fetch_all_feeds(sources: list[dict]) -> list[FeedItem]:
    """Fetch all configured RSS feeds in parallel.

    Individual feed failures are caught inside :class:`RssFetcher` and result
    in an empty list for that source, ensuring the pipeline never crashes due
    to a single unavailable feed.

    Args:
        sources: List of feed dicts with ``name`` and ``url`` keys.

    Returns:
        Combined list of :class:`FeedItem` objects from all sources.
    """
    all_items: list[FeedItem] = []
    fetchers = [RssFetcher(name=s["name"], url=s["url"]) for s in sources]

    with ThreadPoolExecutor(max_workers=len(fetchers) or 1) as executor:
        future_to_name = {
            executor.submit(fetcher.fetch): fetcher.name for fetcher in fetchers
        }
        for future in as_completed(future_to_name):
            feed_name = future_to_name[future]
            try:
                items = future.result()
                logger.info("Feed '%s' returned %d item(s).", feed_name, len(items))
                all_items.extend(items)
            except Exception as exc:  # noqa: BLE001
                # RssFetcher.fetch already handles its own exceptions; this is a
                # safety net in case of unexpected errors in the executor itself.
                logger.error(
                    "Unexpected error fetching feed '%s': %s", feed_name, exc
                )

    return all_items


def run_pipeline() -> None:
    """Execute the full pipeline: fetch → process → deliver."""
    logger.info("=== AI Information Pipeline starting ===")

    # 1. Configuration -------------------------------------------------------
    try:
        settings = get_settings()
    except Exception as exc:
        logger.critical("Failed to load settings: %s", exc)
        sys.exit(1)

    sources = load_sources()
    if not sources:
        logger.warning("No RSS sources configured in sources.json.")

    # 2. Ingestion ------------------------------------------------------------
    logger.info("Step 1/3 – Fetching %d RSS feed(s)...", len(sources))
    feed_items = fetch_all_feeds(sources)
    logger.info("Total items fetched: %d", len(feed_items))

    # 3. Processing -----------------------------------------------------------
    logger.info("Step 2/3 – Running LLM summariser...")
    summariser = LlmSummarizer(settings=settings)
    try:
        briefing = summariser.process(feed_items)
    except RuntimeError as exc:
        logger.error("LLM processing failed: %s", exc)
        sys.exit(1)

    # 4. Delivery -------------------------------------------------------------
    logger.info("Step 3/3 – Delivering briefing via Telegram...")
    notifier = TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )
    try:
        notifier.send(briefing)
    except Exception as exc:  # noqa: BLE001
        logger.error("Telegram delivery failed: %s", exc)
        sys.exit(1)

    logger.info("=== Pipeline completed successfully ===")


if __name__ == "__main__":
    run_pipeline()
