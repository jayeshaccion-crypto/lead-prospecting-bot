# Contract: Graph Schema

**Feature**: Neo4j Graph Schema & Entity Resolution
**Version**: 1.0 | **Date**: 2026-08-03
**Consumers**: `src/graphdb/client.py` (writer), `src/pipeline.py` (orchestrator), idempotency tests.

This contract pins the canonical graph shape and the exact write queries. Any change to node properties, relationship properties, or merge keys is a breaking schema change.

## Node contract

| Label | Required properties | Unique on | Indexed |
|-------|--------------------|-----------|---------|
| `Company` | `dedup_key`, `company_name`, `normalized_name`, `first_seen`, `last_seen`, `sources` | `dedup_key` | `company_name`, `normalized_name` |
| `Category` | `name` | `name` | — |
| `City` | `name` | `name` | — |
| `Source` | `name` | `name` | — |

Optional `Company` properties: `phone`, `email`, `website`, `address`, `industry_code`, `lead_score`, `lead_score_breakdown`.

Semantics:
- `dedup_key` is immutable once created (identity).
- `first_seen` is set only on create and MUST NOT be overwritten by later merges.
- `last_seen` is updated on every match.
- `sources` is a list; a directory name is appended only if not already present.

## Relationship contract

| Relationship | From → To | Properties | Merge key (idempotency) |
|--------------|-----------|------------|--------------------------|
| `LISTED_IN` | Company → Category | — | (`Company.dedup_key`, `Category.name`) |
| `LOCATED_IN` | Company → City | — | (`Company.dedup_key`, `City.name`) |
| `SOURCED_FROM` | Company → Source | `scraped_at`, `raw_record_id` | (`Company.dedup_key`, `Source.name`) — one edge per pair |

- `raw_record_id` := `f"{source_name}|{company_name}|{primary_contact}".lower()`, `primary_contact` = phone digits if present else email else website.
- Relationship writes MUST use `MERGE`, never `CREATE`.

## DDL

```cypher
CREATE CONSTRAINT company_dedup_key IF NOT EXISTS FOR (c:Company) REQUIRE c.dedup_key IS UNIQUE
CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE
CREATE CONSTRAINT category_name IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE
CREATE CONSTRAINT city_name IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE
CREATE INDEX company_normalized_name IF NOT EXISTS FOR (c:Company) ON (c.normalized_name)
CREATE INDEX company_name IF NOT EXISTS FOR (c:Company) ON (c.company_name)
```

## Write queries (binding)

See [data-model.md](../data-model.md) §Write Queries for Q3 (Company MERGE), Q4 (LISTED_IN), Q5 (LOCATED_IN), Q6 (SOURCED_FROM). These four queries are the complete write surface.

## Acceptance tests

- Re-running identical input twice produces identical node and relationship counts (delta 0) — see `quickstart.md` idempotency procedure.
- No query uses `CREATE` for an existing entity or relationship.
- `first_seen` on a merged node equals the value from its original creation.
