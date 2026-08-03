# Quickstart: Neo4j Graph Schema & Entity Resolution — Validation Guide

**Created**: 2026-08-03 | **Branch**: `007-neo4j-entity-resolution`

This guide validates the feature end-to-end. Implementation details live in the contracts and data model; this file is the run/verify recipe.

## Prerequisites

- Python 3.14 environment with project deps installed: `neo4j`, `rapidfuzz`, `pytest`.
- A Neo4j instance (>= 5.20) for the integration checks. Credentials are **environment variables only**:
  - `NEO4J_URI` (default `bolt://localhost:7687`)
  - `NEO4J_USER` (default `neo4j`)
  - `NEO4J_PASSWORD` (**required** — no default; the feature fails explicitly if unset)
- `TARGETS_CONFIG` unset or `config/targets.yaml` present with optional `fuzzy_match_threshold` (default 90).

## Setup

```powershell
# 1. Ensure the env-only credentials are present for any Neo4j-touching check
$env:NEO4J_PASSWORD = "<your-password>"

# 2. Regenerate the committed fixture from the captured real records (idempotent, deterministic)
python scripts/make_graphdb_fixture.py
#   → writes tests/fixtures/graphdb_batch.json (54 rows: 51 real from debug_output/*_records.json
#     + synthetic cross-site pair + synthetic TradeIndia-with-phone record)
```

The fixture is committed; the script exists only to reproduce it from source captures.

## 1. Unit checks (no database required)

```powershell
python -m pytest tests/test_config.py tests/test_graphdb.py -q
```

Expected: all pass. Coverage:
- Normalization table over real names (38 unique inputs → 38 distinct outputs, incl. `Nitai Technologies (OPC) Private Limited` → `nitai`).
- `_dedup_key` determinism and phone-primary-key behavior.
- `get_fuzzy_match_threshold()` default 90 and `config/targets.yaml` override.
- Fuzzy selection + threshold + deterministic tie-break (stubbed candidates).
- Review-log writer emits the exact `review-log-format` line schema, incl. `verdict=not_matched` for below-threshold comparisons.

## 2. Idempotency integration check (requires live Neo4j)

`tests/test_graphdb_idempotency.py` is marked `integration` and is skipped automatically when Neo4j is unreachable. Run it explicitly:

```powershell
python -m pytest tests/test_graphdb_idempotency.py -q -m integration
```

> **Safety gate (H2):** this test and the demo run `MATCH (n) DETACH DELETE n` against whatever database `get_driver()` points to. They refuse to run unless you explicitly opt in:
>
> ```powershell
> $env:NEO4J_RESET_ALLOWED = "1"
> ```

**Procedure it runs (exact):**
1. On a dedicated test database: clear graph via `MATCH (n) DETACH DELETE n`.
2. **Run 1** — `write_companies(driver, BATCH)` with the committed 54-record fixture `tests/fixtures/graphdb_batch.json`.
3. Snapshot counts with these **exact** count queries:

```cypher
MATCH (c:Company) RETURN count(c) AS companies
MATCH (cat:Category) RETURN count(cat) AS categories
MATCH (city:City) RETURN count(city) AS cities
MATCH (s:Source) RETURN count(s) AS sources
MATCH ()-[r:LISTED_IN]->() RETURN count(r) AS listed_in
MATCH ()-[r:LOCATED_IN]->() RETURN count(r) AS located_in
MATCH ()-[r:SOURCED_FROM]->() RETURN count(r) AS sourced_from
```

4. **Run 2** — `write_companies(driver, BATCH)` again with the identical fixture.
5. Re-run the same count queries and assert **every value equals the Run-1 snapshot (delta 0)**.

**Expected outcome**: `companies`, `categories`, `cities`, `sources`, `listed_in`, `located_in`, `sourced_from` are byte-identical between Run 1 and Run 2. Additional assertions: `first_seen` unchanged for pre-existing nodes; `sources` arrays contain each directory once; `SOURCED_FROM` edges carry `scraped_at` + `raw_record_id`; the synthetic cross-site phone pair (a Justdial + IndiaMART listing sharing phone `...9876543210`) merges into exactly ONE Company node whose `sources` contains BOTH directories (proves phone-keyed matching works across sites).

### Recorded results — 2026-08-03 (live Neo4j, env-only credentials)

Run with: `python -m scripts.demo_idempotency` after `$env:NEO4J_PASSWORD = "<password>"` and `$env:NEO4J_RESET_ALLOWED = "1"`. Batch = 54 records (real IndiaMART/Justdial/TradeIndia captures + synthetic cross-site pair).

| Metric | Run 1 | Run 2 |
|--------|-------|-------|
| companies | 52 | 52 |
| categories | 10 | 10 |
| cities | 10 | 10 |
| sources | 3 | 3 |
| listed_in | 53 | 53 |
| located_in | 53 | 53 |
| sourced_from | 53 | 53 |

Run stats: Run 1 → created=52, phone-matched=1, fuzzy-matched=1; Run 2 → created=0 (everything already existed; only merges). **Delta = 0 for all seven counts** → idempotent. Cross-site merge verified in graph: `Synthetix Digital Solutions` has `sources=['Justdial','IndiaMART']`.

## 3. Manual spot-check (merge review trail)

After any resolution run that involved phone-less records:

```powershell
Get-Content debug_output\fuzzy_matches.log -Tail 50
```

Expected: one line per fuzzy comparison in the `review-log-format` schema — both names, both normalized forms, score, threshold, `matched`/`not_matched`. A wrong merge (score at/above threshold) should be investigated because graph merges are effectively permanent.

## 4. End-to-end pipeline sanity

```powershell
python -m pytest -q                    # full suite
```

Expected: full suite green. On a non-dry-run pipeline with Neo4j reachable, the run summary logs `neo4j_created=... neo4j_merged=(phone=N, fuzzy=M)` and sets `neo4j_failed=true` explicitly if the write fails (never a silent 0-count).

## References

- Schema + write queries: [contracts/graph-schema.md](./contracts/graph-schema.md), [data-model.md](./data-model.md)
- Resolution algorithm + threshold: [contracts/entity-resolution.md](./contracts/entity-resolution.md)
- Review log fields: [contracts/review-log-format.md](./contracts/review-log-format.md)
