# Implementation Plan: Governance Compliance

**Branch**: `002-governance-compliance` | **Date**: 2026-07-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-governance-compliance/spec.md`

## Summary

Enforce all six constitutional rules in code: fail loudly on every target
(no silent 0-record contributions), log all entity-resolution merges to
a review file, ensure scoring is deterministic and auditable, isolate
lead_score from all user-facing renders, guarantee no credentials are
committed to git, and prove idempotency across all pipeline phases.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**:
- `neo4j>=5.20` — already in `pyproject.toml:13`
- Pinned version for this plan: `neo4j==5.20.0` (pinned in production
  CI install, not in pyproject range)
- `rapidfuzz>=3.0` — already in `pyproject.toml:14`

**Storage**: SQLite (`data/leads.db`) + Neo4j (graph database, `NEO4J_URI`
env var)

**Testing**: pytest (352 existing tests), plus a standalone Neo4j
connectivity proof script at `scripts/test_neo4j_write.py`

**Target Platform**: Linux (GitHub Actions ubuntu-latest), Windows dev

**Project Type**: CLI pipeline (single project layout under `src/`)

**Performance Goals**: Pipeline completes within 30-min GitHub Actions
timeout. Neo4j write for ~200 records/day completes in <30s.

**Constraints**:
- Must NOT modify Scrapling library code (only `src/` project code)
- `.env` must remain in `.gitignore`
- `debug_output/` and checkpoint dirs must remain in `.gitignore`
- Must not break any of the 352 existing tests

**Scale/Scope**: ~200 records/day, ~500 Company nodes after 3 months,
single-threaded pipeline

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Violation Analysis

| Constitution Principle | Status | Notes |
|-----------------------|--------|-------|
| I. Robots.txt Compliance | ✅ Compliant | `robots_txt_obey=False` but `is_robots_allowed()` called explicitly per domain. No violation. |
| II. No LinkedIn Scraping | ✅ Compliant | No LinkedIn code paths. |
| III. Credential Security | ❌ **Violation** | `_write_to_neo4j()` returns `{"created":0}` on failure instead of `"neo4j_failed":true`. `.gitignore` coverage for checkpoint dir not verified. |
| IV. Idempotent Operations | ❌ **Violation** | Checkpointing disabled (`crawldir=None` in `spider.py:142`). No idempotency proof exists. |
| V. Fail Loudly | ❌ **Violation** | Neo4j failure silently downgrades. JD ASN stats count retries, not distinct IPs. Fuzzy matches not written to review file. |
| Entity Resolution Transparency | ❌ **Violation** | No `debug_output/fuzzy_matches.log` writer exists. Matches logged to INFO only. |
| Data Layer Isolation | ✅ Compliant | Dashboard already grep-clean. Verified in prior code review. |
| VI-X. Knowledge Graph Grounding | ✅ Compliant | CodeGraph queries precede all work in this session. |

**Resolution**: All violations will be closed by this plan's deliverables.
Justification for complexity: no simpler alternative exists — the
violations are constitutional obligations that require code changes.

## Project Structure

### Documentation (this feature)

```text
specs/002-governance-compliance/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── pipeline.py          # Patch _write_to_neo4j() to set neo4j_failed
├── scraper/
│   └── spider.py        # Pass crawldir to super().__init__()
├── graphdb/
│   └── client.py        # Add fuzzy-matches log file writer
scripts/
├── test_neo4j_write.py  # NEW — standalone connectivity proof
.github/
└── workflows/
    └── daily.yml        # Add neo4j dep install step + pin version
```

**Structure Decision**: Single project (DEFAULT). No new modules needed —
all changes are patches to existing files plus one standalone script.

## Complexity Tracking

> No constitution violations require complexity justification — all changes
> are straightforward patches to existing functions.

## Phase 0: Research

### Research Tasks

1. **Neo4j driver pinning** — Confirm `neo4j==5.20.0` is the correct
   pinned version (current `>=5.20` is loose). Resolve: pin to `5.20.0`
   for CI reproducibility.

2. **GitHub Actions workflow** — Locate the workflow file and CI install
   step to modify.

3. **Checkpoint directory** — Determine the correct `crawldir` value and
   verify `.gitignore` coverage.

4. **Cloudflare log lines** — Confirm actual log level of "No Cloudflare
   challenge found" in bundled Scrapling.

### Research Results (consolidated in [research.md](./research.md))

<!-- Phase 0 generates research.md — see that file for full findings -->

**Decision**: `neo4j==5.20.0` pinned. `crawldir=".scrapling_checkpoints"`.
Cloudflare lines already at INFO — no change needed.

## Phase 1: Design

### Deliverables

- [data-model.md](./data-model.md) — PipelineSummary entity with
  `neo4j_failed` field, EntityResolutionLog entity
- [contracts/](./contracts/) — Interface for `_write_to_neo4j()` return
  shape, review log file format
- [quickstart.md](./quickstart.md) — Validation scenarios for Neo4j
  connectivity, fuzzy-match review, score isolation, idempotency

### Key Design Decisions

1. **Neo4j write failure**: Change `_write_to_neo4j()` to propagate
   `ImportError` and `Exception` up to `main_pipeline()`, which sets
   `summary["neo4j_failed"] = True`. Log at ERROR, not WARNING.
   File: `src/pipeline.py:348-353`
   Before:
   ```python
   except ImportError:
       logger.warning("Neo4j driver not installed — skipping graph write")
       return {"created": 0, "merged_phone": 0, "merged_fuzzy": 0, "skipped": 0}
   except Exception as exc:
       logger.warning("Neo4j write failed: %s", exc)
       return {"created": 0, "merged_phone": 0, "merged_fuzzy": 0, "skipped": 0}
   ```
   After:
   ```python
   except ImportError as exc:
       logger.error("Neo4j driver not installed: %s", exc)
       raise
   except Exception as exc:
       logger.error("Neo4j write failed: %s", exc)
       raise
   ```

2. **Checkpointing**: Pass `crawldir=".scrapling_checkpoints"` to
   `super().__init__()` in `LeadSpider.__init__()`. Add `.scrapling_checkpoints/`
   to `.gitignore`. File: `src/scraper/spider.py:142`

3. **Fuzzy-match review log**: In `graphdb/client.py`, `upsert_company()`,
   append fuzzy match entries to `debug_output/fuzzy_matches.log` using
   a file handler. Format per line:
   `[timestamp] FUZZY_MATCH score=92 threshold=90 "CompanyA" -> "CompanyB"`
   Directory created on first write.

4. **JD ASN stats accuracy**: Change `_jd_stats["attempted"]` to track
   unique proxy IPs (via a set), not total retry count, so the summary
   log accurately says "X distinct proxy IPs attempted".

5. **No Cloudflare downgrade**: No action needed — both occurrences at
   `Scrapling/scrapling/engines/_browsers/_stealth.py:116` (sync) and
   `:391` (async) already use `log.info()`.

6. **Neo4j connectivity proof**: New standalone script at
   `scripts/test_neo4j_write.py` that:
   - Parses env vars `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
   - Runs `CREATE (c:Company {company_name: "TestCorp", dedup_key: md5("test"), first_seen: datetime()})`
     followed by `MATCH (c:Company) RETURN count(c) AS cnt`
   - Then runs the same CREATE again (to prove MERGE idempotency) and
     asserts count is unchanged
   - Then cleans up: `MATCH (c:Company {dedup_key: md5("test")}) DETACH DELETE c`
   - Exits 0 on success, 1 on failure

7. **GitHub Actions workflow**: Add explicit `pip install neo4j==5.20.0`
   step before running pipeline. File: `.github/workflows/daily.yml`

### Changes Summary

| File | Change | Line(s) |
|------|--------|---------|
| `src/pipeline.py` | `_write_to_neo4j()` — raise on failure, ERROR log | 348-353 |
| `src/pipeline.py` | `main_pipeline()` — catch Neo4j failure, set `neo4j_failed` | 420-429 |
| `src/scraper/spider.py` | Pass `crawldir=".scrapling_checkpoints"` to `super().__init__()` | ~142 |
| `src/graphdb/client.py` | Add `debug_output/fuzzy_matches.log` writer in `upsert_company()` | ~131-140 |
| `src/scraper/spider.py` | Track unique proxy IPs (set) for JD ASN stats | ~421-424 |
| `scripts/test_neo4j_write.py` | NEW — standalone connectivity + idempotency proof | N/A |
| `.github/workflows/daily.yml` | Add `pip install neo4j==5.20.0` step | ~41-42 |
| `.gitignore` | Add `.scrapling_checkpoints/` | append |

### Cloudflare Log Level Report

| File | Line | Current Level | Required Level | Action |
|------|------|---------------|----------------|--------|
| `Scrapling/scrapling/engines/_browsers/_stealth.py` | 116 | `log.info()` | INFO (no change) | None — already correct |
| `Scrapling/scrapling/engines/_browsers/_stealth.py` | 391 | `log.info()` | INFO (no change) | None — already correct |

The "No Cloudflare challenge found" messages are emitted by Scrapling's
internal logger (`log.info()` from `scrapling.core.utils`). They have
never been at ERROR level in this bundled version. No change needed.

### Standalone Neo4j Proof Script

`scripts/test_neo4j_write.py` — exact Cypher to be executed:

```python
# Step 1: CREATE a test node (first run creates, second run should MERGE)
session.run(
    "MERGE (c:Company {dedup_key: $dk}) "
    "ON CREATE SET c.company_name = $name, c.first_seen = datetime() "
    "ON MATCH SET c.last_seen = datetime()",
    {"dk": md5("test-governance-proof").hexdigest(), "name": "TestGovernanceProof"},
)

# Step 2: Count nodes
count = session.run("MATCH (c:Company) WHERE c.dedup_key = $dk RETURN count(c) AS cnt",
                    {"dk": md5("test-governance-proof").hexdigest()}).single()["cnt"]
assert count == 1

# Step 3: Re-run same MERGE (prove idempotency)
session.run(
    "MERGE (c:Company {dedup_key: $dk}) "
    "ON CREATE SET c.company_name = $name, c.first_seen = datetime() "
    "ON MATCH SET c.last_seen = datetime()",
    {"dk": md5("test-governance-proof").hexdigest(), "name": "TestGovernanceProof"},
)
count2 = session.run("MATCH (c:Company) WHERE c.dedup_key = $dk RETURN count(c) AS cnt",
                     {"dk": md5("test-governance-proof").hexdigest()}).single()["cnt"]
assert count2 == count  # Must be unchanged

# Step 4: Cleanup
session.run("MATCH (c:Company {dedup_key: $dk}) DETACH DELETE c",
            {"dk": md5("test-governance-proof").hexdigest()})
```
