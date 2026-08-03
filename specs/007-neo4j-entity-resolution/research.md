# Research: Neo4j Graph Schema & Entity Resolution

**Created**: 2026-08-03 | **Branch**: `007-neo4j-entity-resolution`

Phase 0 output — every design decision is resolved here, grounded in the existing `src/graphdb/` module, the constitution, and real scraped sample data. There are no open `NEEDS CLARIFICATION` items.

## Decision: Canonical graph model (Company/Category/City/Source)

**Decision**: New graph writes use exactly four node types — `Company`, `Category`, `City`, `Source` — and three relationship types — `LISTED_IN`, `LOCATED_IN`, `SOURCED_FROM` — per the spec. Legacy node types (`Phone`, `Email`, `Website`, `Location`, `Industry`) and `HAS_PHONE`/`HAS_EMAIL`/`HAS_WEBSITE`/`BELONGS_TO` are no longer written by new code; existing legacy nodes already in a database are left untouched (spec Clarification Q2 → A).

**Rationale**: Contact data is attached as properties on `Company` (single-node lookup, simplest idempotent MERGE); categories/cities/sources are the only cardinal facts that warrant separate nodes and edges. The current runtime writer `src/graphdb/client.py` already follows this shape, so the change is a tightening, not a rewrite.

**Alternatives considered**:
- Keep the legacy sub-node model (`Phone`/`Email`/`Website`/`Location`/`Industry` nodes) → rejected: more nodes/edges to merge, no analytical benefit for this pipeline, and the requested schema is explicit.
- Write both models in parallel → rejected (spec Q2 option C): doubles write cost and maintenance with no added value.

## Decision: Identity via deterministic `dedup_key`, phone primary key

**Decision**: Reuse the existing `_dedup_key` scheme. Phone (last 10 digits, formatting-insensitive) is the identity when present → `md5("phone:<last10>")`; otherwise `md5("name:<normalized>")` or `md5("name:<normalized>|web:<host>")`.

**Rationale**: Matches the spec ("phone is the primary key when available") and Constitution §Deduplication Key. Content-derived ⇒ identical re-runs produce identical keys ⇒ MERGE is idempotent. Last-10-digits makes `+91 7971 671113` == `07971671113` == `7971671113`.

**Alternatives considered**: raw phone string as key (rejected: formatting variants would create duplicates); normalized-name-only key (rejected: weaker, only used when no phone/website).

## Decision: Idempotent SOURCED_FROM — MERGE on (company, source), SET properties

**Decision**: `MERGE (c)-[r:SOURCED_FROM]->(s)` keyed on the company `dedup_key` + `Source.name`, then `SET r.scraped_at, r.raw_record_id`. One edge per company/source pair; re-runs update the two properties to the latest run's values and never add an edge.

**Rationale**: This is what makes the second run of identical data add zero edges (Constitution IV). `raw_record_id` is content-derived (`source|company|primary_contact`), stable across identical re-runs, and kept on the edge for traceability to the originating raw record (FR-002).

**Alternatives considered**: one edge per unique `raw_record_id` (rejected: would create duplicate edges on re-run unless the id is perfectly stable — a fragile property of run order); CREATE (rejected explicitly by spec).

## Decision: Deterministic phone → fuzzy resolution, thresholded token_sort_ratio

**Decision**: Resolution is (1) deterministic phone match; (2) if no phone match, fuzzy `rapidfuzz.fuzz.token_sort_ratio` against existing `normalized_name` values scoped by a `STARTS WITH` prefix, merge only if score ≥ `fuzzy_match_threshold` (default 90); tie-break = highest score, then lexicographically smallest candidate name. Every comparison is logged (FR-006).

**Rationale**: `token_sort_ratio` is order-insensitive, ideal for "Tech Solutions Pvt Ltd" vs "Tech Solutions Pvt. Ltd." after normalization; it is already the in-repo choice. Candidate scoping by prefix + index bounds work to near-neighbours instead of a full scan. Deterministic tie-break keeps `Same input ⇒ same merge` (Constitution IV, no judgment calls).

**Alternatives considered**: `ratio` (order-sensitive — rejected); `partial_ratio` (too aggressive for company names — rejected); full-graph scan scoring (rejected: slow and unnecessary).

## Decision: Threshold configurable via `fuzzy_match_threshold` (default 90)

**Decision**: `src/config.py` gains `get_fuzzy_match_threshold()` reading top-level `fuzzy_match_threshold` from `config/targets.yaml`; absent ⇒ 90. The in-effect value is written to the review log line.

**Rationale**: Spec Clarification Q3 → A. Operators can tune merge aggressiveness without a code change; determinism is preserved because the value is fixed for a given run.

**Alternatives considered**: hardcoded constant (rejected per Q3); environment variable only (rejected: the repo already centralizes tunables in `targets.yaml`).

## Decision: Review log is a flat file with an exact field schema

**Decision**: `debug_output/fuzzy_matches.log`, one pipe-separated line per comparison: `timestamp|action|incoming_name|incoming_normalized|candidate_name|candidate_normalized|score|threshold|verdict`. Every comparison is logged, above and below threshold. Phone matches are logged at INFO, not to this file.

**Rationale**: Spec Clarification Q2 → A (flat file only); Constitution §Entity Resolution Transparency requires every fuzzy comparison recorded for manual spot-checking, and below-threshold comparisons must not vanish without trace. Pipe-separated keeps it human-readable and trivially parseable.

**Alternatives considered**: database table (rejected per Q2 — no relational schema change wanted); JSONL (equivalent, rejected for a minor readability edge to the existing human-oriented format).

## Decision: Name normalization set = existing extended set + `OPC`

**Decision**: Exact regex strip list: `pvt, ltd, llp, private limited, opc, inc, corp, corporation, llc, limited, co, company, technologies, solutions, services, systems, group, industries, enterprises` — punctuation removed first, whitespace collapsed.

**Rationale**: Evidence from a 38-name real sample (`debug_output/*_records.json`): the only legal form not already handled is `OPC` (One Person Company), e.g. `Nitai Technologies (OPC) Private Limited` → `nitai`. The sample yields 38 distinct normalized values (0 collisions), so the set is not over-aggressive in practice.

**Alternatives considered**: strip only the four suffixes named in the spec (rejected — would leave `technologies`/`solutions`/etc. causing near-identical companies to differ); also strip brand tokens `tech`/`it` (rejected — over-merges distinct companies such as `Basudeb It Solution` vs `Basudeb Solution`).

## Decision: Credentials env-only (Constitution III defect fix)

**Decision**: `src/graphdb/__init__.py` removes the hardcoded `DEFAULT_PASSWORD = "leadsbot"`; driver construction fails explicitly with a clear error if `NEO4J_URI`/`NEO4J_PASSWORD` are unset or empty. No credential value is added anywhere in source/config.

**Rationale**: Constitution III is fail-closed on credentials; the current default password is a committed credential equivalent and is a blocking defect (FR-011).

**Alternatives considered**: keep default for local convenience (rejected — violates fail-closed rule and risks accidental commits).

---

# Post-implementation deep review — fixes applied (2026-08-03)

A full code review of the committed feature produced H1/M1–M6/L1–L7 findings; all were fixed and re-validated. Recorded here for traceability.

## H1 — fuzzy normalization must not strip descriptor words (FIXED)

**Finding**: `normalize_company_name` strips business descriptors (`technologies|solutions|services|systems|group|industries|enterprises`). When the SAME function fed the fuzzy score, "Pinnacle It Solutions" and "Pinnacle It Services" both normalized to "pinnacle it" → permanent false-positive merge at score 100. Real 51-name sample had 0 collisions (latent, not yet triggered).

**Fix**: split into two functions. `fuzzy_normalize_company_name` strips ONLY legal suffixes (`pvt|ltd|llp|private limited|opc|inc|corp|corporation|llc|limited|co|company`); the fuzzy pass scores on it. Display `normalize_company_name` (descriptor-stripping) is kept for the stored `normalized_name`, prefix scan, and name `_dedup_key`.

**Evidence**: descriptor pairs now score well below 90 — `Pinnacle It Solutions` vs `Pinnacle It Services` = 73.2, `Tech Solutions India` vs `Tech Services India` = 71.8, vs `Tech Systems India` = 73.7, `Acme Technologies` vs `Acme Tech` = 69.2. Legal variants still merge at 100.0 (`Codetrex Infotech Pvt. Ltd.` vs `Codetrex Infotech`, `Nitai Technologies (OPC) Private Limited` vs `Nitai Technologies`). Idempotency counts unchanged (52/10/10/3/53/53/53, delta 0).

## H2 — destructive cleanup needs an opt-in guard (FIXED)

**Finding**: `MATCH (n) DETACH DELETE n` in `tests/test_graphdb_idempotency.py` and `scripts/demo_idempotency.py` runs against whatever DB `get_driver()` points to, with no guard.

**Fix**: both require `NEO4J_RESET_ALLOWED=1` in the environment before executing the delete; the test `pytest.skip`s otherwise, the demo `sys.exit`s with a clear message.

## M1 — display-name fields are ON CREATE only (FIXED)

**Finding**: Q3 `ON MATCH SET c.company_name = $name, c.normalized_name = $norm` made the display name last-write-wins (verified: cross-site merged node showed the IndiaMART name, not Justdial first-seen).

**Fix**: `company_name`/`normalized_name` removed from `ON MATCH`. First-seen identity is now immutable.

## M2 — run.py standalone path was bypassing the API (FIXED)

**Finding**: `run.py` called `upsert_company` per-row (no `ensure_schema`, no `city_slug`/`category_slug`/`lead_score_breakdown`) and read `s['Phone']`/`s['Email']` which `get_stats` no longer returns → swallowed KeyError → Neo4j stats always "--".

**Fix**: `run.py` now calls `ensure_schema` + `write_companies(driver, row_dicts)`; the stats line uses the actual `get_stats` keys (`Company/Category/City/Source` + relationship counts) and `close_driver()`.

## M3 — raw_record_id owned by the writer (FIXED)

**Finding**: pipeline passed `r.phone or r.email or r.website` (raw string with spaces/+) as `primary_contact`; the client fallback used digits-only. Contract requires digits.

**Fix**: `raw_record_id` is generated only in `src/graphdb/client.py` via `_primary_contact` (phone→digits). Pipeline no longer threads it.

## M4 — single URL→source mapping (FIXED)

**Finding**: `SITE_SOURCES` (client) vs `SITE_SOURCE_NAMES` (pipeline) duplicated and already diverged (`"Unknown"` vs `None`).

**Fix**: `source_name(url)` is the single mapping in `client.py`; pipeline delegates to it; `build_dashboard.py` keeps its own display-only fallback.

## M5 — PROJECT_KNOWLEDGE_GRAPH.md was stale (FIXED)

**Finding**: still described legacy Phone/Email/Website/Location/Industry nodes + HAS_* rels, Neo4j 6.2.0 (installed 5.20.0), and "pipeline does NOT write to Neo4j".

**Fix**: updated to the canonical sparse-schema model (Company/Category/City/Source; LISTED_IN/LOCATED_IN/SOURCED_FROM), neo4j 5.20.0, pipeline writes Neo4j.

## M6 — unknown source never appended (FIXED)

**Finding**: with `source_name = "Unknown"`, the Q3 sources CASE would append `"Unknown"` to a matched node's `sources` (latent — pipeline always passed a known source).

**Fix**: `source_name` returns `None` for unknown; `None` never enters `sources` and no `SOURCED_FROM` edge is created.

## L1 — dead code removed (FIXED)

`stats["skipped"]` (never set) and the unreachable `else: stats["merged_phone"] += 1` (match_type is only phone/fuzzy/None) removed from `write_companies`.

## L2 + L6 — one session per batch, one transaction per record (FIXED)

`write_companies` now reuses a single session; Q3–Q6 for a record run inside one `session.execute_write` transaction, so a partial failure rolls back cleanly.

## L3 — review-log pipe escaping + append lock (FIXED)

Field values now escape `|` as `\|` (per contract) instead of replacing with a space; appends are serialized under an advisory lock (`fuzzy_matches.log.lock`, msvcrt on win32 / fcntl on POSIX, plus an in-process lock) so concurrent writers never interleave lines or duplicate the header.

## L4 — credentials read at call time (FIXED)

`get_driver()` reads `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD` from the environment on each call (driver creation), not at import time, so the env can be set after import.

## L5 — schema metadata canonicalized (FIXED)

`src/graphdb/schema.py` `LABELS`/`REL_TYPES` now list only the canonical model (Company/Category/City/Source; LISTED_IN/LOCATED_IN/SOURCED_FROM). Constraints/indexes unchanged (4 constraints, 2 indexes).

## L7 — driver closed on error path (FIXED)

`src/pipeline.py:_write_to_neo4j` wraps the write in `try/finally close_driver()` so the driver is always released, including on failure.

## Validation after fixes

- `tests/test_graphdb.py`: 30 passed (13 existing + 17 new for H1/M3/M4/M6/L3/M1).
- Full suite: 601 passed, 1 skipped (idempotency skipped without `NEO4J_RESET_ALLOWED`).
- Live idempotency (`NEO4J_RESET_ALLOWED=1`): 1 passed — counts 52/10/10/3/53/53/53, delta 0, Run2 created=0.
- Demo (`NEO4J_RESET_ALLOWED=1`): refuses without opt-in; with opt-in prints IDEMPOTENT with identical counts.
- `python -m py_compile` clean on all modified modules.
