"""Site-specific parsers for Justdial, IndiaMART, and TradeIndia.

Each parser extracts structured listing data from page responses.
Uses embedded JSON (__NEXT_DATA__, __INITIAL_STATE__) and CSS selectors
as fallback strategies, extracting all available contact fields.
"""

from dataclasses import dataclass
import json
import logging
import re

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
    """Extract __NEXT_DATA__ JSON from page HTML."""
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


def _extract_initial_state(html: str) -> dict | None:
    """Extract window.__INITIAL_STATE__ JSON from page HTML."""
    idx = html.find("window.__INITIAL_STATE__ = ")
    if idx < 0:
        return None
    start = idx + len("window.__INITIAL_STATE__ = ")
    depth = 0
    end = start
    for i in range(start, len(html)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(html[start:end])
    except json.JSONDecodeError:
        return None


def _safe_str(val, max_len: int = 500) -> str | None:
    if val is None or val == "" or val == "null":
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


def _extract_phone_from_html(html: str) -> str | None:
    """Extract a phone number from detail page HTML using regex."""
    # Indian mobile: +91-XXXXXXXXXX or 0XXXXXXXXXX or XXXXXXXXXX
    patterns = [
        r'(?:\+?91[-\s]?)?[6-9]\d{9}',
        r'\+\d{1,3}[-\s]?\d{1,4}[-\s]?\d{6,8}',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            digits = re.sub(r"[^\d+]", "", m.group(0))
            if len(digits) >= 10:
                return digits[:15]
    # Landline: 0XXX-XXXXXX
    m = re.search(r'0\d{2,4}[-\s]?\d{6,8}', html)
    if m:
        return re.sub(r"[^\d+]", "", m.group(0))[:15]
    return None


def _extract_detail_urls(
    parser_name: str, response, records: list[RawRecord], base_idx: int,
) -> list[tuple[int, str]]:
    """Extract company profile URLs from the listing page response."""
    urls: list[tuple[int, str]] = []
    if parser_name == "parse_indiamart":
        html = _raw_html(response)
        state = _extract_initial_state(html)
        if not state:
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
        for i, card in enumerate(response.css(".top-cont")):
            link_el = card.css(".company-url").first
            if link_el is None:
                continue
            href = link_el.attrib.get("href", "")
            if href:
                url_idx = base_idx + i
                if url_idx < len(records):
                    urls.append((url_idx, href))
    return urls


def _enrich_from_detail_pages(
    session, records: list[RawRecord], targets: list[tuple[int, str]], timeout: int,
):
    """Scrape company profile pages to extract phone numbers.

    Uses the same StealthySession if available; otherwise creates one-off fetches.
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
            if rec.phone:
                continue
            try:
                page_resp = s.fetch(url, wait=1000)
                html = str(page_resp.html_content)
                phone = _extract_phone_from_html(html)
                if phone:
                    records[idx] = RawRecord(
                        company_name=rec.company_name,
                        website=rec.website,
                        email=rec.email,
                        phone=phone,
                        address=rec.address,
                        industry_code=rec.industry_code,
                        source_url=rec.source_url,
                    )
                    logger.info("Enriched %s -> phone=%s", rec.company_name, phone)
            except Exception as exc:
                logger.debug("Failed detail page %s for %s: %s", url, rec.company_name, exc)
    finally:
        if should_close:
            s.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Pagination URL builders
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
    """TradeIndia pagination is client-side only — only first page works."""
    return base_url


# ---------------------------------------------------------------------------
# scrape_target — entry point called by engine
# ---------------------------------------------------------------------------

def scrape_target(target_config: dict) -> list[RawRecord]:
    """Scrape a target site across multiple pages and return all records.

    After collecting listing-page records, enriches those without phone/email
    by scraping individual company profile pages on the source site.
    """
    url = target_config["entry_url"]
    parser_name = target_config.get("parser", "")
    fetch_kwargs = target_config.get("fetch_kwargs", {})
    timeout = fetch_kwargs.get("timeout", 60000)
    pages = target_config.get("pages", 1)
    max_detail = fetch_kwargs.get("max_detail_pages", 15)

    parser_func = PARSER_REGISTRY.get(parser_name)
    if not parser_func:
        raise ValueError(f"Unknown parser: {parser_name}")

    session_options = {
        "timeout": timeout,
        "headless": True,
        "solve_cloudflare": True,
        "load_dom": True,
    }
    proxy = fetch_kwargs.get("proxy")
    if proxy:
        session_options["proxy"] = proxy

    all_records = []
    detail_urls: list[tuple[int, str]] = []

    with StealthySession(**session_options) as session:
        for page in range(1, pages + 1):
            page_url = _build_page_url(parser_name, url, page)
            logger.info("Fetching page %d/%d: %s", page, pages, page_url)
            try:
                response = session.fetch(page_url, timeout=timeout)
                records = parser_func(response, source_url=url)
                all_records.extend(records)
                logger.info("Page %d: got %d records", page, len(records))

                page_detail_urls = _extract_detail_urls(parser_name, response, records, len(all_records) - len(records))
                detail_urls.extend(page_detail_urls)
            except Exception as exc:
                logger.warning("Failed page %d of %s: %s", page, url, exc)

        needy = [(i, u) for i, u in detail_urls if i < len(all_records) and not all_records[i].phone]
        if needy:
            logger.info("Enriching %d records via detail page scraping (max %d)", len(needy), max_detail)
            _enrich_from_detail_pages(session, all_records, needy[:max_detail], timeout)

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


# ===================================================================
# JUSTDIAL PARSER
# ===================================================================

@register_parser("parse_justdial")
def parse_justdial(response, source_url: str = "") -> list[RawRecord]:
    records = []

    # Strategy 1: Extract from __NEXT_DATA__
    html = _raw_html(response)
    next_data = _extract_next_data(html)
    if next_data:
        records = _parse_jd_from_next_data(next_data, source_url)

    if records:
        return records

    # Strategy 2: CSS selectors (fallback for non-JS rendered)
    records = _parse_jd_from_css(response, source_url)
    if records:
        return records

    logger.warning("Justdial: no listing data found via any strategy")
    return []


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

    # Build column name -> index map
    col_index = {col: i for i, col in enumerate(columns)} if columns else {}
    # Also support numeric index access by column position
    col_by_index = {}

    records = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue

        # Helper to get by column name or fallback to index
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

        # Combine address components
        full_address = ", ".join(filter(None, [address, area, city]))

        # Try extracting bd_params misc field (alternate phone)
        bd_raw = _get("bd_params")
        if bd_raw and bd_raw != "null":
            try:
                bd = json.loads(bd_raw) if isinstance(bd_raw, str) else bd_raw
                misc_phone = bd.get("cmp_params", {}).get("misc", "")
                if misc_phone and not phone:
                    phone = str(misc_phone)
            except (json.JSONDecodeError, AttributeError):
                pass

        # pincode
        pincode = _get("pincode")

        # Rating (for reference)
        rating = _get("compRating")

        records.append(RawRecord(
            company_name=name,
            phone=_clean_phone(phone) or None,
            address=_safe_str(full_address),
            industry_code=_safe_str(biz_type),
            source_url=source_url,
        ))

    if records:
        logger.info("Justdial: extracted %d records from __NEXT_DATA__", len(records))
    return records


def _parse_jd_from_css(response, source_url: str) -> list[RawRecord]:
    records = []
    for card in response.css(".jf-listing-card, [class*='listing-card'], .slideshow-listing-card"):
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


def _clean_phone(phone: str) -> str | None:
    phone = phone.strip()
    if not phone or phone == "0" or phone == "-":
        return None
    digits = re.sub(r"[^\d+]", "", phone)
    if not digits or len(digits) < 7:
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
    if state:
        records = _parse_im_from_state(state, source_url)

    if records:
        return records

    # Strategy 2: CSS selectors
    records = _parse_im_from_css(response, source_url)
    if records:
        return records

    logger.warning("IndiaMART: no listing data found")
    return []


def _parse_im_from_state(state: dict, source_url: str) -> list[RawRecord]:
    # Main listing data
    items = state.get("data", [])
    if not items:
        return []

    # Phone numbers from promoted listings
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

        # s_url is seller profile on IndiaMART, not their own website
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

    logger.info("IndiaMART: extracted %d records from __INITIAL_STATE__", len(records))
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

        # Phone sometimes in "call now" buttons
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


# ===================================================================
# TRADEINDIA PARSER
# ===================================================================

@register_parser("parse_tradeindia")
def parse_tradeindia(response, source_url: str = "") -> list[RawRecord]:
    """Parse TradeIndia listing page.

    Two sections:
      - Company cards (.top-cont) with company name, city, business type
      - Product cards (.product-info-cnt) with product names/descriptions

    We extract from the company card section for clean company records.
    """
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

        records.append(RawRecord(
            company_name=name[:200],
            address=_safe_str(city),
            industry_code=_safe_str(biz, max_len=200),
            source_url=source_url,
        ))

    if records:
        logger.info("TradeIndia: extracted %d records from company cards", len(records))
    else:
        logger.warning("TradeIndia: no listing data found")
    return records
