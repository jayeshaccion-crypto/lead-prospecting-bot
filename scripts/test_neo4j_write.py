"""Standalone Neo4j connectivity + MERGE idempotency proof.

Reads NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD from env.
Raises on missing credentials or connection failure.
Exits 0 on success, 1 on failure.
"""

import os
import sys
from hashlib import md5

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

if not all([NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD]):
    print("ERROR: Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD")
    sys.exit(1)

from neo4j import GraphDatabase

TEST_DEDUP_KEY = md5(b"test-governance-proof").hexdigest()
TEST_NAME = "TestGovernanceProof"


def run_test(driver):
    with driver.session() as session:
        # Step 1: MERGE test node (first run creates)
        session.run(
            "MERGE (c:Company {dedup_key: $dk}) "
            "ON CREATE SET c.company_name = $name, c.first_seen = datetime() "
            "ON MATCH SET c.last_seen = datetime()",
            {"dk": TEST_DEDUP_KEY, "name": TEST_NAME},
        )

        # Step 2: Count after first write
        result = session.run(
            "MATCH (c:Company) WHERE c.dedup_key = $dk RETURN count(c) AS cnt",
            {"dk": TEST_DEDUP_KEY},
        )
        count_before = result.single()["cnt"]
        print(f"Node count after first MERGE: {count_before}")
        assert count_before == 1, f"Expected 1 node, got {count_before}"

        # Step 3: Re-run same MERGE (idempotency proof)
        session.run(
            "MERGE (c:Company {dedup_key: $dk}) "
            "ON CREATE SET c.company_name = $name, c.first_seen = datetime() "
            "ON MATCH SET c.last_seen = datetime()",
            {"dk": TEST_DEDUP_KEY, "name": TEST_NAME},
        )

        # Step 4: Count after second write — must be unchanged
        result = session.run(
            "MATCH (c:Company) WHERE c.dedup_key = $dk RETURN count(c) AS cnt",
            {"dk": TEST_DEDUP_KEY},
        )
        count_after = result.single()["cnt"]
        print(f"Node count after second MERGE: {count_after}")
        assert count_after == count_before, (
            f"Idempotency failure: {count_before} -> {count_after}"
        )

        print(f"Idempotency OK: {count_before} -> {count_after} (unchanged)")


def cleanup(driver):
    with driver.session() as session:
        session.run(
            "MATCH (c:Company {dedup_key: $dk}) DETACH DELETE c",
            {"dk": TEST_DEDUP_KEY},
        )


def main():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception:
        print("ERROR: Connection failed (URI redacted)")
        sys.exit(1)

    try:
        run_test(driver)
    except Exception as exc:
        print(f"ERROR: Test failed (node count: see above)")
        sys.exit(1)
    finally:
        try:
            cleanup(driver)
        except Exception:
            pass
        driver.close()


if __name__ == "__main__":
    main()
