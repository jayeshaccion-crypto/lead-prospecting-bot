"""Neo4j graph database integration for lead prospecting."""

import logging
import os

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

_driver_instance = None


def get_driver() -> GraphDatabase.driver:
    global _driver_instance
    if _driver_instance is None:
        # Read credentials at call time (L4) so NEO4J_PASSWORD can be set
        # after this module is imported.
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError(
                "NEO4J_PASSWORD is not set — credentials must come from the environment"
            )
        _driver_instance = GraphDatabase.driver(uri, auth=(user, password))
        try:
            _driver_instance.verify_connectivity()
            logger.info("Connected to Neo4j at %s", uri)
        except Exception as exc:
            logger.warning("Neo4j not available at %s: %s", uri, exc)
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
