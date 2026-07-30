"""High-level Neo4j graph API for the lead prospecting pipeline."""

import logging
import re
import unicodedata
from hashlib import md5
from typing import Any

from neo4j import GraphDatabase

from .schema import create_schema

logger = logging.getLogger(__name__)

SITE_SOURCES = {
    "justdial.com": "Justdial",
    "indiamart.com": "IndiaMART",
    "tradeindia.com": "TradeIndia",
}


def _dedup_key(company_name: str, website: str | None) -> str:
    raw = f"{company_name}|{website or ''}".strip().lower()
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return md5(raw.encode()).hexdigest()


def _extract_phones(row: dict) -> list[str]:
    phones = set()
    for col in ("phone", "mobile", "phone1", "phone2", "phone3", "phone4", "raw_phone", "alt_phone"):
        raw = row.get(col, "") or ""
        if raw.strip():
            nums = re.findall(r"\d{6,15}", str(raw))
            phones.update(nums)
    return sorted(phones)


def _extract_emails(row: dict) -> list[str]:
    emails = set()
    raw = str(row.get("email", "") or "") + "|" + str(row.get("raw_email", "") or "")
    matches = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw)
    emails.update(m.lower() for m in matches)
    return sorted(emails)


def _source_name(row: dict) -> str:
    url = (row.get("source_url") or row.get("url") or "").lower()
    for domain, name in SITE_SOURCES.items():
        if domain in url:
            return name
    return "Unknown"


def ensure_schema(driver: GraphDatabase.driver):
    create_schema(driver)


def upsert_company(driver: GraphDatabase.driver, row: dict):
    dk = _dedup_key(
        row.get("company_name", "") or "",
        row.get("website"),
    )
    company_name = (row.get("company_name") or "").strip() or "Unknown"
    website = (row.get("website") or "").strip() or None
    address = " ".join(filter(None, [
        row.get("address"),
        row.get("locality"),
        row.get("city"),
    ])).strip() or None
    city = (row.get("city") or "").strip() or None
    industry = (row.get("industry") or row.get("category") or "").strip() or None
    source_url = (row.get("source_url") or row.get("url") or "").strip() or None
    phones = _extract_phones(row)
    emails = _extract_emails(row)
    src_name = _source_name(row)

    industry_code = None
    if industry and industry.strip() not in ("", "N/A", "n/a"):
        industry_code = industry.strip().upper().replace(" ", "_").replace("/", "_")
        if len(industry_code) > 50:
            industry_code = md5(industry_code.encode()).hexdigest()[:16]

    with driver.session() as session:
        session.run(
            """MERGE (c:Company {dedup_key: $dk})
               SET c.company_name = $name,
                   c.website = $website,
                   c.address = $address,
                   c.industry_code = $industry_code,
                   c.source_url = $source_url,
                   c.scraped_at = datetime()
               RETURN c""",
            {"dk": dk, "name": company_name, "website": website,
             "address": address, "industry_code": industry_code,
             "source_url": source_url},
        )

        for phone in phones:
            session.run(
                "MERGE (p:Phone {number: $num}) "
                "WITH p MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:HAS_PHONE]->(p)",
                {"num": phone, "dk": dk},
            )
        for email in emails:
            session.run(
                "MERGE (e:Email {address: $addr}) "
                "WITH e MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:HAS_EMAIL]->(e)",
                {"addr": email, "dk": dk},
            )
        if website:
            session.run(
                "MERGE (w:Website {url: $url}) "
                "WITH w MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:HAS_WEBSITE]->(w)",
                {"url": website, "dk": dk},
            )
        if city:
            session.run(
                "MERGE (l:Location {city: $city}) "
                "WITH l MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:LOCATED_IN]->(l)",
                {"city": city, "dk": dk},
            )
        if industry_code:
            session.run(
                "MERGE (i:Industry {code: $code}) "
                "ON CREATE SET i.name = $name "
                "WITH i MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:BELONGS_TO]->(i)",
                {"code": industry_code, "name": industry, "dk": dk},
            )
        if src_name != "Unknown":
            session.run(
                "MERGE (s:Source {name: $src_name}) "
                "WITH s MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:SOURCED_FROM]->(s)",
                {"src_name": src_name, "dk": dk},
            )


def query_by_location(driver: GraphDatabase.driver, city: str):
    with driver.session() as session:
        result = session.run(
            """MATCH (c:Company)-[:LOCATED_IN]->(l:Location {city: $city})
               OPTIONAL MATCH (c)-[:HAS_PHONE]->(p:Phone)
               OPTIONAL MATCH (c)-[:HAS_EMAIL]->(e:Email)
               OPTIONAL MATCH (c)-[:HAS_WEBSITE]->(w:Website)
               OPTIONAL MATCH (c)-[:BELONGS_TO]->(i:Industry)
               RETURN c.company_name AS company_name,
                      c.website AS website,
                      c.address AS address,
                      collect(DISTINCT p.number) AS phones,
                      collect(DISTINCT e.address) AS emails,
                      collect(DISTINCT w.url) AS websites,
                      i.name AS industry
               ORDER BY c.company_name""",
            {"city": city},
        )
        return list(result)


def query_company_detail(driver: GraphDatabase.driver, company_name: str):
    with driver.session() as session:
        result = session.run(
            """MATCH (c:Company)
               WHERE toLower(c.company_name) CONTAINS toLower($name)
               OPTIONAL MATCH (c)-[:HAS_PHONE]->(p:Phone)
               OPTIONAL MATCH (c)-[:HAS_EMAIL]->(e:Email)
               OPTIONAL MATCH (c)-[:HAS_WEBSITE]->(w:Website)
               OPTIONAL MATCH (c)-[:LOCATED_IN]->(l:Location)
               OPTIONAL MATCH (c)-[:BELONGS_TO]->(i:Industry)
               OPTIONAL MATCH (c)-[:SOURCED_FROM]->(s:Source)
               RETURN c.company_name AS company_name,
                      c.website AS website,
                      c.address AS address,
                      l.city AS city,
                      collect(DISTINCT p.number) AS phones,
                      collect(DISTINCT e.address) AS emails,
                      i.name AS industry,
                      s.name AS source
               ORDER BY c.company_name""",
            {"name": company_name},
        )
        return list(result)


def get_company_count(driver: GraphDatabase.driver) -> int:
    with driver.session() as session:
        result = session.run("MATCH (c:Company) RETURN count(c) AS cnt")
        return result.single()["cnt"]


def get_stats(driver: GraphDatabase.driver) -> dict[str, int]:
    with driver.session() as session:
        stats = {}
        for label in ("Company", "Phone", "Email", "Website", "Location", "Industry", "Source"):
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            stats[label] = result.single()["cnt"]
        return stats
