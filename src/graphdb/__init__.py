"""Neo4j graph database integration for lead prospecting."""

import logging
import os

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

DEFAULT_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
DEFAULT_USER = os.environ.get("NEO4J_USER", "neo4j")
DEFAULT_PASSWORD = os.environ.get("NEO4J_PASSWORD", "leadsbot")

_driver_instance = None


def get_driver() -> GraphDatabase.driver:
    global _driver_instance
    if _driver_instance is None:
        _driver_instance = GraphDatabase.driver(DEFAULT_URI, auth=(DEFAULT_USER, DEFAULT_PASSWORD))
        try:
            _driver_instance.verify_connectivity()
            logger.info("Connected to Neo4j at %s", DEFAULT_URI)
        except Exception as exc:
            logger.warning("Neo4j not available at %s: %s", DEFAULT_URI, exc)
            _driver_instance = None
            raise
    return _driver_instance


def close_driver():
    global _driver_instance
    if _driver_instance:
        _driver_instance.close()
        _driver_instance = None
        logger.info("Neo4j driver closed")


def run_query(query: str, params: dict | None = None):
    """Run a Cypher query and return all records."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(query, params or {})
        return list(result)
