"""Migrate existing SQLite leads data into Neo4j graph."""

import logging
import re
import sqlite3
import unicodedata
from hashlib import md5

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

SITE_SOURCES = {
    "justdial.com": "Justdial",
    "indiamart.com": "IndiaMART",
    "tradeindia.com": "TradeIndia",
}


def _dedup_key(row: dict) -> str:
    raw = f"{row.get('company_name','')}|{row.get('website','')}".strip().lower()
    raw = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return md5(raw.encode()).hexdigest()


def _phones_from_row(row: dict) -> list[str]:
    phones = set()
    for col in ("phone", "mobile", "phone1", "phone2", "phone3", "phone4", "raw_phone", "alt_phone"):
        raw = row.get(col, "") or ""
        if raw.strip():
            nums = re.findall(r"\d{6,15}", raw)
            phones.update(nums)
    return sorted(phones)


def _emails_from_row(row: dict) -> list[str]:
    emails = set()
    raw = (row.get("email", "") or "") + "|" + (row.get("raw_email", "") or "")
    matches = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw)
    emails.update(m.lower() for m in matches)
    return sorted(emails)


def _source_name(row: dict) -> str:
    url = (row.get("source_url") or row.get("url") or "").lower()
    for domain, name in SITE_SOURCES.items():
        if domain in url:
            return name
    return "Unknown"


def _industry_code(industry: str | None) -> str | None:
    if not industry or industry.strip() in ("", "N/A", "n/a"):
        return None
    code = industry.strip().upper().replace(" ", "_").replace("/", "_")
    if len(code) > 50:
        code = md5(code.encode()).hexdigest()[:16]
    return code


def run_migration(driver: GraphDatabase.driver, db_path: str):
    logger.info("Migrating SQLite data from %s to Neo4j", db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM Leads")
    rows = cursor.fetchall()
    conn.close()
    logger.info("Found %d rows to migrate", len(rows))

    merged: dict[str, dict] = {}
    for row in rows:
        d = dict(row)
        dk = _dedup_key(d)
        if dk in merged:
            existing = merged[dk]
            for k, v in d.items():
                if v and not existing.get(k):
                    existing[k] = v
        else:
            d["_dedup_key"] = dk
            merged[dk] = d

    logger.info("After dedup: %d unique companies", len(merged))

    with driver.session() as session:
        for dk, row in merged.items():
            try:
                _upsert_company(session, row)
            except Exception as exc:
                logger.warning("Failed to migrate dedup_key=%s: %s", dk, exc)

    logger.info("Migration complete: %d companies", len(merged))


def _upsert_company(session, row: dict):
    dk = row.get("_dedup_key") or _dedup_key(row)
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
    phones = _phones_from_row(row)
    emails = _emails_from_row(row)
    src_name = _source_name(row)
    industry_code_val = _industry_code(industry)

    MERGE_COMPANY = """
    MERGE (c:Company {dedup_key: $dk})
    SET c.company_name = $name,
        c.website = $website,
        c.address = $address,
        c.industry_code = $industry_code,
        c.source_url = $source_url,
        c.scraped_at = datetime()
    RETURN c
    """
    session.run(MERGE_COMPANY, {
        "dk": dk, "name": company_name, "website": website,
        "address": address, "industry_code": industry_code_val,
        "source_url": source_url,
    })

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
    if industry_code_val:
        session.run(
            "MERGE (i:Industry {code: $code}) "
            "ON CREATE SET i.name = $name "
            "WITH i MATCH (c:Company {dedup_key: $dk}) "
            "MERGE (c)-[:BELONGS_TO]->(i)",
            {"code": industry_code_val, "name": industry, "dk": dk},
        )
    if src_name != "Unknown":
        session.run(
            "MERGE (s:Source {name: $src_name}) "
            "WITH s MATCH (c:Company {dedup_key: $dk}) "
            "MERGE (c)-[:SOURCED_FROM]->(s)",
            {"src_name": src_name, "dk": dk},
        )
