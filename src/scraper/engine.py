"""Scrape orchestration — iterates targets via LeadSpider and returns results."""

import logging
import os

from src.config import load_targets_config
from src.scraper.spider import LeadSpider

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


def scrape_all_targets(targets_config: list[dict] | None = None) -> tuple[list, list]:
    """Scrape all configured target sites using LeadSpider.

    Returns:
        A tuple of (all_records, errors).
    """
    if targets_config is None:
        targets_config = load_targets_config()

    spider = LeadSpider(targets_config)
    result = spider.start()

    errors = spider.scrape_errors
    all_records = spider.all_records

    if result.paused:
        logger.warning(
            "Scrape paused mid-run (checkpoint saved) — returning %d partial records",
            len(all_records),
        )
    logger.info(
        "Scrape complete via LeadSpider: %d total records, %d target errors "
        "(requests=%d, blocked=%d, items_scraped=%d)",
        len(all_records), len(errors),
        result.stats.requests_count, result.stats.blocked_requests_count, result.stats.items_scraped,
    )
    return all_records, errors
