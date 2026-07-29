"""Scrape orchestration — iterates targets and delegates to site parsers."""

import logging
import time

from src.config import load_targets_config
from src.models import ScrapeError, now_utc
from src.scraper.targets import scrape_target
from src.scraper.utils import is_robots_allowed

logger = logging.getLogger(__name__)


def scrape_all_targets(targets_config: list[dict] | None = None) -> tuple[list, list[ScrapeError]]:
    """Scrape all configured target sites and aggregate records and errors.

    Each target's pages are fetched via a persistent StealthySession (real
    headless browser with Cloudflare solving), and parsed by the registered
    parser function. Adds a delay between targets to avoid rate limiting.

    Returns:
        A tuple of (all_records, errors).
    """
    if targets_config is None:
        targets_config = load_targets_config()

    all_records = []
    errors = []

    for idx, target in enumerate(targets_config):
        url = target.get("entry_url", "")
        target_delay = target.get("fetch_kwargs", {}).get("target_delay", 5.0)

        if idx > 0:
            logger.info("Waiting %.1fs before next target...", target_delay)
            time.sleep(target_delay)

        try:
            if not is_robots_allowed(url):
                logger.warning("Robots.txt disallows scraping %s — skipping", url)
                errors.append(ScrapeError(url=url, timestamp=now_utc(), error_type="RobotsDisallowed"))
                continue

            logger.info("Scraping target: %s (pages=%s)", url, target.get("pages", 1))
            records = scrape_target(target)
            logger.info("Scraped %d records from %s", len(records), url)
            all_records.extend(records)
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", url, exc, exc_info=True)
            errors.append(ScrapeError(url=url, timestamp=now_utc(), error_type=type(exc).__name__))

    logger.info("Scrape complete: %d total records, %d target errors", len(all_records), len(errors))
    return all_records, errors
