"""Site-specific parsers for Justdial, IndiaMART, and TradeIndia.

Each parser extracts structured listing data from page responses.
Uses capture_xhr (Justdial), embedded JSON, regex-based text extraction,
and find_similar() as layered strategies — never assigns directory
site URLs as company websites.
"""

from dataclasses import dataclass
import json
import logging
import re
import time
from urllib.parse import urlparse

from scrapling.fetchers import StealthySession

logger = logging.getLogger(__name__)


@dataclass
class RawRecord:
    company_name: str
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    industry_code: str | None = None
    source_url: str | None = None


PARSER_REGISTRY: dict[str, callable] = {}

DIRECTORY_DOMAINS = {
    "facebook.com", "twitter.com", "linkedin.com", "instagram.com",
    "youtube.com", "justdial.com", "indiamart.com", "tradeindia.com",
    "google.com", "whatsapp.com", "googletagmanager.com", "schema.org",
}

# Site-wide contact values that appear on every page of a directory site
# Enrichment must reject these — they are not company-specific.
KNOWN_SITE_WIDE_PHONES: set[str] = {"01146710423"}
KNOWN_SITE_WIDE_EMAILS: set[str] = {"helpdesk@tradeindia.com"}


def register_parser(name: str):
    def decorator(func):
        PARSER_REGISTRY[name] = func
        return func
    return decorator


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def _raw_html(response) -> str:
    if raw := getattr(response, "html_content", None):
        return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return str(response.text)


def _extract_next_data(html: str) -> dict | None:
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_initial_state(html: str) -> dict | list | None:
    for prefix in ("window.__INITIAL_STATE__ = ", "window.__PRELOADED_STATE__ = "):
        idx = html.find(prefix)
        if idx < 0:
            continue
        start = idx + len(prefix)
        first = html[start]
        if first == "{":
            open_b, close_b = "{", "}"
        elif first == "[":
            open_b, close_b = "[", "]"
        else:
            continue
        depth = 0
        end = start
        for i in range(start, len(html)):
            c = html[i]
            if c == open_b:
                depth += 1
            elif c == close_b:
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            return json.loads(html[start:end])
        except json.JSONDecodeError:
            return None
    return None


def _extract_json_ld(html: str) -> list[dict]:
    """Extract all JSON-LD structured data blocks from the page."""
    results = []
    for m in re.finditer(
        r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            data = json.loads(m.group(1))
            results.append(data)
        except json.JSONDecodeError:
            continue
    return results


def _safe_str(val, max_len: int = 1000) -> str | None:
    if val is None or val == "" or val == "null":
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


# ---------------------------------------------------------------------------
# General text-based extraction
# ---------------------------------------------------------------------------

RFC_5322_LITE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def _extract_emails_from_text(text: str) -> list[str]:
    return RFC_5322_LITE.findall(text)


def _is_directory_domain(domain: str) -> bool:
    domain = domain.lower().strip()
    if "://" in domain:
        parsed = urlparse(domain)
        domain = parsed.hostname or domain
    domain = domain.removeprefix("www.").split(":")[0]
    return any(domain == d or domain.endswith("." + d) for d in DIRECTORY_DOMAINS)


def _extract_websites_from_text(text: str) -> list[str]:
    """Extract company website URLs, filtering out directory/social domains."""
    urls = re.findall(r'https?://[-\w.%+]+[-\w/?=&+#]*', text)
    seen = set()
    result = []
    for url in urls:
        m = re.match(r'https?://([^/?#]+)', url)
        if not m:
            continue
        domain = m.group(1).lower().removeprefix("www.")
        if _is_directory_domain(domain):
            continue
        if not domain.count(".") >= 1:
            continue
        clean = url.split("?")[0].rstrip("/")
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _extract_phone_from_html(html: str) -> str | None:
    patterns = [
        r'(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)',
        r'(?<!\d)\+\d{1,3}[-\s]?\d{1,4}[-\s]?\d{6,8}(?!\d)',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            digits = re.sub(r"[^\d+]", "", m.group(0))
            if len(digits) >= 10:
                return digits[:15]
    m = re.search(r'(?<!\d)0\d{2,4}[-\s]?\d{6,8}(?!\d)', html)
    if m:
        return re.sub(r"[^\d+]", "", m.group(0))[:15]
    return None


def _extract_xhr_data(response) -> list[dict] | None:
    """Extract listing data from captured XHR responses (Justdial API).

    Prefers XHRs whose URL matches the target site API pattern over generic
    XHRs (analytics, tracking, etc.).
    """
    xhr_list = getattr(response, "captured_xhr", None)
    if not xhr_list:
        return None

    def _parse_xhr(xhr) -> list[dict] | None:
        body = getattr(xhr, "body", None) or getattr(xhr, "response", None) or ""
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        if not body:
            return None
        try:
            data = json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        results = (
            data.get("data", {}).get("searchOutput", {}).get("results", [])
            or data.get("results", [])
            or data.get("listData", [])
        )
        if not results:
            return None
        return [r for r in results if isinstance(r, dict)]

    matched: list[tuple[list[dict], str]] = []
    unmatched: list[list[dict]] = []

    for xhr in xhr_list:
        parsed = _parse_xhr(xhr)
        if parsed is None:
            continue
        url = (getattr(xhr, "url", "") or "").lower()
        if url and "justdial" in url:
            matched.append((parsed, url))
        else:
            unmatched.append(parsed)

    # Return best match: highest priority is Justdial API XHR
    if matched:
        return matched[0][0]
    if unmatched:
        return unmatched[0]
    return None


# ---------------------------------------------------------------------------
# find_similar() based card locator
# ---------------------------------------------------------------------------

def _find_cards_via_similarity(response, selectors: list[str]) -> list:
    for sel in selectors:
        example = response.css(sel).first
        if example is not None:
            similar = example.find_similar()
            if similar:
                logger.info("find_similar() found %d cards via selector '%s'", len(similar), sel)
                return list(similar)
    return []


# ---------------------------------------------------------------------------
# Detail URL extraction
# ---------------------------------------------------------------------------

def _extract_detail_urls(
    parser_name: str, response, records: list[RawRecord], base_idx: int,
) -> list[tuple[int, str]]:
    urls: list[tuple[int, str]] = []
    html = _raw_html(response)

    if parser_name == "parse_indiamart":
        state = _extract_initial_state(html)
        if not state or not isinstance(state, dict):
            return urls
        items = state.get("data", [])
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            s_url = (item.get("s_url") or "").strip()
            if s_url and "indiamart.com" in s_url:
                url_idx = base_idx + i
                if url_idx < len(records):
                    profile_url = s_url.split("?")[0].rstrip("/") + "/"
                    urls.append((url_idx, profile_url))

    elif parser_name == "parse_tradeindia":
        for i, card in enumerate(response.css(".top-cont, [class*='company-card'], .card-list > div")):
            for sel in [".company-url a", ".company-url", "a[href*='tradeindia.com']", "h2 a", "h3 a"]:
                link_el = card.css(sel).first
                if link_el is not None:
                    href = link_el.attrib.get("href", "")
                    if href and "tradeindia.com" in href:
                        url_idx = base_idx + i
                        if url_idx < len(records):
                            full = href if href.startswith("http") else response.urljoin(href) if hasattr(response, "urljoin") else href
                            urls.append((url_idx, full))
                        break

    elif parser_name == "parse_justdial":
        for i, card in enumerate(response.css('[class*="listing-card"], [class*="card"], .jf-listing-card')):
            for sel in ["a[href*='justdial.com'][href*='/']", "a[href]"]:
                link_el = card.css(sel).first
                if link_el is not None:
                    href = link_el.attrib.get("href", "")
                    if href and "justdial.com" in href and not href.endswith("#"):
                        url_idx = base_idx + i
                        if url_idx < len(records):
                            full = href if href.startswith("http") else response.urljoin(href) if hasattr(response, "urljoin") else href
                            urls.append((url_idx, full))
                        break

    return urls


# ---------------------------------------------------------------------------
# Detail page enrichment
# ---------------------------------------------------------------------------

def _enrich_from_detail_pages(
    session, records: list[RawRecord], targets: list[tuple[int, str]], timeout: int,
):
    """Scrape company profile pages to extract phone, email, and website.

    Preserves the original source_url (listing page) — does NOT overwrite
    it with the detail page URL. Only sets website to external company
    domains (never directory domains). Rejects known site-wide values
    (e.g. helpdesk@tradeindia.com, 01146710423) that appear on every page.
    """
    should_close = session is None
    s = session or StealthySession(
        headless=True, solve_cloudflare=True, timeout=timeout, load_dom=True,
    )
    try:
        if should_close:
            s.__enter__()
        for idx, url in targets:
            if idx >= len(records):
                continue
            rec = records[idx]
            if rec.phone and rec.email:
                continue
            try:
                page_resp = s.fetch(url, wait=1000)
                if page_resp.html_content is None:
                    logger.debug("No body for detail page %s — skipping enrichment", url)
                    continue
                html = str(page_resp.html_content)
                if not html or html.strip() in ("None", ""):
                    logger.debug("Empty body for detail page %s — skipping enrichment", url)
                    continue

                detail_phone = _extract_phone_from_html(html)
                emails = _extract_emails_from_text(html)
                detail_email = emails[0] if emails else None
                websites = _extract_websites_from_text(html)
                detail_website = websites[0] if websites else None

                # Reject known site-wide values that are not company-specific
                if detail_phone and detail_phone in KNOWN_SITE_WIDE_PHONES:
                    detail_phone = None
                if detail_email and detail_email in KNOWN_SITE_WIDE_EMAILS:
                    detail_email = None

                phone = detail_phone or rec.phone
                email = detail_email or rec.email
                website = detail_website or rec.website

                if phone != rec.phone or email != rec.email or website != rec.website:
                    records[idx] = RawRecord(
                        company_name=rec.company_name,
                        website=website,
                        email=email,
                        phone=phone,
                        address=rec.address,
                        industry_code=rec.industry_code,
                        source_url=rec.source_url,
                    )
                    logger.info(
                        "Enriched %s -> phone=%s email=%s website=%s",
                        rec.company_name, phone or "—", email or "—", website or "—",
                    )
            except Exception as exc:
                logger.debug("Failed detail page %s for %s: %s", url, rec.company_name, exc)
            finally:
                time.sleep(0.5)
    finally:
        if should_close:
            s.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# httpx enrichment fallback for IndiaMART (browser detail pages fail)
# ---------------------------------------------------------------------------

def _enrich_indiamart_via_httpx(records: list[RawRecord]) -> int:
    """Enrich IndiaMART records with phone numbers from detail pages via httpx.

    IndiaMART detail pages block browser body retrieval but serve HTML fine
    to plain httpx requests. This extracts phones from the raw HTML.
    """
    needy = [(i, r) for i, r in enumerate(records) if not r.phone]
    if not needy:
        return 0

    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available — skipping IndiaMART enrichment")
        return 0

    # Re-fetch listing page to get detail URLs (avoid storing in session)
    detail_targets: list[tuple[int, str]] = []
    try:
        from scrapling.fetchers import StealthySession
        with StealthySession(headless=True, solve_cloudflare=True, timeout=60000, load_dom=True, network_idle=True) as s:
            resp = s.fetch(records[0].source_url or "", wait=3000)
            detail_targets = _extract_detail_urls("parse_indiamart", resp, records, 0)
    except Exception as exc:
        logger.debug("Failed to get IndiaMART detail URLs: %s", exc)
        return 0

    enriched = 0
    with httpx.Client(follow_redirects=True, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }) as client:
        for idx, url in detail_targets:
            if idx >= len(records):
                continue
            rec = records[idx]
            if rec.phone:
                continue
            try:
                r = client.get(url)
                phones = re.findall(r"(?<!\d)(?:\+?91[-\s]?)?[6-9]\d{9}(?!\d)", r.text)
                if phones:
                    digits = re.sub(r"[^\d+]", "", phones[0])[:15]
                    records[idx] = RawRecord(
                        company_name=rec.company_name,
                        website=rec.website,
                        email=rec.email,
                        phone=digits,
                        address=rec.address,
                        industry_code=rec.industry_code,
                        source_url=rec.source_url,
                    )
                    enriched += 1
                    logger.info("httpx enrich: +phone for %s: %s", rec.company_name, digits)
            except Exception as exc:
                logger.debug("httpx failed for %s: %s", url, exc)

    if enriched:
        logger.info("httpx enriched %d IndiaMART records with phone", enriched)
    return enriched


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def _jd_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    return f"{base_url.rstrip('/')}?page={page}"


def _im_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    return f"{base_url.rstrip('/')}?page={page}"


def _ti_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    return f"{base_url.rstrip('/')}?page={page}"


# ---------------------------------------------------------------------------
# scrape_target — entry point
# ---------------------------------------------------------------------------

def scrape_target(target_config: dict) -> list[RawRecord]:
    url = target_config["entry_url"]
    parser_name = target_config.get("parser", "")
    fetch_kwargs = target_config.get("fetch_kwargs", {})
    timeout = fetch_kwargs.get("timeout", 90000)
    pages = target_config.get("pages", 1)
    max_detail = fetch_kwargs.get("max_detail_pages", 15)
    page_delay = fetch_kwargs.get("page_delay", 2.0)

    parser_func = PARSER_REGISTRY.get(parser_name)
    if not parser_func:
        raise ValueError(f"Unknown parser: {parser_name}")

    session_options = {
        "timeout": timeout,
        "headless": True,
        "solve_cloudflare": True,
        "load_dom": True,
        "network_idle": True,
        "capture_xhr": r".*",
    }
    proxy = fetch_kwargs.get("proxy")
    if proxy:
        session_options["proxy"] = proxy

    all_records = []
    detail_urls: list[tuple[int, str]] = []

    with StealthySession(**session_options) as session:
        for page in range(1, pages + 1):
            page_url = _build_page_url(parser_name, url, page)

            max_attempts = 3
            for attempt in range(max_attempts):
                logger.info("Fetching page %d/%d (attempt %d/%d): %s", page, pages, attempt + 1, max_attempts, page_url)
                try:
                    response = session.fetch(
                        page_url, timeout=timeout,
                        wait=max(int(page_delay * 1000), 2000),
                    )
                    records = parser_func(response, source_url=url)

                    if records:
                        all_records.extend(records)
                        logger.info("Page %d: got %d records", page, len(records))
                        page_detail_urls = _extract_detail_urls(parser_name, response, all_records, len(all_records) - len(records))
                        detail_urls.extend(page_detail_urls)
                        break  # success, move to next page

                    # 0 records — check if rate-limited or transient
                    status = getattr(response, "status_code", getattr(response, "status", 0))
                    if status == 429:
                        wait_sec = 30 * (attempt + 1)
                        logger.warning("429 rate limit on %s, waiting %ds before retry", page_url, wait_sec)
                        time.sleep(wait_sec)
                    else:
                        logger.info("Empty response from %s (status=%s, attempt %d/%d), retrying...",
                                     page_url, status, attempt + 1, max_attempts)
                        if attempt < max_attempts - 1:
                            time.sleep(5)
                except Exception as exc:
                    logger.warning("Failed page %d of %s (attempt %d/%d): %s", page, url, attempt + 1, max_attempts, exc)
                    if attempt < max_attempts - 1:
                        time.sleep(10)

            if page < pages:
                time.sleep(page_delay)

        needy = [
            (i, u) for i, u in detail_urls
            if i < len(all_records) and not (all_records[i].phone and all_records[i].email)
        ]
        if needy:
            logger.info("Enriching %d records via detail page scraping (max %d)", len(needy), max_detail)
            _enrich_from_detail_pages(session, all_records, needy[:max_detail], timeout)

    # httpx enrichment fallback for IndiaMART (browser detail pages fail to retrieve body)
    if parser_name == "parse_indiamart":
        _enrich_indiamart_via_httpx(all_records)

    return all_records


def _build_page_url(parser_name: str, base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    builders = {
        "parse_justdial": _jd_page_url,
        "parse_indiamart": _im_page_url,
        "parse_tradeindia": _ti_page_url,
    }
    builder = builders.get(parser_name)
    return builder(base_url, page) if builder else base_url


# ---------------------------------------------------------------------------
# Example parser (demo / testing)
# ---------------------------------------------------------------------------

def parse_example_directory(response, source_url=""):
    listings = response.css(".listing")
    records = []
    for listing in listings:
        name_el = listing.css(".company-name").first
        if name_el is None:
            continue
        name = name_el.text.strip() if name_el.text else ""
        if not name:
            continue

        website = None
        website_el = listing.css(".website").first
        if website_el is not None:
            website = website_el.attrib.get("href")

        email_el = listing.css(".email").first
        email = email_el.text.strip() if email_el and email_el.text else None

        phone_el = listing.css(".phone").first
        phone = phone_el.text.strip() if phone_el and phone_el.text else None

        address_el = listing.css(".address").first
        address = address_el.text.strip() if address_el and address_el.text else None

        industry_el = listing.css(".industry").first
        industry = industry_el.text.strip() if industry_el and industry_el.text else None

        records.append(RawRecord(
            company_name=name,
            website=website,
            email=email,
            phone=phone,
            address=address,
            industry_code=industry,
            source_url=source_url,
        ))
    return records


# ===================================================================
# JUSTDIAL PARSER
# ===================================================================

@register_parser("parse_justdial")
def parse_justdial(response, source_url: str = "") -> list[RawRecord]:
    """Justdial parser with multi-strategy extraction.

    Strategy order:
      1. XHR API data (capture_xhr) — richest, contains all fields
      2. __NEXT_DATA__ JSON embedded in page
      3. JSON-LD structured data
      4. find_similar() card discovery
      5. CSS selector fallback
      6. Generic text extraction
    """
    records = []

    # Strategy 1: XHR API data (captured via StealthySession capture_xhr)
    xhr_data = _extract_xhr_data(response)
    if xhr_data:
        records = _parse_jd_from_xhr(xhr_data, source_url)
        if records:
            return records

    html = _raw_html(response)

    # Strategy 2: __NEXT_DATA__ JSON
    next_data = _extract_next_data(html)
    if next_data:
        records = _parse_jd_from_next_data(next_data, source_url)
        if records:
            return records

    # Strategy 3: JSON-LD
    ld = _extract_json_ld(html)
    if ld:
        records = _parse_jd_from_json_ld(ld, source_url)
        if records:
            return records

    # Strategy 4: find_similar()
    records = _parse_jd_via_similarity(response, source_url)
    if records:
        return records

    # Strategy 5: CSS selectors
    records = _parse_jd_from_css(response, source_url)
    if records:
        return records

    # Strategy 6: Generic text extraction
    records = _parse_jd_from_text(html, source_url)
    if records:
        return records

    logger.warning("Justdial: no listing data found via any strategy")
    return []


def _parse_jd_from_xhr(data: list[dict], source_url: str) -> list[RawRecord]:
    """Parse listing data from Justdial's internal XHR API response."""
    records = []
    for item in data:
        name = (item.get("name") or item.get("title") or "").strip()
        if not name:
            continue

        phone = (item.get("contactNumber") or item.get("phone") or item.get("VNumber") or "").strip()

        address_parts = filter(None, [
            (item.get("address") or item.get("NewAddress") or "").strip(),
            (item.get("area") or "").strip(),
            (item.get("city") or "").strip(),
        ])
        address = ", ".join(address_parts)

        industry = (item.get("type") or item.get("category") or item.get("businessType") or "").strip()
        website = (item.get("website") or "").strip()
        if website and not website.startswith("http"):
            website = "https://" + website
        if _is_directory_domain(website or ""):
            website = None

        email = (item.get("email") or "").strip()

        records.append(RawRecord(
            company_name=name,
            website=website or None,
            email=email or None,
            phone=_clean_phone(phone) or None,
            address=_safe_str(address),
            industry_code=_safe_str(industry),
            source_url=source_url,
        ))

    if records:
        logger.info("Justdial: extracted %d records from XHR API data", len(records))
    return records


def _parse_jd_from_next_data(next_data: dict, source_url: str) -> list[RawRecord]:
    try:
        pp = next_data.get("props", {}).get("pageProps", {})
        list_data = pp.get("listData", pp.get("listingData", {}))
        results = list_data.get("results", list_data)
        columns = results.get("columns", [])
        rows = results.get("data", [])
    except AttributeError:
        return []

    if not rows:
        return []

    col_index = {col: i for i, col in enumerate(columns)} if columns else {}

    records = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue

        def _get(name_or_idx, default=""):
            if isinstance(name_or_idx, str) and name_or_idx in col_index:
                idx = col_index[name_or_idx]
            elif isinstance(name_or_idx, int):
                idx = name_or_idx
            else:
                return default
            return str(row[idx]).strip() if idx < len(row) and row[idx] is not None else default

        name = _get("name", "")
        if not name:
            continue

        phone = _get("VNumber") or ""
        address = _get("NewAddress") or ""
        area = _get("area") or ""
        city = _get("city") or ""
        biz_type = _get("type") or ""
        full_address = ", ".join(filter(None, [address, area, city]))

        email = _get("email") or None
        website = _get("website") or None
        if website and not website.startswith("http"):
            website = "https://" + website
        if website and _is_directory_domain(website):
            website = None

        bd_raw = _get("bd_params")
        if bd_raw and bd_raw != "null":
            try:
                bd = json.loads(bd_raw) if isinstance(bd_raw, str) else bd_raw
                cmp = bd.get("cmp_params", {})
                if not email:
                    email = cmp.get("email") or None
                if not website:
                    w = cmp.get("website") or None
                    if w:
                        website = "https://" + w if not w.startswith("http") else w
                        if _is_directory_domain(website):
                            website = None
                if not phone:
                    misc = cmp.get("misc", "")
                    if misc:
                        phone = str(misc)
            except (json.JSONDecodeError, AttributeError):
                pass

        records.append(RawRecord(
            company_name=name,
            website=website,
            email=email,
            phone=_clean_phone(phone) or None,
            address=_safe_str(full_address),
            industry_code=_safe_str(biz_type),
            source_url=source_url,
        ))

    if records:
        logger.info("Justdial: extracted %d records from __NEXT_DATA__", len(records))
    return records


def _parse_jd_from_json_ld(ld: list[dict], source_url: str) -> list[RawRecord]:
    """Extract business listings from JSON-LD structured data."""
    records = []
    for item in ld:
        if not isinstance(item, dict):
            continue
        graph = item if isinstance(item.get("@graph"), list) else [item]
        for entry in graph:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            if entry.get("@type") not in ("LocalBusiness", "Organization", "Business", None):
                continue

            website = (entry.get("url") or "").strip()
            if website and _is_directory_domain(website):
                website = None

            email = ""
            for c in [entry.get("contactPoint")] if isinstance(entry.get("contactPoint"), dict) else (entry.get("contactPoint") or []):
                if isinstance(c, dict):
                    e = c.get("email", "")
                    if e:
                        email = e
                        break

            address_obj = entry.get("address", {}) or {}
            if isinstance(address_obj, dict):
                address = ", ".join(filter(None, [
                    address_obj.get("streetAddress", "").strip(),
                    address_obj.get("addressLocality", "").strip(),
                    address_obj.get("addressRegion", "").strip(),
                ]))
            else:
                address = str(address_obj) if address_obj else ""

            phone = (entry.get("telephone") or "").strip()

            records.append(RawRecord(
                company_name=name,
                website=website or None,
                email=email or None,
                phone=_clean_phone(phone) or None,
                address=_safe_str(address),
                source_url=source_url,
            ))

    if records:
        logger.info("Justdial: extracted %d records from JSON-LD", len(records))
    return records


def _parse_jd_via_similarity(response, source_url: str) -> list[RawRecord]:
    selectors = [
        ".jf-listing-card", "[class*='listing-card']",
        ".slideshow-listing-card", ".store-card",
        "[class*='card'][data-id]", "li[data-id]",
    ]
    cards = _find_cards_via_similarity(response, selectors)
    if not cards:
        return []

    records = []
    for card in cards:
        name_text = card.css("::text").get()
        if not name_text:
            name_el = card.css("h2, h3, .name, [class*='title'], a").first
            name_text = name_el.text if name_el is not None else ""
        name = (name_text or "").strip() if name_text else ""
        if not name:
            continue

        card_html = str(card._root) if hasattr(card, "_root") else ""
        phone = _extract_phone_from_html(card_html) if card_html else None
        emails = _extract_emails_from_text(card_html)
        email = emails[0] if emails else None
        websites = _extract_websites_from_text(card_html)
        website = websites[0] if websites else None

        addr_el = card.css("[class*='address'], .address, [class*='addr']").first
        address = addr_el.text.strip() if addr_el is not None and addr_el.text else ""

        cat_el = card.css("[class*='category'], .category, [class*='cat']").first
        industry = cat_el.text.strip() if cat_el is not None and cat_el.text else ""

        records.append(RawRecord(
            company_name=name,
            website=website,
            email=email,
            phone=phone,
            address=_safe_str(address),
            industry_code=_safe_str(industry),
            source_url=source_url,
        ))

    if records:
        logger.info("Justdial: extracted %d records via find_similar()", len(records))
    return records


def _parse_jd_from_css(response, source_url: str) -> list[RawRecord]:
    records = []
    selectors = [".jf-listing-card", "[class*='listing-card']", ".slideshow-listing-card"]
    for card in response.css(", ".join(selectors)):
        name_el = card.css(".company-name, .jf-business-name, h2 a, .name a").first
        if name_el is None:
            continue
        name = name_el.text.strip() if name_el.text else ""
        if not name:
            continue

        phone_el = card.css(".call-now, .greenfill_animate.callbutton, span.callcontent").first
        phone = phone_el.text.strip() if phone_el and phone_el.text else ""

        addr_el = card.css(".address, .jf-address, .business-address").first
        address = addr_el.text.strip() if addr_el and addr_el.text else ""

        cat_el = card.css(".category, .jf-category").first
        category = cat_el.text.strip() if cat_el and cat_el.text else ""

        records.append(RawRecord(
            company_name=name,
            phone=_clean_phone(phone) or None,
            address=_safe_str(address),
            industry_code=_safe_str(category),
            source_url=source_url,
        ))

    return records


def _parse_jd_from_text(html: str, source_url: str) -> list[RawRecord]:
    """Fallback: extract business names and contacts from raw HTML using regex."""
    names = re.findall(r'<h2[^>]*data-name[^>]*>([^<]+)</h2>', html)
    if not names:
        names = re.findall(r'"name"\s*:\s*"([^"]+)"', html)
    if not names:
        return []

    records = []
    for name in names:
        name = name.strip()
        if not name or len(name) < 2:
            continue
        phone = _extract_phone_from_html(html)
        emails = _extract_emails_from_text(html)
        websites = _extract_websites_from_text(html)

        records.append(RawRecord(
            company_name=name,
            website=websites[0] if websites else None,
            email=emails[0] if emails else None,
            phone=phone,
            source_url=source_url,
        ))

    if records:
        logger.info("Justdial: extracted %d records via generic text extraction", len(records))
    return records


def _clean_phone(phone: str) -> str | None:
    phone = phone.strip()
    if not phone or phone == "0" or phone == "-":
        return None
    digits = re.sub(r"[^\d+]", "", phone)
    if not digits or len(digits) < 10:
        return None
    return digits[:15]


# ===================================================================
# INDIAMART PARSER
# ===================================================================

@register_parser("parse_indiamart")
def parse_indiamart(response, source_url: str = "") -> list[RawRecord]:
    records = []

    # Strategy 1: __INITIAL_STATE__ JSON
    html = _raw_html(response)
    state = _extract_initial_state(html)
    if isinstance(state, dict):
        records = _parse_im_from_state(state, source_url)

    if records:
        return records

    # Strategy 2: find_similar()
    records = _parse_im_via_similarity(response, source_url)
    if records:
        return records

    # Strategy 3: CSS selectors
    records = _parse_im_from_css(response, source_url)
    if records:
        return records

    # Strategy 4: Generic text extraction
    records = _parse_im_from_text(html, source_url)
    if records:
        return records

    logger.warning("IndiaMART: no listing data found")
    return []


def _parse_im_from_state(state: dict, source_url: str) -> list[RawRecord]:
    items = state.get("data", [])
    if not items:
        return []

    phone_map = {}
    for ad in state.get("plaWidgetData", []):
        if isinstance(ad, dict):
            cname = ad.get("COMPANYNAME", "").strip()
            phone = ad.get("CONTACT_NUMBER", "").strip()
            if cname and phone:
                phone_map[cname] = phone

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("CMP") or "").strip()
        if not name:
            continue

        phone = phone_map.get(name, "")
        address_parts = filter(None, [
            (item.get("ad") or "").strip(),
            (item.get("city") or "").strip(),
            (item.get("g_s") or "").strip(),
        ])
        address = ", ".join(address_parts)
        description = (item.get("ds") or "").strip()

        s_url = (item.get("s_url") or "").strip()
        website = None
        if s_url and "indiamart.com" not in s_url:
            website = s_url

        records.append(RawRecord(
            company_name=name,
            phone=_clean_phone(phone) or None,
            address=_safe_str(address),
            industry_code=_safe_str(description, max_len=300),
            website=website,
            source_url=source_url,
        ))

    if records:
        logger.info("IndiaMART: extracted %d records from __INITIAL_STATE__", len(records))
    return records


def _parse_im_via_similarity(response, source_url: str) -> list[RawRecord]:
    selectors = [
        "li.pCard1", ".card", "[class*='seller-card']",
        ".list-view", "[class*='listing']",
    ]
    cards = _find_cards_via_similarity(response, selectors)
    if not cards:
        return []

    records = []
    for card in cards:
        name_el = card.css("a, [class*='title'], h2, h3").first
        name = ""
        if name_el is not None:
            name = (name_el.text or "").strip()
        if not name:
            continue

        card_html = str(card._root) if hasattr(card, "_root") else ""
        phone = _extract_phone_from_html(card_html) if card_html else None
        emails = _extract_emails_from_text(card_html)
        email = emails[0] if emails else None
        websites = _extract_websites_from_text(card_html)
        website = websites[0] if websites else None

        addr_el = card.css("[class*='addr'], .address").first
        address = addr_el.text.strip() if addr_el is not None and addr_el.text else ""

        desc_el = card.css("[class*='desc'], .ds").first
        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        records.append(RawRecord(
            company_name=name,
            website=website,
            email=email,
            phone=phone,
            address=_safe_str(address),
            industry_code=_safe_str(desc, max_len=300),
            source_url=source_url,
        ))

    if records:
        logger.info("IndiaMART: extracted %d records via find_similar()", len(records))
    return records


def _parse_im_from_css(response, source_url: str) -> list[RawRecord]:
    records = []
    for card in response.css("li.pCard1, .card, [class*='seller-card']"):
        name_el = card.css(".wlc1 a, .company-name, h2 a").first
        if name_el is None:
            continue
        name = name_el.text.strip() if name_el.text else ""
        if not name:
            continue

        addr_el = card.css(".seller-addr span, .address").first
        address = addr_el.text.strip() if addr_el and addr_el.text else ""

        desc_el = card.css(".desc, .product-description, .ds").first
        desc = desc_el.text.strip() if desc_el and desc_el.text else ""

        phone = ""
        call_btn = card.css(".viewmno, .call-now, [class*='call']").first
        if call_btn and call_btn.text:
            raw = call_btn.text.strip()
            if raw and raw != "Call Now":
                phone = raw

        records.append(RawRecord(
            company_name=name,
            phone=_clean_phone(phone) or None,
            address=_safe_str(address),
            industry_code=_safe_str(desc, max_len=300),
            source_url=source_url,
        ))

    return records


def _parse_im_from_text(html: str, source_url: str) -> list[RawRecord]:
    """Fallback: extract company names from __INITIAL_STATE__ or generic patterns."""
    names = re.findall(r'"CMP"\s*:\s*"([^"]+)"', html)
    if not names:
        names = re.findall(r'<h2[^>]*>([^<]+)</h2>', html)
    if not names:
        return []

    seen = set()
    records = []
    for name in names:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        phone = _extract_phone_from_html(html)
        emails = _extract_emails_from_text(html)
        websites = _extract_websites_from_text(html)

        records.append(RawRecord(
            company_name=name,
            website=websites[0] if websites else None,
            email=emails[0] if emails else None,
            phone=phone,
            source_url=source_url,
        ))

    if records:
        logger.info("IndiaMART: extracted %d records via generic text extraction", len(records))
    return records


# ===================================================================
# TRADEINDIA PARSER
# ===================================================================

@register_parser("parse_tradeindia")
def parse_tradeindia(response, source_url: str = "") -> list[RawRecord]:
    records = []

    # Strategy 1: CSS selectors
    records = _parse_ti_from_css(response, source_url)
    if records:
        return records

    # Strategy 2: find_similar()
    records = _parse_ti_via_similarity(response, source_url)
    if records:
        return records

    # Strategy 3: Generic text extraction
    html = _raw_html(response)
    records = _parse_ti_from_text(html, source_url)
    if records:
        return records

    logger.warning("TradeIndia: no listing data found")
    return []


def _parse_ti_from_css(response, source_url: str) -> list[RawRecord]:
    records = []
    for card in response.css(".top-cont"):
        name_el = card.css(".company-url").first
        if name_el is None:
            continue
        name = (name_el.text or "").strip()
        if not name:
            continue

        h3s = card.find_all("h3")
        city = h3s[1].text.strip() if len(h3s) > 1 and h3s[1].text else ""

        biz = ""
        biz_el = card.css(".business-type span + span").first
        if biz_el is None:
            biz_el = card.css(".business-type").first
        if biz_el and biz_el.text:
            biz = biz_el.text.strip()

        card_html = str(card._root) if hasattr(card, "_root") else ""
        phone = _extract_phone_from_html(card_html) if card_html else None
        emails = _extract_emails_from_text(card_html)
        email = emails[0] if emails else None
        websites = _extract_websites_from_text(card_html)
        website = websites[0] if websites else None

        records.append(RawRecord(
            company_name=name[:200],
            website=website,
            email=email,
            phone=phone,
            address=_safe_str(city),
            industry_code=_safe_str(biz, max_len=200),
            source_url=source_url,
        ))

    if records:
        logger.info("TradeIndia: extracted %d records from CSS (phone=%d, email=%d, website=%d)",
                     len(records),
                     sum(1 for r in records if r.phone),
                     sum(1 for r in records if r.email),
                     sum(1 for r in records if r.website))
    return records


def _parse_ti_via_similarity(response, source_url: str) -> list[RawRecord]:
    selectors = [".top-cont", "[class*='company-card']", ".card-list > div"]
    cards = _find_cards_via_similarity(response, selectors)
    if not cards:
        return []

    records = []
    for card in cards:
        name_el = card.css(".company-url, a[href], h2, h3").first
        name = ""
        if name_el is not None:
            name = (name_el.text or "").strip()
        if not name:
            continue

        card_html = str(card._root) if hasattr(card, "_root") else ""
        phone = _extract_phone_from_html(card_html) if card_html else None
        emails = _extract_emails_from_text(card_html)
        email = emails[0] if emails else None
        websites = _extract_websites_from_text(card_html)
        website = websites[0] if websites else None

        h3s = card.find_all("h3")
        city = h3s[1].text.strip() if len(h3s) > 1 and h3s[1].text else ""

        biz = ""
        biz_el = card.css(".business-type, [class*='business']").first
        if biz_el is not None and biz_el.text:
            biz = biz_el.text.strip()

        records.append(RawRecord(
            company_name=name[:200],
            website=website,
            email=email,
            phone=phone,
            address=_safe_str(city),
            industry_code=_safe_str(biz, max_len=200),
            source_url=source_url,
        ))

    if records:
        logger.info("TradeIndia: extracted %d records via find_similar()", len(records))
    return records


def _parse_ti_from_text(html: str, source_url: str) -> list[RawRecord]:
    """Fallback: extract company names from TradeIndia page using regex."""
    names = re.findall(r'<h3[^>]*class="company-url"[^>]*>\s*([^<]+)\s*</h3>', html)
    if not names:
        names = re.findall(r'"company_name"\s*:\s*"([^"]+)"', html)
    if not names:
        return []

    seen = set()
    records = []
    for name in names:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        phone = _extract_phone_from_html(html)
        emails = _extract_emails_from_text(html)
        websites = _extract_websites_from_text(html)

        records.append(RawRecord(
            company_name=name[:200],
            website=websites[0] if websites else None,
            email=emails[0] if emails else None,
            phone=phone,
            source_url=source_url,
        ))

    if records:
        logger.info("TradeIndia: extracted %d records via generic text extraction", len(records))
    return records
