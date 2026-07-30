"""Scrape orchestration — iterates targets and delegates to site parsers."""

import logging
import os
import time

from src.config import load_targets_config
from src.models import ScrapeError, now_utc
from src.scraper.targets import scrape_target, get_target_bytes
from src.scraper.utils import is_robots_allowed

logger = logging.getLogger(__name__)

_PROXY_POOL: list[str] | None = None
_PROXY_INDEX = 0


def _fetch_proxies_from_api(api_key: str) -> list[str]:
    """Fetch proxy list from Webshare API and return http://user:pass@host:port URLs."""
    import httpx
    proxies: list[str] = []
    page = 1
    while True:
        resp = httpx.get(
            f"https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page={page}&page_size=100",
            headers={"Authorization": f"Token {api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for p in data.get("results", []):
            if p.get("valid"):
                proxies.append(
                    f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}"
                )
        if not data.get("next"):
            break
        page += 1
    return proxies


def _init_proxy_pool() -> None:
    global _PROXY_POOL
    if _PROXY_POOL is not None:
        return
    url = os.environ.get("WEBSHARE_PROXY_URL", "").strip()
    if url:
        _PROXY_POOL = [url]
        logger.info("Proxy: using WEBSHARE_PROXY_URL rotating endpoint")
        return
    lst = os.environ.get("WEBSHARE_PROXY_LIST", "")
    if lst:
        proxies = [p.strip() for p in lst.split(",") if p.strip()]
        if proxies:
            _PROXY_POOL = proxies
            logger.info("Proxy: using WEBSHARE_PROXY_LIST (%d proxies)", len(proxies))
            return
    api_key = os.environ.get("WEBSHARE_API_KEY", "").strip()
    if api_key:
        try:
            api_proxies = _fetch_proxies_from_api(api_key)
            if api_proxies:
                _PROXY_POOL = api_proxies
                logger.info("Proxy: fetched %d proxies from Webshare API", len(api_proxies))
                return
        except Exception as exc:
            logger.warning("Proxy: failed to fetch from Webshare API: %s", exc)
    logger.warning("Proxy: no Webshare proxy configured (set WEBSHARE_PROXY_URL, WEBSHARE_PROXY_LIST, or WEBSHARE_API_KEY)")
    _PROXY_POOL = []


def _get_next_proxy() -> str | None:
    global _PROXY_INDEX
    _init_proxy_pool()
    if not _PROXY_POOL:
        return None
    proxy = _PROXY_POOL[_PROXY_INDEX % len(_PROXY_POOL)]
    _PROXY_INDEX += 1
    return proxy


def scrape_all_targets(targets_config: list[dict] | None = None) -> tuple[list, list[ScrapeError]]:
    """Scrape all configured target sites and aggregate records and errors.

    Each target's pages are fetched via a persistent StealthySession (real
    headless browser with Cloudflare solving), and parsed by the registered
    parser function. Adds a delay between targets to avoid rate limiting.

    Justdial and IndiaMART require a webshare proxy to run from GitHub-hosted
    runners (Azure IP ranges are blocked). TradeIndia runs unproxied.

    Returns:
        A tuple of (all_records, errors).
    """
    if targets_config is None:
        targets_config = load_targets_config()

    _init_proxy_pool()

    all_records = []
    errors = []

    for idx, target in enumerate(targets_config):
        url = target.get("entry_url", "")
        target_delay = target.get("fetch_kwargs", {}).get("target_delay", 5.0)
        name = target.get("name", "")

        if idx > 0:
            logger.info("Waiting %.1fs before next target...", target_delay)
            time.sleep(target_delay)

        # Proxy check: Justdial and IndiaMART require proxy
        if name in ("Justdial", "IndiaMART"):
            proxy = _get_next_proxy()
            if not proxy:
                logger.warning("%s requires a proxy but none configured — skipping", name)
                errors.append(ScrapeError(url=url, timestamp=now_utc(), error_type="ProxyNotConfigured"))
                continue
            target.setdefault("fetch_kwargs", {})["proxy"] = proxy
            logger.info("%s: using proxy %s", name, proxy.partition("@")[-1] or proxy)
        else:
            target.get("fetch_kwargs", {}).pop("proxy", None)

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

    target_bytes = get_target_bytes()
    if target_bytes:
        per_target = ", ".join(f"{k}={v:,}B" for k, v in target_bytes.items())
        total = sum(target_bytes.values())
        logger.info("Bytes fetched - %s | total=%s", per_target, f"{total:,}B")

    logger.info("Scrape complete: %d total records, %d target errors", len(all_records), len(errors))
    return all_records, errors
