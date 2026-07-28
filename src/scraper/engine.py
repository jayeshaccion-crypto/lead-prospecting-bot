import logging

from scrapling import StealthyFetcher

from src.config import load_targets_config
from src.models import ScrapeError, now_utc
from src.scraper.targets import scrape_target
from src.scraper.utils import is_robots_allowed, retry

logger = logging.getLogger(__name__)


def create_fetcher():
    """Configure and return a StealthyFetcher with adaptive mode enabled."""
    StealthyFetcher.configure(adaptive=True)
    return StealthyFetcher


@retry(max_attempts=3, base_delay=1.0, backoff=4.0)
def fetch_with_retry(url: str, timeout: int = 30000):
    """Fetch a URL with retry logic and exponential backoff.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in milliseconds.

    Returns:
        The scrapling response object.
    """
    fetcher = create_fetcher()
    return fetcher.fetch(url, timeout=timeout)


def scrape_all_targets(targets_config: list[dict] | None = None) -> tuple[list, list[ScrapeError]]:
    """Scrape all configured target sites and aggregate records and errors.

    Args:
        targets_config: List of target config dicts. If None, loaded from config.

    Returns:
        A tuple of (all_records, errors) where all_records is a flat list of
        RawRecord objects and errors is a list of ScrapeError objects.
    """
    if targets_config is None:
        targets_config = load_targets_config()

    all_records = []
    errors = []

    for target in targets_config:
        url = target.get("entry_url", "")
        try:
            if not is_robots_allowed(url):
                logger.warning("Robots.txt disallows scraping %s — skipping", url)
                errors.append(ScrapeError(
                    url=url,
                    timestamp=now_utc(),
                    error_type="RobotsDisallowed",
                ))
                continue
            logger.info("Scraping target: %s", url)
            records = scrape_target(target)
            logger.info("Scraped %d records from %s", len(records), url)
            all_records.extend(records)
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", url, exc, exc_info=True)
            errors.append(ScrapeError(
                url=url,
                timestamp=now_utc(),
                error_type=type(exc).__name__,
            ))

    logger.info("Scrape complete: %d total records, %d target errors", len(all_records), len(errors))
    return all_records, errors
