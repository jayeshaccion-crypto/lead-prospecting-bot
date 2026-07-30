"""CLI: Migrate SQLite leads data to Neo4j graph database."""

import argparse
import logging
import sys

from src.graphdb import get_driver, close_driver
from src.graphdb.schema import create_schema
from src.graphdb.migrate import run_migration

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite leads to Neo4j")
    parser.add_argument("--db", default="data/leads.db", help="Path to SQLite database")
    args = parser.parse_args()

    try:
        driver = get_driver()
    except Exception as exc:
        logger.error("Cannot connect to Neo4j: %s", exc)
        sys.exit(1)

    create_schema(driver)
    run_migration(driver, args.db)
    close_driver()
    logger.info("Done")


if __name__ == "__main__":
    main()
