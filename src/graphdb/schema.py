"""Neo4j schema: constraints, indexes, and graph model definitions."""

import logging

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

LABELS = {
    "Company": "Company",
    "Phone": "Phone",
    "Email": "Email",
    "Website": "Website",
    "Location": "Location",
    "Industry": "Industry",
    "Source": "Source",
}

REL_TYPES = {
    "HAS_PHONE": "HAS_PHONE",
    "HAS_EMAIL": "HAS_EMAIL",
    "HAS_WEBSITE": "HAS_WEBSITE",
    "LOCATED_IN": "LOCATED_IN",
    "BELONGS_TO": "BELONGS_TO",
    "SOURCED_FROM": "SOURCED_FROM",
    "SIMILAR_TO": "SIMILAR_TO",
}

CONSTRAINTS = [
    "CREATE CONSTRAINT company_dedup_key IF NOT EXISTS FOR (c:Company) REQUIRE c.dedup_key IS UNIQUE",
    "CREATE CONSTRAINT phone_number IF NOT EXISTS FOR (p:Phone) REQUIRE p.number IS UNIQUE",
    "CREATE CONSTRAINT email_address IF NOT EXISTS FOR (e:Email) REQUIRE e.address IS UNIQUE",
    "CREATE CONSTRAINT website_url IF NOT EXISTS FOR (w:Website) REQUIRE w.url IS UNIQUE",
    "CREATE CONSTRAINT location_key IF NOT EXISTS FOR (l:Location) REQUIRE l.city IS UNIQUE",
    "CREATE CONSTRAINT industry_code IF NOT EXISTS FOR (i:Industry) REQUIRE i.code IS UNIQUE",
    "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX company_name_index IF NOT EXISTS FOR (c:Company) ON (c.company_name)",
    "CREATE INDEX company_website_index IF NOT EXISTS FOR (c:Company) ON (c.website)",
]


def create_schema(driver: GraphDatabase.driver):
    with driver.session() as session:
        for cypher in CONSTRAINTS:
            try:
                session.run(cypher)
                logger.info("Constraint applied: %s", cypher.split("REQUIRE")[0].strip())
            except Exception as exc:
                logger.warning("Constraint failed (may already exist): %s", exc)
        for cypher in INDEXES:
            try:
                session.run(cypher)
                logger.info("Index applied: %s", cypher.split("ON")[0].strip())
            except Exception as exc:
                logger.warning("Index failed: %s", exc)
    logger.info("Neo4j schema ready")
