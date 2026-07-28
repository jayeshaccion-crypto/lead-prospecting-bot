from dataclasses import dataclass


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


@register_parser("parse_justdial")
def parse_justdial(response, source_url: str = "") -> list[RawRecord]:
    records = []
    for listing in response.css(".jca-info"):
        name_el = listing.css(".jcnn").first
        website_el = listing.css(".jdbm a").first
        email_el = listing.css(".jcem").first
        phone_el = listing.css(".jcpn").first
        address_el = listing.css(".jca-detail").first
        record = RawRecord(
            company_name=name_el.get("").strip() if name_el else "",
            website=website_el.attrib.get("href", "") if website_el else "",
            email=email_el.get("").strip() if email_el else None,
            phone=phone_el.get("").strip() if phone_el else None,
            address=address_el.get("").strip() if address_el else None,
            industry_code="",
            source_url=source_url,
        )
        if record.company_name:
            records.append(record)
    return records


@register_parser("parse_indiamart")
def parse_indiamart(response, source_url: str = "") -> list[RawRecord]:
    records = []
    for listing in response.css(".catlg"):
        name_el = listing.css(".heading").first
        phone_el = listing.css(".number").first
        address_el = listing.css(".address").first
        record = RawRecord(
            company_name=name_el.get("").strip() if name_el else "",
            website="",
            email=None,
            phone=phone_el.get("").strip() if phone_el else None,
            address=address_el.get("").strip() if address_el else None,
            industry_code="",
            source_url=source_url,
        )
        if record.company_name:
            records.append(record)
    return records


@register_parser("parse_tradeindia")
def parse_tradeindia(response, source_url: str = "") -> list[RawRecord]:
    records = []
    for listing in response.css(".company_listing"):
        name_el = listing.css(".company_name").first
        phone_el = listing.css(".phone_no").first
        address_el = listing.css(".address").first
        record = RawRecord(
            company_name=name_el.get("").strip() if name_el else "",
            website="",
            email=None,
            phone=phone_el.get("").strip() if phone_el else None,
            address=address_el.get("").strip() if address_el else None,
            industry_code="",
            source_url=source_url,
        )
        if record.company_name:
            records.append(record)
    return records
