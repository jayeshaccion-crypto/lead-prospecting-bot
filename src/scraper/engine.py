from scrapling import StealthyFetcher

from src.config import load_targets_config
from src.models import ScrapeError, now_utc
from src.scraper.targets import scrape_target
from src.scraper.utils import is_robots_allowed, retry


def create_fetcher():
    StealthyFetcher.configure(adaptive=True)
    return StealthyFetcher


@retry(max_attempts=3, base_delay=1.0, backoff=4.0)
def fetch_with_retry(url: str, timeout: int = 30000):
    fetcher = create_fetcher()
    return fetcher.fetch(url, timeout=timeout)


def scrape_all_targets(targets_config: list[dict] | None = None) -> tuple[list, list[ScrapeError]]:
    if targets_config is None:
        targets_config = load_targets_config()

    all_records = []
    errors = []

    for target in targets_config:
        url = target.get("entry_url", "")
        try:
            if not is_robots_allowed(url):
                errors.append(ScrapeError(
                    url=url,
                    timestamp=now_utc(),
                    error_type="RobotsDisallowed",
                ))
                continue
            records = scrape_target(target)
            all_records.extend(records)
        except Exception as exc:
            errors.append(ScrapeError(
                url=url,
                timestamp=now_utc(),
                error_type=type(exc).__name__,
            ))

    return all_records, errors
