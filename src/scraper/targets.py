from dataclasses import dataclass
import json
import logging
import re

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


def _raw_html(response) -> str:
    """Get raw HTML string from a Scrapling response."""
    if raw := getattr(response, "html_content", None):
        return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return str(response.text)


def scrape_target(target_config: dict) -> list[RawRecord]:
    url = target_config["entry_url"]
    parser_name = target_config.get("parser", "")
    fetch_kwargs = target_config.get("fetch_kwargs", {})
    timeout = fetch_kwargs.get("timeout", 30000)

    parser_func = PARSER_REGISTRY.get(parser_name)
    if not parser_func:
        raise ValueError(f"Unknown parser: {parser_name}")

    from src.scraper.engine import fetch_with_retry
    response = fetch_with_retry(url, timeout=timeout)
    return parser_func(response, source_url=url)


# ---------------------------------------------------------------------------
# Example / test parser
# ---------------------------------------------------------------------------

@register_parser("parse_example_directory")
def parse_example_directory(response, source_url: str = "") -> list[RawRecord]:
    records = []
    for listing in response.css(".listing"):
        website_el = listing.css(".website").first
        record = RawRecord(
            company_name=listing.css(".company-name").get("").strip(),
            website=website_el.attrib.get("href", "") if website_el else "",
            email=listing.css(".email").get("").strip(),
            phone=listing.css(".phone").get("").strip(),
            address=listing.css(".address").get("").strip(),
            industry_code=listing.css(".industry").get("").strip(),
            source_url=source_url,
        )
        if record.company_name:
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# Justdial — extracts embedded Next.js page-props JSON
# ---------------------------------------------------------------------------

JD_COL_MAP = {
    "company_name": 1,
    "phone": 15,        # VNumber
    "address": 3,       # NewAddress
    "city": 18,
    "industry_code": 14,  # type
    "rating": 7,        # compRating
}


@register_parser("parse_justdial")
def parse_justdial(response, source_url: str = "") -> list[RawRecord]:
    html = _raw_html(response)

    # Find the largest <script> blob containing "listData"
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        body = m.group(1).strip()
        if '"listData"' not in body or len(body) < 5000:
            continue

        # It may be raw JSON or assigned to window.xxx
        clean = body.rstrip(";").strip()
        data = None
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            for obj in re.finditer(r'(\{(?:[^{}]|(?:\{[^{}]*\}))*\})', clean):
                try:
                    candidate = json.loads(obj.group(1))
                    if "props" in candidate:
                        data = candidate
                        break
                except json.JSONDecodeError:
                    continue

        if data is None:
            continue

        results = data.get("props", {}).get("pageProps", {}).get("listData", {}).get("results", {})
        columns = results.get("columns", []) or []
        rows = results.get("data", [])
        if not rows:
            continue

        records = []
        for row in rows:
            name = row[JD_COL_MAP["company_name"]] if len(row) > JD_COL_MAP["company_name"] else ""
            phone = row[JD_COL_MAP["phone"]] if len(row) > JD_COL_MAP["phone"] else ""
            address = row[JD_COL_MAP["address"]] if len(row) > JD_COL_MAP["address"] else ""
            industry = row[JD_COL_MAP["industry_code"]] if len(row) > JD_COL_MAP["industry_code"] else ""

            if not name:
                continue

            records.append(RawRecord(
                company_name=name,
                phone=phone or None,
                address=address or None,
                industry_code=industry or None,
                source_url=source_url,
            ))

        logger.info("Justdial: extracted %d records", len(records))
        return records

    logger.warning("Justdial: no embedded listing data found")
    return []


# ---------------------------------------------------------------------------
# IndiaMART — extracts __INITIAL_STATE__ JSON
# ---------------------------------------------------------------------------

@register_parser("parse_indiamart")
def parse_indiamart(response, source_url: str = "") -> list[RawRecord]:
    html = _raw_html(response)

    idx = html.find("window.__INITIAL_STATE__ = ")
    if idx < 0:
        logger.warning("IndiaMART: __INITIAL_STATE__ not found")
        return []

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
        state = json.loads(html[start:end])
    except json.JSONDecodeError as e:
        logger.warning("IndiaMART: failed to parse __INITIAL_STATE__: %s", e)
        return []

    items = state.get("data", [])
    if not items:
        logger.warning("IndiaMART: no data items in __INITIAL_STATE__")
        return []

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("CMP", "") or ""
        phone = item.get("c_ct", "") or ""
        address = item.get("ad", "") or ""
        city = item.get("city", "") or ""
        website = item.get("s_url", "") or ""
        description = item.get("ds", "") or ""

        if not name:
            continue

        # s_url is often an IndiaMART profile page; keep only real company domains
        web = website or None
        if web and "indiamart.com" in web:
            web = None

        full_address = f"{address}, {city}".strip(", ") if address and city else (address or city or "")

        records.append(RawRecord(
            company_name=name,
            phone=phone or None,
            address=full_address or None,
            website=web,
            industry_code=description[:200] or None,
            source_url=source_url,
        ))

    logger.info("IndiaMART: extracted %d records", len(records))
    return records


# ---------------------------------------------------------------------------
# TradeIndia — CSS-selector based on .top-cont listing cards
# ---------------------------------------------------------------------------

@register_parser("parse_tradeindia")
def parse_tradeindia(response, source_url: str = "") -> list[RawRecord]:
    cards = response.css(".top-cont")
    if not cards:
        logger.warning("TradeIndia: no .top-cont cards found")
        return []

    records = []
    for card in cards:
        name_el = card.css(".company-url").first
        if name_el is None:
            continue
        name = name_el.text.strip() if name_el.text else ""
        if not name:
            continue

        # City is the second h3 child
        h3s = card.find_all("h3")
        city = h3s[1].text.strip() if len(h3s) > 1 and h3s[1].text else ""

        # Business type
        biz_type_el = card.css(".business-type span + span").first
        biz_type = biz_type_el.text.strip() if biz_type_el and biz_type_el.text else ""

        records.append(RawRecord(
            company_name=name,
            address=city or None,
            industry_code=biz_type or None,
            source_url=source_url,
        ))

    logger.info("TradeIndia: extracted %d records", len(records))
    return records
