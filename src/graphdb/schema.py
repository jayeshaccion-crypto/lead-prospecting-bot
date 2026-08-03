"""Neo4j schema: constraints, indexes, and graph model definitions."""

import logging

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

LABELS = {
    "Company": "Company",
    "Category": "Category",
    "City": "City",
    "Source": "Source",
}

REL_TYPES = {
    "LISTED_IN": "LISTED_IN",
    "LOCATED_IN": "LOCATED_IN",
    "SOURCED_FROM": "SOURCED_FROM",
}

CONSTRAINTS = [
    "CREATE CONSTRAINT company_dedup_key IF NOT EXISTS FOR (c:Company) REQUIRE c.dedup_key IS UNIQUE",
    "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE",
    "CREATE CONSTRAINT city_name IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX company_normalized_name IF NOT EXISTS FOR (c:Company) ON (c.normalized_name)",
    "CREATE INDEX company_name_index IF NOT EXISTS FOR (c:Company) ON (c.company_name)",
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
