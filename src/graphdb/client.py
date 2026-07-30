"""High-level Neo4j graph API with entity resolution for the lead prospecting pipeline."""

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from hashlib import md5

from neo4j import GraphDatabase
from rapidfuzz import fuzz

from .schema import create_schema

logger = logging.getLogger(__name__)

SITE_SOURCES = {
    "justdial.com": "Justdial",
    "indiamart.com": "IndiaMART",
    "tradeindia.com": "TradeIndia",
}


def normalize_company_name(name: str) -> str:
    """Normalize a company name for entity resolution.

    Lowercase, strip legal suffixes (Pvt, Ltd, LLP, Private Limited, etc.),
    strip punctuation, collapse whitespace.
    """
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(
        r"\b(pvt|ltd|llp|private\s*limited|inc|corp|corporation|llc|limited|co|company|technologies|solutions|services|systems|group|industries|enterprises?)\b",
        "", n, flags=re.IGNORECASE,
    )
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _dedup_key(company_name: str, phone: str | None = None, website: str | None = None) -> str:
    """Generate a deterministic dedup key.

    Phone is the strongest signal — use it as primary key when available.
    Otherwise fall back to normalized name + website.
    """
    raw = ""
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            raw = f"phone:{digits[-10:]}"
    if not raw:
        n = normalize_company_name(company_name)
        w = (website or "").lower().strip()
        w = re.sub(r"^https?://", "", w).rstrip("/")
        raw = f"name:{n}|web:{w}" if w else f"name:{n}"
    return md5(raw.encode()).hexdigest()


def _source_name(url: str | None) -> str:
    if not url:
        return "Unknown"
    for domain, name in SITE_SOURCES.items():
        if domain in url:
            return name
    return "Unknown"


def _write_fuzzy_review(incoming_name: str, matched_name: str, score: int, threshold: int = 90):
    """Append a fuzzy-match entry to debug_output/fuzzy_matches.log."""
    log_dir = "debug_output"
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "fuzzy_matches.log"), "a", encoding="utf-8") as f:
            ts = datetime.now(timezone.utc).isoformat()
            f.write(f"[{ts}] FUZZY_MATCH score={score} threshold={threshold} \"{incoming_name}\" -> \"{matched_name}\"\n")
    except OSError:
        logger.warning("Could not write fuzzy-match review log (falling back to console-only)")


def ensure_schema(driver: GraphDatabase.driver):
    create_schema(driver)


def upsert_company(driver: GraphDatabase.driver, record: dict) -> dict:
    """MERGE a Company node with entity resolution, return the operation result.

    Entity resolution:
    1. Deterministic first pass: match on phone number (strongest signal).
    2. If no phone match, try normalized name fuzzy match (rapidfuzz >= 90).
    3. On match: UPDATE existing node (merge sources, update last_seen, re-score).
    4. On no match: CREATE new node.

    Returns dict with keys: action (created/merged/skipped), dedup_key,
    match_type (phone/fuzzy/none), matched_name (if fuzzy), fuzzy_score (if fuzzy).
    """
    company_name = (record.get("company_name") or "").strip() or "Unknown"
    phone = (record.get("phone") or "").strip() or None
    email = (record.get("email") or "").strip() or None
    website = (record.get("website") or "").strip() or None
    address = (record.get("address") or "").strip() or None
    industry_code = (record.get("industry_code") or "").strip() or None
    source_url = (record.get("source_url") or "").strip() or None
    city_slug = (record.get("city_slug") or "").strip() or None
    category_slug = (record.get("category_slug") or "").strip() or None
    lead_score = record.get("lead_score")
    lead_score_breakdown = record.get("lead_score_breakdown")
    normalized_name = normalize_company_name(company_name)
    src_name = _source_name(source_url)
    now_str = datetime.now(timezone.utc).isoformat()

    dk = _dedup_key(company_name, phone, website)

    result = {"dedup_key": dk, "action": "skipped", "match_type": None}

    with driver.session() as session:
        # Step 1: Deterministic phone match
        matched_key = None
        match_type = None
        fuzzy_score = None
        matched_name = None

        if phone:
            digits = re.sub(r"\D", "", phone)
            if len(digits) >= 10:
                phone_dk = _dedup_key(company_name, phone)
                row = session.run(
                    "MATCH (c:Company {dedup_key: $dk}) RETURN c.dedup_key AS dk, c.company_name AS name",
                    {"dk": phone_dk},
                ).single()
                if row:
                    matched_key = row["dk"]
                    match_type = "phone"
                    logger.info("Entity resolution: phone match for '%s' -> existing '%s' (phone=%s)", company_name, row["name"], digits[-10:])

        # Step 2: Fuzzy name match (only if no phone match)
        if not matched_key:
            prefix = normalized_name[:3] if len(normalized_name) >= 3 else normalized_name
            existing = list(session.run(
                "MATCH (c:Company) WHERE c.normalized_name STARTS WITH $prefix "
                "RETURN c.dedup_key AS dk, c.company_name AS name, c.normalized_name AS norm",
                {"prefix": prefix},
            ))
            for row in existing:
                existing_norm = row.get("norm") or normalize_company_name(row.get("name") or "")
                score = fuzz.token_sort_ratio(normalized_name, existing_norm)
                if score >= 90:
                    matched_key = row["dk"]
                    match_type = "fuzzy"
                    fuzzy_score = score
                    matched_name = row.get("name") or ""
                    logger.info(
                        "Entity resolution: fuzzy match '%s' -> '%s' (score=%d)",
                        company_name, matched_name, score,
                    )
                    _write_fuzzy_review(company_name, matched_name, score)
                    break
                else:
                    logger.debug(
                        "Entity resolution: sub-threshold candidate '%s' (score=%d < 90)",
                        row.get("name") or "", score,
                    )

        if matched_key:
            # MERGE existing — update fields and add relationships
            dk = matched_key
            session.run(
                """MERGE (c:Company {dedup_key: $dk})
                   SET c.company_name = CASE WHEN $name <> '' THEN $name ELSE c.company_name END,
                       c.normalized_name = $norm,
                       c.website = CASE WHEN $website IS NOT NULL AND $website <> '' THEN $website ELSE c.website END,
                       c.phone = CASE WHEN $phone IS NOT NULL AND $phone <> '' THEN $phone ELSE c.phone END,
                       c.email = CASE WHEN $email IS NOT NULL AND $email <> '' THEN $email ELSE c.email END,
                       c.address = CASE WHEN $address IS NOT NULL AND $address <> '' THEN $address ELSE c.address END,
                       c.industry_code = CASE WHEN $industry IS NOT NULL AND $industry <> '' THEN $industry ELSE c.industry_code END,
                       c.last_seen = $now,
                       c.lead_score = $score,
                       c.lead_score_breakdown = $breakdown,
                       c.sources = CASE
                           WHEN $src_name IS NOT NULL AND NOT $src_name IN COALESCE(c.sources, [])
                           THEN COALESCE(c.sources, []) + [$src_name]
                           ELSE c.sources
                       END
                """,
                {"dk": dk, "name": company_name, "norm": normalized_name,
                 "website": website, "phone": phone, "email": email,
                 "address": address, "industry": industry_code,
                 "now": now_str, "score": lead_score,
                 "breakdown": json.dumps(lead_score_breakdown) if lead_score_breakdown else None,
                 "src_name": src_name},
            )
            result["action"] = "merged"
        else:
            # CREATE new
            sources = [src_name] if src_name != "Unknown" else []
            session.run(
                """CREATE (c:Company {
                       dedup_key: $dk, company_name: $name, normalized_name: $norm,
                       website: $website, phone: $phone, email: $email,
                       address: $address, industry_code: $industry,
                       first_seen: $now, last_seen: $now,
                       lead_score: $score, lead_score_breakdown: $breakdown,
                       sources: $sources
                   })""",
                {"dk": dk, "name": company_name, "norm": normalized_name,
                 "website": website, "phone": phone, "email": email,
                 "address": address, "industry": industry_code,
                 "now": now_str, "score": lead_score,
                 "breakdown": json.dumps(lead_score_breakdown) if lead_score_breakdown else None,
                 "sources": sources},
            )
            result["action"] = "created"

        # Category relationship (MERGE to avoid duplicates)
        if category_slug:
            session.run(
                "MERGE (cat:Category {name: $slug}) "
                "WITH cat MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:LISTED_IN]->(cat)",
                {"slug": category_slug, "dk": dk},
            )

        # City relationship
        if city_slug:
            session.run(
                "MERGE (city:City {name: $slug}) "
                "WITH city MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:LOCATED_IN]->(city)",
                {"slug": city_slug, "dk": dk},
            )

        # Source relationship
        if src_name != "Unknown":
            session.run(
                "MERGE (s:Source {name: $src_name}) "
                "WITH s MATCH (c:Company {dedup_key: $dk}) "
                "MERGE (c)-[:SOURCED_FROM {scraped_at: $now}]->(s)",
                {"src_name": src_name, "dk": dk, "now": now_str},
            )

    result["match_type"] = match_type
    return result


def write_companies(driver: GraphDatabase.driver, records: list[dict]) -> dict:
    """Write multiple records to Neo4j with entity resolution.

    Returns aggregate stats: created, merged (phone vs fuzzy), total.
    """
    stats = {"created": 0, "merged_phone": 0, "merged_fuzzy": 0, "skipped": 0}
    for rec in records:
        r = upsert_company(driver, rec)
        if r["action"] == "created":
            stats["created"] += 1
        elif r["action"] == "merged":
            if r.get("match_type") == "phone":
                stats["merged_phone"] += 1
            elif r.get("match_type") == "fuzzy":
                stats["merged_fuzzy"] += 1
            else:
                stats["merged_phone"] += 1
        else:
            stats["skipped"] += 1
    return stats


def query_by_location(driver: GraphDatabase.driver, city: str):
    with driver.session() as session:
        result = session.run(
            """MATCH (c:Company)-[:LOCATED_IN]->(city:City {name: $city})
               OPTIONAL MATCH (c)-[:LISTED_IN]->(cat:Category)
               OPTIONAL MATCH (c)-[:SOURCED_FROM]->(s:Source)
               RETURN c.company_name AS company_name,
                      c.website AS website,
                      c.address AS address,
                      c.phone AS phone,
                      c.email AS email,
                      c.lead_score AS lead_score,
                      collect(DISTINCT cat.name) AS categories,
                      collect(DISTINCT s.name) AS sources
               ORDER BY c.company_name""",
            {"city": city},
        )
        return list(result)


def query_company_detail(driver: GraphDatabase.driver, company_name: str):
    with driver.session() as session:
        result = session.run(
            """MATCH (c:Company)
               WHERE toLower(c.company_name) CONTAINS toLower($name)
               OPTIONAL MATCH (c)-[:LOCATED_IN]->(city:City)
               OPTIONAL MATCH (c)-[:LISTED_IN]->(cat:Category)
               OPTIONAL MATCH (c)-[:SOURCED_FROM]->(s:Source)
               RETURN c.company_name AS company_name,
                      c.website AS website,
                      c.address AS address,
                      c.phone AS phone,
                      c.email AS email,
                      city.name AS city,
                      collect(DISTINCT cat.name) AS categories,
                      collect(DISTINCT s.name) AS sources,
                      c.lead_score AS lead_score,
                      c.lead_score_breakdown AS lead_score_breakdown
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
        for label in ("Company", "Category", "City", "Source"):
            result = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            stats[label] = result.single()["cnt"]
        # Relationship counts
        for rel in ("LISTED_IN", "LOCATED_IN", "SOURCED_FROM"):
            result = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS cnt")
            stats[rel] = result.single()["cnt"]
        return stats
