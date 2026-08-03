# Implementation Plan: Neo4j Graph Schema & Entity Resolution

**Branch**: `007-neo4j-entity-resolution` | **Date**: 2026-08-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-neo4j-entity-resolution/spec.md`

## Summary

Implement the canonical Neo4j graph model (Company / Category / City / Source with LISTED_IN / LOCATED_IN / SOURCED_FROM) and a deterministic+thresholded entity-resolution write path in `src/graphdb/`, grounded in the existing `client.py` implementation. The feature resolves each scraped record to a single Company node (phone-keyed first, then name fuzzy at `fuzzy_match_threshold`, default 90), merges rather than duplicates on repeat scraping, logs every fuzzy comparison to `debug_output/fuzzy_matches.log`, and is provably idempotent for same-day re-runs. Concretely the delta over the current code: add `OPC` to name normalization, log all fuzzy comparisons (not just ≥90) with an exact field schema, read the threshold from config, add `raw_record_id` + `scraped_at` on SOURCED_FROM, add Category/City uniqueness constraints + a normalized_name index, thread `raw_record_id` through the pipeline, remove the hardcoded Neo4j password, and add unit + integration idempotency tests.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**: `neo4j>=5.20`, `rapidfuzz>=3.0`, `PyYAML` (existing config loader). All already declared in `pyproject.toml`.

**Storage**: Neo4j graph store (`NEO4J_URI`, default `bolt://localhost:7687`) alongside the existing SQLite data layer (unchanged). New writes target the canonical node/relationship model only.

**Testing**: `pytest` (repo standard). `tests/test_graphdb.py` (unit, no DB) + `tests/test_graphdb_idempotency.py` (integration, skipped unless a live Neo4j is reachable).

**Target Platform**: Python application; the pipeline runs as a scheduled job (server).

**Project Type**: Python application — batch data pipeline.

**Performance Goals**: Daily batch of ~50–500 records across 3 sources; single-node Neo4j; no sub-second latency target. Fuzzy pass is candidate-scoped via a `STARTS WITH` prefix + index to avoid a full graph scan.

**Constraints**: Idempotency (Constitution IV); credentials via environment variables only (Constitution III); fail-loudly with explicit `neo4j_failed` flag (Constitution V); deterministic resolution (no ML/judgment); `lead_score`/`lead_score_breakdown` stay data-layer-only (Constitution Data Layer Isolation).

**Scale/Scope**: 3 directory sources (IndiaMART, Justdial, TradeIndia), canonical graph model for all new writes; legacy node types (Phone/Email/Website/Location/Industry) are no longer written (existing ones left untouched per spec Q2).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Gate | Requirement | Design compliance |
|------|-------------|-------------------|
| G1 (III. Credential Security) | Neo4j URI/user/password via env vars only; fail explicitly when missing; nothing committed | `src/graphdb/__init__.py` currently has `DEFAULT_PASSWORD = "leadsbot"` — **defect to remove**. Driver must raise if `NEO4J_PASSWORD`/`NEO4J_URI` unset. |
| G2 (IV. Idempotent Operations) | Re-running same day's data twice changes no counts; MERGE on identity; `first_seen` never overwritten | MERGE on `dedup_key`; relationships MERGEd keyed on company+category / company+city / company+source; `first_seen` only in `ON CREATE`. Proven by the two-run integration test (below). |
| G3 (Entity Resolution Transparency) | Every fuzzy comparison logged with both names + score + threshold to `debug_output/fuzzy_matches.log`; per-run counts (created / phone / fuzzy / total size) | All comparisons logged to the review file (exact schema below); run counts logged. |
| G4 (V. Fail Loudly) | Graph-write failure reported explicitly, not as 0-count | Pipeline already sets `summary["neo4j_failed"] = True` on exception; retained. |
| G5 (Data Layer Isolation) | `lead_score`/`lead_score_breakdown` only in data layer (Company node) | Retained as Company properties; no user-facing surface touched. |
| G6 (VI. CodeGraph-First) | Design grounded in existing module | Plan derived from `src/graphdb/{client,schema,migrate}.py`, `src/config.py`, `src/pipeline.py`, `src/models.py` (queried via CodeGraph). |

**Result**: GATES PASS — no violations requiring complexity justification.

## Project Structure

### Documentation (this feature)

```text
specs/007-neo4j-entity-resolution/
├── plan.md              # this file (/speckit.plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output (validation guide)
├── contracts/           # Phase 1 output
│   ├── graph-schema.md          # node/relationship DDL + MERGE queries
│   ├── entity-resolution.md     # resolution algorithm contract
│   └── review-log-format.md     # exact review log schema
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
├── config.py                 # + get_fuzzy_match_threshold()
├── graphdb/
│   ├── __init__.py           # remove hardcoded default password; env-only
│   ├── schema.py             # canonical constraints + indexes
│   └── client.py             # normalize (OPC), resolution, MERGE queries, review log
├── pipeline.py               # thread raw_record_id into row dicts
└── models.py                 # (unchanged)

config/
└── targets.yaml              # + fuzzy_match_threshold: 90

tests/
├── test_config.py            # + threshold default/override tests
├── test_graphdb.py           # unit: normalization table, dedup_key, fuzzy, review log
├── test_graphdb_idempotency.py  # integration: exact two-run count comparison
└── fixtures/
    └── graphdb_batch.json    # committed 51-record fixture derived from debug_output

scripts/
└── make_graphdb_fixture.py   # generates tests/fixtures/graphdb_batch.json from captured records
```

**Structure Decision**: Extend the existing single-project layout; all changes live in the existing `src/graphdb/` module, `src/config.py`, `src/pipeline.py`, `config/targets.yaml`, and new `tests/test_graphdb*.py`. No new packages.

## Design — Exact Specifications

### 1. Exact name normalization function

Evidence base: 38 real scraped names sampled from `debug_output/{indiamart,justdial,tradeindia}_records.json` (see `data-model.md` §Normalization sample). The only legal form not already handled is `OPC` (e.g. `Nitai Technologies (OPC) Private Limited`). Exact function (replace `src/graphdb/client.py:normalize_company_name`):

```python
import re

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(pvt|ltd|llp|private\s*limited|opc|inc|corp|corporation|llc|limited|"
    r"co|company|technologies|solutions|services|systems|group|industries|enterprises?)\b",
    re.IGNORECASE,
)

def normalize_company_name(name: str) -> str:
    """Deterministic canonical form for entity resolution.

    Lowercase; strip punctuation to whitespace; remove legal/corporate suffixes
    (including the Indian One-Person-Company form `opc`); collapse whitespace.
    """
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    n = _LEGAL_SUFFIX_RE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n
```

Punctuation is removed **before** suffix stripping so `Pvt. Ltd.`, `(OPC)`, and `Private Limited` all normalize correctly. On the 38-name sample this yields 38 distinct normalized values (0 collisions).

### 2. Exact dedup/identity key

Keep the existing scheme in `src/graphdb/client.py:_dedup_key` (unchanged):

```python
def _dedup_key(company_name: str, phone: str | None = None, website: str | None = None) -> str:
    raw = ""
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            raw = f"phone:{digits[-10:]}"          # phone is the primary key
    if not raw:
        n = normalize_company_name(company_name)
        w = (website or "").lower().strip()
        w = re.sub(r"^https?://", "", w).rstrip("/")
        raw = f"name:{n}|web:{w}" if w else f"name:{n}"
    return md5(raw.encode()).hexdigest()
```

### 3. Exact Cypher MERGE queries

**Constraints & indexes** (`src/graphdb/schema.py`):

```cypher
CREATE CONSTRAINT company_dedup_key IF NOT EXISTS FOR (c:Company) REQUIRE c.dedup_key IS UNIQUE
CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE
CREATE CONSTRAINT category_name IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE
CREATE CONSTRAINT city_name IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE
CREATE INDEX company_normalized_name IF NOT EXISTS FOR (c:Company) ON (c.normalized_name)
CREATE INDEX company_name IF NOT EXISTS FOR (c:Company) ON (c.company_name)
```

**Resolution pre-queries** (run before the write):

```cypher
-- Q1 deterministic phone match
MATCH (c:Company) WHERE c.dedup_key = $phone_dk
RETURN c.dedup_key AS dk, c.company_name AS name

-- Q2 fuzzy candidate scan (index-backed prefix)
MATCH (c:Company) WHERE c.normalized_name STARTS WITH $prefix
RETURN c.dedup_key AS dk, c.company_name AS name, c.normalized_name AS norm
```

**Q3 — MERGE Company** (single query for both match and create; `first_seen` set only on create, never overwritten):

```cypher
MERGE (c:Company {dedup_key: $dk})
ON CREATE SET
  c.company_name = $name,
  c.normalized_name = $norm,
  c.phone = $phone,
  c.email = $email,
  c.website = $website,
  c.address = $address,
  c.industry_code = $industry_code,
  c.first_seen = $now,
  c.last_seen = $now,
  c.sources = $sources
ON MATCH SET
  c.company_name = $name,
  c.normalized_name = $norm,
  c.phone = CASE WHEN $phone IS NOT NULL AND $phone <> '' THEN $phone ELSE c.phone END,
  c.email = CASE WHEN $email IS NOT NULL AND $email <> '' THEN $email ELSE c.email END,
  c.website = CASE WHEN $website IS NOT NULL AND $website <> '' THEN $website ELSE c.website END,
  c.address = CASE WHEN $address IS NOT NULL AND $address <> '' THEN $address ELSE c.address END,
  c.industry_code = CASE WHEN $industry_code IS NOT NULL AND $industry_code <> '' THEN $industry_code ELSE c.industry_code END,
  c.last_seen = $now,
  c.sources = CASE
    WHEN $src_name IS NOT NULL AND NOT $src_name IN COALESCE(c.sources, [])
    THEN COALESCE(c.sources, []) + [$src_name]
    ELSE c.sources
  END
```

Parameters: `{dk, name, norm, phone, email, website, address, industry_code, now, sources, src_name}`. `sources` = `[src_name]` if a source is known else `[]` (create path); `src_name` = directory name (create path passes `None` so the append-if-absent branch is inert).

**Q4 — LISTED_IN** (category; MERGE keyed on company+category → no duplicates):

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (cat:Category {name: $category})
MERGE (c)-[:LISTED_IN]->(cat)
```

**Q5 — LOCATED_IN** (city; MERGE keyed on company+city):

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (city:City {name: $city})
MERGE (c)-[:LOCATED_IN]->(city)
```

**Q6 — SOURCED_FROM** (source; MERGE keyed on company+source — one edge per company/source pair; `scraped_at` + `raw_record_id` are `SET` (latest run wins) so re-runs add no edges):

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (s:Source {name: $source})
MERGE (c)-[r:SOURCED_FROM]->(s)
SET r.scraped_at = $now, r.raw_record_id = $raw_record_id
```

**`raw_record_id` definition** (deterministic, content-derived, stable across identical re-runs): `f"{source_name}|{company_name}|{primary_contact}".lower()` where `primary_contact` = phone digits if present, else email, else website (whitespace collapsed). Computed in `_write_to_neo4j`.

### 4. Exact rapidfuzz integration and threshold application

`src/graphdb/client.py` — resolution order and scoring:

```python
from rapidfuzz import fuzz

def _resolve(driver, record: dict, threshold: int) -> dict:
    phone = (record.get("phone") or "").strip() or None
    norm = normalize_company_name(record["company_name"])
    # 1. Deterministic phone match (primary key)
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            row = _run(Q1, {"phone_dk": _dedup_key(record["company_name"], phone)}).single()
            if row:
                return {"dk": row["dk"], "match_type": "phone", "matched_name": row["name"]}
    # 2. Fuzzy name pass (only when no phone match)
    prefix = norm[:3] if len(norm) >= 3 else norm
    best = None  # (score, candidate_name, dk)
    for row in _run(Q2, {"prefix": prefix}):
        cand_norm = row["norm"] or normalize_company_name(row["name"] or "")
        score = float(fuzz.token_sort_ratio(norm, cand_norm))
        verdict = "matched" if score >= float(threshold) else "not_matched"
        _write_fuzzy_review(
            incoming=record["company_name"], incoming_norm=norm,
            candidate=row["name"] or "", candidate_norm=cand_norm,
            score=score, threshold=threshold, verdict=verdict,
        )
        if score >= float(threshold):
            if best is None or score > best[0] or (score == best[0] and (row["name"] or "") < best[1]):
                best = (score, row["name"] or "", row["dk"])
    if best:
        return {"dk": best[2], "match_type": "fuzzy", "matched_name": best[1], "fuzzy_score": best[0]}
    return {"dk": _dedup_key(record["company_name"], phone, record.get("website")), "match_type": None}
```

- **Threshold source**: `get_fuzzy_match_threshold()` in `src/config.py` — reads top-level `fuzzy_match_threshold` from `config/targets.yaml`, defaults to `90` when absent. Exact:

```python
def get_fuzzy_match_threshold(config: dict | None = None) -> int:
    if config is None:
        config = load_full_config()
    val = config.get("fuzzy_match_threshold", 90)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 90
```

- **Tie-break (deterministic)**: among candidates ≥ threshold, pick the highest `token_sort_ratio`; on a score tie, the lexicographically smallest candidate `company_name`. (Same input ⇒ same pick.)
- After `_resolve`, `upsert_company` runs Q3–Q6 with the resolved `dk`, then classifies the run stat as `created` / `merged_phone` / `merged_fuzzy` from `match_type`.

### 5. Exact review log schema (fields per match attempt)

Flat file `debug_output/fuzzy_matches.log` — one line per fuzzy comparison, pipe-separated, header written once when the file is created:

```
timestamp|action|incoming_name|incoming_normalized|candidate_name|candidate_normalized|score|threshold|verdict
```

Example:

```
2026-08-03T12:00:00.000Z|FUZZY_MATCH|Codetrex Infotech Pvt. Ltd.|codetrex infotech|Codetrex Infotech|codetrex infotech|100.0|90|matched
2026-08-03T12:00:00.100Z|FUZZY_MATCH|Basudeb It Solution|basudeb it solution|Hub It Infotech|hub it infotech|40.0|90|not_matched
```

- `timestamp`: ISO 8601 UTC.
- `action`: always `FUZZY_MATCH` (every comparison is logged, **whether or not** it crosses the threshold).
- `score`: token_sort_ratio rounded to 1 decimal; `threshold`: the in-effect integer; `verdict`: `matched` | `not_matched`.
- Phone-keyed merges are **not** written to this file; they are logged at INFO (`Entity resolution: phone match for '<incoming>' -> existing '<name>' (phone=<last10>)`).
- Exact writer replaces `src/graphdb/client.py:_write_fuzzy_review`; appends a line and never truncates.

### 6. Exact idempotency test procedure

**Input batch**: `tests/fixtures/graphdb_batch.json` — a committed, fixed 51-record fixture derived from the real captures `debug_output/{indiamart,justdial,tradeindia}_records.json` (28+10+13) via `scripts/make_graphdb_fixture.py`, augmented with `city_slug`/`category_slug` from the crawl context and `lead_score`/`lead_score_breakdown` (deterministic). Generated once at implementation time and checked in; the test never re-derives it. **Cross-site coverage**: the real captures contain zero cross-record phone matches and no TradeIndia phone/email, so the fixture script MUST add synthetic records — a JustDial + IndiaMART pair sharing one phone (different names/sources) and one TradeIndia record carrying phone+email — and assert ≥1 phone-last-10 group spans ≥2 distinct sites before writing (proves the phone pass merges across sites, incl. Phase 4 enrichment data; see spec Assumptions).

**Procedure** (`tests/test_graphdb_idempotency.py`, `@pytest.mark.integration`, skipped when no live Neo4j is reachable — e.g. `NEO4J_URI`/`NEO4J_PASSWORD` env unset or connectivity fails):

1. On a dedicated test database, clear the graph: `MATCH (n) DETACH DELETE n`.
2. **Run 1**: `write_companies(driver, BATCH)`.
3. Snapshot counts with **exact** count queries:

```cypher
MATCH (c:Company) RETURN count(c) AS companies
MATCH (cat:Category) RETURN count(cat) AS categories
MATCH (city:City) RETURN count(city) AS cities
MATCH (s:Source) RETURN count(s) AS sources
MATCH ()-[r:LISTED_IN]->() RETURN count(r) AS listed_in
MATCH ()-[r:LOCATED_IN]->() RETURN count(r) AS located_in
MATCH ()-[r:SOURCED_FROM]->() RETURN count(r) AS sourced_from
```

4. **Run 2**: `write_companies(driver, BATCH)` again (same fixture).
5. Re-run the same count queries; **assert every value equals the Run-1 snapshot (delta 0)** — Company, Category, City, Source, LISTED_IN, LOCATED_IN, SOURCED_FROM.
6. Spot-checks: `first_seen` is identical across runs for a pre-existing node; `sources` arrays contain each directory once (no duplicates); the review log grew but counts did not.

**Unit tests** (`tests/test_graphdb.py`, no DB): normalization table (real names → expected normalized, incl. `(OPC)`), `_dedup_key` determinism, `get_fuzzy_match_threshold` default/override, fuzzy selection + threshold + deterministic tie-break (stubbed candidates), review-log writer field/format correctness.

## Complexity Tracking

Not required — no constitution violations to justify.

## Phase Plan

- **Phase 0 (research.md)**: design decisions — canonical model, identity scheme, idempotent SOURCED_FROM, threshold configurability, review-log schema, OPC normalization.
- **Phase 1 (data-model.md, contracts/, quickstart.md)**: entity model + sample normalization table; contract docs for graph schema (DDL + MERGE queries), entity resolution, review log; quickstart validation guide including the exact idempotency procedure.
- **Phase 2 (`/speckit.tasks`)**: task breakdown implementing the code changes listed under Source Code above.
