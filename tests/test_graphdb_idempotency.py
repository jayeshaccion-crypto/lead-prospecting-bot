"""Integration test: idempotent Neo4j writes (FR-009, SC-002).

Runs the fixed graphdb_batch.json fixture through write_companies twice on a
dedicated test database and asserts every node/relationship count is
identical between runs (delta 0). Skipped unless a live Neo4j is reachable.

Run: NEO4J_URI=... NEO4J_PASSWORD=... python -m pytest tests/test_graphdb_idempotency.py -m integration -v
"""

import json
import os
from hashlib import md5
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "graphdb_batch.json"

COUNT_QUERIES = {
    "companies": "MATCH (c:Company) RETURN count(c) AS c",
    "categories": "MATCH (cat:Category) RETURN count(cat) AS c",
    "cities": "MATCH (city:City) RETURN count(city) AS c",
    "sources": "MATCH (s:Source) RETURN count(s) AS c",
    "listed_in": "MATCH ()-[r:LISTED_IN]->() RETURN count(r) AS c",
    "located_in": "MATCH ()-[r:LOCATED_IN]->() RETURN count(r) AS c",
    "sourced_from": "MATCH ()-[r:SOURCED_FROM]->() RETURN count(r) AS c",
}


def _live_driver():
    from src.graphdb import get_driver
    return get_driver()


def _snapshot(session) -> dict:
    return {name: session.run(q).single()["c"] for name, q in COUNT_QUERIES.items()}


def _batch() -> list[dict]:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _require_live_neo4j():
    if not os.environ.get("NEO4J_PASSWORD"):
        pytest.skip("NEO4J_PASSWORD not set — skipping live idempotency test")
    try:
        _live_driver()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j unreachable: {exc}")


pytestmark = pytest.mark.integration


def test_idempotent_two_run_counts():
    _require_live_neo4j()
    from src.graphdb import close_driver
    from src.graphdb.client import ensure_schema, write_companies

    driver = _live_driver()
    ensure_schema(driver)
    batch = _batch()

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    # Run 1
    stats1 = write_companies(driver, batch)
    with driver.session() as session:
        run1 = _snapshot(session)

    # Cross-site phone-merge assertion (C1/C3): the synthetic pair must have merged.
    # The phone property stores the raw string (spaces/dashes), so assert via the
    # deterministic phone dedup_key (last-10 digits) which is the merge identity.
    with driver.session() as session:
        phone_dk = md5(b"phone:9876543210").hexdigest()
        rows = list(session.run(
            "MATCH (c:Company {dedup_key: $dk}) RETURN c.company_name AS name, c.sources AS sources",
            {"dk": phone_dk},
        ))
        assert len(rows) == 1, f"expected exactly one Company for phone-dk ...{phone_dk[-6:]}, got {len(rows)}"
        assert "Justdial" in rows[0]["sources"], rows[0]["sources"]
        assert "IndiaMART" in rows[0]["sources"], rows[0]["sources"]

    # Run 2 — identical input
    stats2 = write_companies(driver, batch)
    with driver.session() as session:
        run2 = _snapshot(session)

    close_driver()

    # Idempotency is proven by graph counts (Run 2 creates nothing; it only
    # merges), so per-run classification stats naturally differ. Assert the
    # seven node/relationship counts are identical across runs (delta 0).
    for key in COUNT_QUERIES:
        assert run2[key] == run1[key], f"count '{key}' changed: {run1[key]} -> {run2[key]}"

    # Run 2 must not create any new Company node (everything already exists).
    assert stats2["created"] == 0, f"Run 2 created {stats2['created']} nodes (not idempotent)"
    # Merges reuse existing nodes, so Company count equals created (not created+merged).
    assert run1["companies"] == stats1["created"]
    assert stats1["created"] + stats1["merged_phone"] + stats1["merged_fuzzy"] == len(batch)
