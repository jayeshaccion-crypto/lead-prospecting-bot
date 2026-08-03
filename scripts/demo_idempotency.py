"""Explicit idempotency demonstration (user-requested).

Reuses the checked-in 54-record fixture (derived from real TradeIndia +
IndiaMART + Justdial captures, plus synthetic cross-site phone pair).
Writes to a live Neo4j, reports node/relationship counts, writes the
identical batch again, reports counts a second time, and prints the
review log showing every fuzzy comparison made during the two runs.
"""

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "graphdb_batch.json"
COUNT_QUERIES = [
    ("companies", "MATCH (c:Company) RETURN count(c) AS c"),
    ("categories", "MATCH (cat:Category) RETURN count(cat) AS c"),
    ("cities", "MATCH (city:City) RETURN count(city) AS c"),
    ("sources", "MATCH (s:Source) RETURN count(s) AS c"),
    ("listed_in", "MATCH ()-[r:LISTED_IN]->() RETURN count(r) AS c"),
    ("located_in", "MATCH ()-[r:LOCATED_IN]->() RETURN count(r) AS c"),
    ("sourced_from", "MATCH ()-[r:SOURCED_FROM]->() RETURN count(r) AS c"),
]


def snapshot(session) -> dict:
    return {name: session.run(q).single()["c"] for name, q in COUNT_QUERIES}


def main():
    import os
    import sys

    from src.graphdb import get_driver, close_driver
    from src.graphdb.client import ensure_schema, write_companies

    # H2 guard: never run MATCH (n) DETACH DELETE n without explicit opt-in.
    if os.environ.get("NEO4J_RESET_ALLOWED") != "1":
        sys.exit(
            "Refusing to run: NEO4J_RESET_ALLOWED not set to '1'. "
            "This demo executes MATCH (n) DETACH DELETE n against the "
            "database get_driver() points to."
        )

    driver = get_driver()
    ensure_schema(driver)
    batch = json.loads(FIXTURE.read_text(encoding="utf-8"))
    print(f"Batch: {len(batch)} records (real IndiaMART/Justdial/TradeIndia + synthetic cross-site pair)\n")

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    print("=== RUN 1 (identical input) ===")
    stats1 = write_companies(driver, batch)
    with driver.session() as session:
        counts1 = snapshot(session)
    print(f"Created={stats1['created']}  Phone-matched={stats1['merged_phone']}  Fuzzy-matched={stats1['merged_fuzzy']}")
    print("Counts:", counts1)

    print("\n=== RUN 2 (identical input, re-run) ===")
    stats2 = write_companies(driver, batch)
    with driver.session() as session:
        counts2 = snapshot(session)
    print(f"Created={stats2['created']}  Phone-matched={stats2['merged_phone']}  Fuzzy-matched={stats2['merged_fuzzy']}")
    print("Counts:", counts2)

    print("\n=== DELTA ===")
    deltas = {k: counts2[k] - counts1[k] for k in counts1}
    print(deltas)
    if all(v == 0 for v in deltas.values()) and stats2["created"] == 0:
        print("IDEMPOTENT: all counts unchanged on second run")
    else:
        print("NON-IDEMPOTENT: counts changed on second run")
        raise SystemExit(1)

    print("\n=== REVIEW LOG (every fuzzy comparison during both runs) ===")
    log = Path("debug_output") / "fuzzy_matches.log"
    print(log.read_text(encoding="utf-8"))

    close_driver()


if __name__ == "__main__":
    main()
