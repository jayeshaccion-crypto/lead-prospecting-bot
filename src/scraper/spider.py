"""LeadSpider — Scrapling Spider for multi-category × multi-city lead scraping.

Generates a Request per site/category/city/page combination from targets.yaml
expansion config. Routes justdial/indiamart through AsyncStealthySession (proxy-
enabled, CF-solving) and tradeindia through plain FetcherSession. Supports
daily request caps, stop-on-empty-page, and JustDial conditional modes.
"""

import json
import logging
import os
import random
import time
from collections import defaultdict

import anyio

from scrapling.spiders import Spider, Request

from src.config import load_full_config, get_icp_categories, get_icp_cities
from src.models import ScrapeError, now_utc
from src.scraper.targets import (
    PARSER_REGISTRY,
    RawRecord,
    _enrich_from_detail_pages,
    _enrich_indiamart_via_httpx,
    _extract_detail_urls,
    _build_page_url,
    BLOCKED_DOMAINS,
    KNOWN_SITE_WIDE_PHONES,
    KNOWN_SITE_WIDE_EMAILS,
)
from src.scraper.utils import is_robots_allowed

logger = logging.getLogger(__name__)

SID_JUSTDIAL = "justdial_session"
SID_INDIAMART = "indiamart_session"
SID_TRADEINDIA = "tradeindia_session"

SITE_NAMES = {
    SID_JUSTDIAL: "Justdial",
    SID_INDIAMART: "IndiaMART",
    SID_TRADEINDIA: "TradeIndia",
}

SID_BY_NAME = {
    "justdial": SID_JUSTDIAL,
    "indiamart": SID_INDIAMART,
    "tradeindia": SID_TRADEINDIA,
}

# Per-domain throttle delays (applied by the scheduler, domain-scoped)
DOMAIN_DELAYS: dict[str, tuple[float, float]] = {
    SID_JUSTDIAL: (5.0, 10.0),
    SID_INDIAMART: (8.0, 20.0),
    SID_TRADEINDIA: (0.0, 0.0),
}

# URL templates per site — {category} and {city} replaced with site-specific labels
SITE_URL_TEMPLATES = {
    "justdial": "https://www.justdial.com/{city}/{category}/nct-10278073",
    "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
    "tradeindia": "https://www.tradeindia.com/manufacturers/{category}.html",
}


class DomainRequestCounter:
    """Tracks and enforces a daily request cap per domain.

    Uses a simple file-based counter (reset on date change) so caps persist
    across pipeline runs on the same day.
    """
    def __init__(self, counter_file: str = "data/request_counts.json"):
        self._file = counter_file
        self._counts: dict[str, int] = {}
        self._date: str = ""
        self._load()

    def _load(self):
        today = time.strftime("%Y-%m-%d")
        try:
            import json
            from pathlib import Path
            p = Path(self._file)
            if p.exists():
                data = json.loads(p.read_text())
                if data.get("date") == today:
                    self._counts = data.get("counts", {})
            self._date = today
        except Exception:
            self._counts = {}
            self._date = today

    def _save(self):
        try:
            from pathlib import Path
            p = Path(self._file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"date": self._date, "counts": self._counts}))
        except Exception:
            pass

    def allowed(self, domain: str, cap: int) -> bool:
        """Check if a request to the domain is within the daily cap."""
        current = self._counts.get(domain, 0)
        if current >= cap:
            return False
        self._counts[domain] = current + 1
        self._save()
        return True


class LeadSpider(Spider):
    name = "lead_spider"
    concurrent_requests = 2
    max_blocked_retries = 3
    download_delay = 0.0
    autothrottle_enabled = False
    robots_txt_obey = False
    start_urls: list[str] = []

    def __init__(self, targets_config: list[dict]):
        self._targets_config = targets_config
        self._full_config = load_full_config()
        self._expansion = self._full_config.get("expansion", {})
        self._categories: list[dict] = self._expansion.get("categories", [])
        self._cities: list[dict] = self._expansion.get("cities", [])
        self._url_templates: dict = self._full_config.get("url_templates", {})
        self._icp_categories = get_icp_categories(self._full_config)
        self._icp_cities = get_icp_cities(self._full_config)
        self._req_counter = DomainRequestCounter()

        self.all_records: list[RawRecord] = []
        self.scrape_errors: list[ScrapeError] = []
        self._jd_stats: dict = {"blocked_ips": set(), "blocked": 0, "succeeded": 0}
        self._enrich_data: list = []
        self._bytes_fetched: dict[str, int] = {}
        self._fill_rates: dict[str, dict] = {}
        self._jd_mode: str = "unknown"
        self._jd_tested: bool = False
        super().__init__(crawldir=".scrapling_checkpoints")

    def configure_sessions(self, manager):
        from scrapling.fetchers import AsyncStealthySession, FetcherSession

        manager.add(SID_TRADEINDIA, FetcherSession())

        stealth_kw = dict(
            headless=True, solve_cloudflare=True, load_dom=True,
            network_idle=True, disable_resources=True,
            blocked_domains=BLOCKED_DOMAINS,
        )
        manager.add(SID_JUSTDIAL, AsyncStealthySession(capture_xhr=r".*", **stealth_kw), lazy=True)
        manager.add(SID_INDIAMART, AsyncStealthySession(**stealth_kw), lazy=True)

    def _site_label(self, slug: str, site: str, label_type: str) -> str:
        """Resolve a slug to a site-specific URL label.

        Tries the per-site labels dict first, then falls back to slug as-is.
        """
        items = self._categories if label_type == "category" else self._cities
        for item in items:
            if item.get("slug") == slug:
                labels = item.get("labels", {})
                if site in labels:
                    return labels[site]
        return slug

    def _build_source_url(self, site_name: str, category_slug: str, city_slug: str | None) -> str:
        """Build the entry URL for a site/category/city combination."""
        template = self._url_templates.get(site_name.lower(), "")
        if not template:
            return ""
        cat_label = self._site_label(category_slug, site_name.lower(), "category")
        city_label = self._site_label(city_slug or "", site_name.lower(), "city") if city_slug else ""
        return template.format(category=cat_label, city=city_label)

    async def start_requests(self):
        if not self._categories:
            logger.warning("No categories configured in expansion — nothing to scrape")
            return

        from src.scraper import engine as _engine_mod
        _engine_mod._init_proxy_pool()

        for target in self._targets_config:
            name = target.get("name", "")
            if not target.get("enabled", True):
                logger.info("%s is disabled in config — skipping", name)
                continue

            site_key = name.lower()
            sid = SID_BY_NAME.get(site_key, f"{site_key}_session")
            parser_name = target["parser"]
            pages = target.get("pages", 1)
            if os.environ.get("SCRAPE_FULL_PAGES", "").lower() != "true":
                pages = 1
            max_req = target.get("max_requests_per_day", 100)
            use_proxy = site_key in ("justdial", "indiamart")
            fetch_kwargs = target.get("fetch_kwargs", {})

            # Determine which mode JustDial runs in
            if site_key == "justdial":
                residential_proxy = os.environ.get("RESIDENTIAL_PROXY_URL_JUSTDIAL", "").strip()
                if residential_proxy:
                    self._jd_mode = "residential"
                elif _engine_mod._PROXY_POOL:
                    self._jd_mode = "datacenter"
                else:
                    self._jd_mode = "no_proxy"
                    logger.warning("Justdial requires a proxy but none configured — skipping")
                    self.scrape_errors.append(ScrapeError(
                        url=target.get("entry_url", ""),
                        timestamp=now_utc(),
                        error_type="ProxyNotConfigured",
                    ))
                    continue

            _proxy_exhausted = False
            _robots_cache: dict[str, bool] = {}

            # For each category
            for cat_idx, cat_item in enumerate(self._categories):
                if cat_idx > 0:
                    await anyio.sleep(random.uniform(3.0, 6.0))
                if _proxy_exhausted:
                    break
                category_slug = cat_item["slug"]

                # For each city
                cities_to_scrape = self._cities if site_key in ("justdial", "indiamart") else [{"slug": ""}]
                for city_idx, city_item in enumerate(cities_to_scrape):
                    if city_idx > 0:
                        await anyio.sleep(random.uniform(2.0, 5.0))
                    if _proxy_exhausted:
                        break
                    city_slug = city_item.get("slug", "")

                    # Build the entry URL
                    if site_key == "justdial" and self._jd_mode == "datacenter" and self._jd_tested:
                        continue
                    source_url = self._build_source_url(name, category_slug, city_slug)
                    if not source_url:
                        continue

                    # Domain request cap
                    domain = source_url.split("/")[2] if "//" in source_url else site_key
                    if not self._req_counter.allowed(domain, max_req):
                        logger.info("Daily cap reached for %s (%d) — stopping", domain, max_req)
                        _proxy_exhausted = True
                        break

                    if use_proxy:
                        proxy = _engine_mod._get_next_proxy()
                        if not proxy:
                            if site_key == "justdial":
                                continue
                            logger.error("IndiaMART requires a proxy but none configured — skipping all combos")
                            self.scrape_errors.append(ScrapeError(
                                url=source_url, timestamp=now_utc(),
                                error_type="ProxyNotConfigured",
                            ))
                            _proxy_exhausted = True
                            break

                    # Cached robots.txt check
                    if domain not in _robots_cache:
                        _robots_cache[domain] = is_robots_allowed(source_url)
                    if not _robots_cache[domain]:
                        logger.warning("Robots.txt disallows scraping %s — skipping", domain)
                        self.scrape_errors.append(ScrapeError(
                            url=source_url, timestamp=now_utc(),
                            error_type="RobotsDisallowed",
                        ))
                        continue

                    for page_num in range(1, pages + 1):
                        page_url = _build_page_url(parser_name, source_url, page_num)

                        # Domain-scoped throttle delay via anyio.sleep
                        delay_range = DOMAIN_DELAYS.get(sid, (0, 0))
                        if delay_range[1] > 0 and page_num > 1:
                            await anyio.sleep(random.uniform(*delay_range))

                        session_kwargs = {"timeout": fetch_kwargs.get("timeout", 90000)}
                        if use_proxy:
                            session_kwargs["wait"] = max(int(fetch_kwargs.get("page_delay", 2.0) * 1000), 2000)
                            if fetch_kwargs.get("wait_selector") and page_num == 1:
                                session_kwargs["wait_selector"] = fetch_kwargs["wait_selector"]
                                session_kwargs["wait_selector_state"] = "visible"
                            session_kwargs["proxy"] = proxy

                        yield Request(
                            page_url,
                            sid=sid,
                            meta=dict(
                                parser=parser_name,
                                source_url=source_url,
                                site_name=name,
                                category_slug=category_slug,
                                city_slug=city_slug,
                                fetch_kwargs=fetch_kwargs,
                                page=page_num,
                                pages_total=pages,
                                daily_cap=max_req,
                            ),
                            **session_kwargs,
                        )

                # JustDial ASN test: only run one category in datacenter mode
                if site_key == "justdial" and self._jd_mode == "datacenter":
                    self._jd_tested = True

    async def parse(self, response):
        meta = response.meta
        parser_name = meta["parser"]
        source_url = meta["source_url"]
        site_name = meta.get("site_name", "")
        category_slug = meta.get("category_slug", "")
        city_slug = meta.get("city_slug", "")
        fetch_kwargs = meta.get("fetch_kwargs", {})
        page_num = meta.get("page", 1)
        pages_total = meta.get("pages_total", 1)

        parser_func = PARSER_REGISTRY.get(parser_name)
        if not parser_func:
            return

        records = parser_func(response, source_url=source_url)
        if not records:
            return

        body = getattr(response, "html_content", None) or getattr(response, "text", b"")
        body_size = len(body) if isinstance(body, bytes) else len(body.encode("utf-8")) if isinstance(body, str) else 0
        self._bytes_fetched[parser_name] = self._bytes_fetched.get(parser_name, 0) + body_size

        base_idx = len(self.all_records)

        # Tag each record with category/city for enrichment and scoring
        tagged = []
        for rec in records:
            tagged.append(RawRecord(
                company_name=rec.company_name,
                website=rec.website,
                email=rec.email,
                phone=rec.phone,
                address=rec.address,
                industry_code=rec.industry_code,
                source_url=rec.source_url or source_url,
            ))
        self.all_records.extend(tagged)

        detail_urls = _extract_detail_urls(parser_name, response, tagged, base_idx)
        if detail_urls:
            self._enrich_data.append({
                "parser": parser_name,
                "records": tagged,
                "detail_urls": [(base_idx + i, u) for i, u in detail_urls],
                "source_url": source_url,
                "fetch_kwargs": fetch_kwargs,
            })

        # Track fill rates for reporting
        site = site_name or parser_name
        if site not in self._fill_rates:
            self._fill_rates[site] = {"total": 0, "phone": 0, "email": 0, "website": 0}
        for rec in tagged:
            self._fill_rates[site]["total"] += 1
            if rec.phone:
                self._fill_rates[site]["phone"] += 1
            if rec.email:
                self._fill_rates[site]["email"] += 1
            if rec.website:
                self._fill_rates[site]["website"] += 1

        if site_name.lower() == "justdial":
            self._jd_stats["succeeded"] += 1

        for rec in tagged:
            yield {
                "company_name": rec.company_name,
                "website": rec.website,
                "email": rec.email,
                "phone": rec.phone,
                "address": rec.address,
                "industry_code": rec.industry_code,
                "source_url": rec.source_url,
                "category_slug": category_slug,
                "city_slug": city_slug,
            }

    async def is_blocked(self, response):
        if response.status in (401, 403, 407, 429, 444, 500, 502, 503, 504):
            return True
        body = response.body
        body_size = len(body) if isinstance(body, bytes) else len(str(body).encode("utf-8"))
        if response.status == 200 and 0 < body_size < 500:
            return True
        return False

    async def retry_blocked_request(self, request, response):
        from src.scraper.engine import _get_next_proxy
        proxy = _get_next_proxy()
        if proxy:
            request._session_kwargs["proxy"] = proxy
        else:
            request._session_kwargs.pop("proxy", None)

        sid = request.sid
        site_name = SITE_NAMES.get(sid, sid)
        body = response.body
        body_size = len(body) if isinstance(body, bytes) else len(str(body).encode("utf-8"))
        log_proxy = str(proxy).partition("@")[-1] if proxy else "none"

        logger.warning(
            "Blocked: %s via %s, body=%d bytes, retrying with next proxy",
            site_name, log_proxy, body_size,
        )

        if sid == SID_JUSTDIAL:
            self._jd_stats["blocked_ips"].add(log_proxy)
            if body_size < 500:
                self._jd_stats["blocked"] += 1

        return request

    async def on_close(self):
        # TradeIndia detail page enrichment using FetcherSession
        for entry in self._enrich_data:
            if entry["parser"] != "parse_tradeindia":
                continue
            parser_name = entry["parser"]
            detail_urls = entry["detail_urls"]
            fetch_kwargs = entry["fetch_kwargs"]

            needy = [
                (i, u) for i, u in detail_urls
                if i < len(self.all_records) and not (
                    self.all_records[i].phone and self.all_records[i].email
                )
            ]
            if needy:
                max_detail = fetch_kwargs.get("max_detail_pages", 20)
                logger.info("TradeIndia: enriching %d records via detail pages (max %d)", len(needy), max_detail)
                enriched = await anyio.to_thread.run_sync(
                    _enrich_from_detail_pages, None, self.all_records,
                    needy[:max_detail], fetch_kwargs.get("timeout", 90000),
                )

        # IndiaMART httpx enrichment
        for entry in self._enrich_data:
            if entry["parser"] == "parse_indiamart":
                from src.scraper.engine import _get_next_proxy
                proxy = _get_next_proxy()
                await anyio.to_thread.run_sync(_enrich_indiamart_via_httpx, self.all_records, proxy)

        # Recompute fill rates after enrichment
        self._fill_rates = {}
        for rec in self.all_records:
            site = SITE_NAMES.get(
                f"{_source_slug(rec.source_url)}_session",
                _source_slug(rec.source_url),
            )
            if site not in self._fill_rates:
                self._fill_rates[site] = {"total": 0, "phone": 0, "email": 0, "website": 0}
            self._fill_rates[site]["total"] += 1
            if rec.phone:
                self._fill_rates[site]["phone"] += 1
            if rec.email:
                self._fill_rates[site]["email"] += 1
            if rec.website:
                self._fill_rates[site]["website"] += 1

        # Log fill rates
        for site, rates in sorted(self._fill_rates.items()):
            t = rates["total"]
            if t:
                logger.info(
                    "%s: %d records, phone=%d/%d, email=%d/%d, website=%d/%d",
                    site, t,
                    rates["phone"], t, rates["email"], t, rates["website"], t,
                )

        # Log byte totals
        if self._bytes_fetched:
            per_target = ", ".join(f"{k}={v:,}B" for k, v in self._bytes_fetched.items())
            total = sum(self._bytes_fetched.values())
            logger.info("Bytes fetched - %s | total=%s", per_target, f"{total:,}B")

        # JustDial summary
        blocked_ips = self._jd_stats.get("blocked_ips", set())
        blocked = self._jd_stats.get("blocked", 0)
        succeeded = self._jd_stats.get("succeeded", 0)
        distinct_blocked_ips = len(blocked_ips)
        if distinct_blocked_ips + blocked + succeeded > 0:
            logger.info(
                "JustDial: %d distinct proxy IPs hit block pages, %d blocked events (body<500B), %d succeeded",
                distinct_blocked_ips, blocked, succeeded,
            )
            if succeeded == 0 and distinct_blocked_ips > 0:
                logger.warning(
                    "CONCLUSION: JustDial block is ASN-level — datacenter proxies cannot "
                    "bypass regardless of specific IP. Residential proxy tier required."
                )

        # JD mode report
        logger.info("JustDial mode: %s", self._jd_mode)

        logger.info(
            "Scrape complete: %d total records, %d target errors",
            len(self.all_records), len(self.scrape_errors),
        )


def _source_slug(source_url: str | None) -> str:
    if not source_url:
        return "unknown"
    url = source_url.lower()
    if "justdial" in url:
        return "justdial"
    if "indiamart" in url:
        return "indiamart"
    if "tradeindia" in url:
        return "tradeindia"
    return "unknown"
