---

description: "Task list for Neo4j Graph Schema & Entity Resolution"
---

# Tasks: Neo4j Graph Schema & Entity Resolution

**Input**: Design documents from `/specs/007-neo4j-entity-resolution/`

**Prerequisites**: `plan.md` (required), `spec.md` (required for user stories), `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Tests ARE included — the user explicitly requested (a) the normalizer be validated against a real sample of scraped names, and (b) the idempotency test be run and documented. Write tests first, confirm they fail, then implement.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project at repository root: `src/`, `tests/`, `config/`, `scripts/`, `debug_output/`.
- Feature docs live in `specs/007-neo4j-entity-resolution/`.

---

## Phase 1: Setup — Dependencies

**Purpose**: Verify the two primary dependencies are present and importable before any code changes.

- [ ] T001 Verify `neo4j>=5.20` and `rapidfuzz>=3.0` are declared in `pyproject.toml` (currently lines 13–14). If either is missing, add it. Then run `pip install -e "."` from repo root and confirm imports succeed: `python -c "import neo4j; import rapidfuzz; print(neo4j.__version__, rapidfuzz.__version__)"`.

**Checkpoint**: Dependencies present and importable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 [P] Remove the hardcoded Neo4j password default in `src/graphdb/__init__.py` (line 12): `DEFAULT_PASSWORD = os.environ.get("NEO4J_PASSWORD", "leadsbot")` → `DEFAULT_PASSWORD = os.environ.get("NEO4J_PASSWORD")` (no fallback). In `get_driver()` (`src/graphdb/__init__.py:17`), if `NEO4J_PASSWORD` is unset/empty, `raise RuntimeError("NEO4J_PASSWORD not set — credentials must come from the environment")` BEFORE constructing the driver. `NEO4J_URI`/`NEO4J_USER` may keep their current safe defaults. Constitution Gate G1.
- [ ] T003 Replace `normalize_company_name` in `src/graphdb/client.py` (lines 25–38) with the exact plan version — add the Indian legal form `opc`, strip punctuation BEFORE suffix stripping, and replace suffixes with a space (not empty string). Exact code:

```python
import re

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(pvt|ltd|llp|private\s*limited|opc|inc|corp|corporation|llc|limited|"
    r"co|company|technologies|solutions|services|systems|group|industries|enterprises?)\b",
    re.IGNORECASE,
)

def normalize_company_name(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", " ", n)
    n = _LEGAL_SUFFIX_RE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n
```

  (Note: `import re` already exists in `src/graphdb/client.py` — do not duplicate it.)
- [ ] T004 [P] Extend the canonical constraints and indexes in `src/graphdb/schema.py` (CONSTRAINTS list at lines 29–37, INDEXES list at lines 39–42) WITHOUT removing existing entries. Add exactly:

```cypher
CREATE CONSTRAINT category_name IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE
CREATE CONSTRAINT city_name IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE
CREATE INDEX company_normalized_name IF NOT EXISTS FOR (c:Company) ON (c.normalized_name)
```

  Keep `company_dedup_key` and `source_name` constraints. Legacy Phone/Email/Website/Location/Industry constraints stay as-is (existing nodes left untouched per spec Q2); new writes simply stop creating those labels.

**Checkpoint**: Foundation ready — credentials env-only, normalizer canonical, schema supports canonical writes. User story implementation can now begin.

---

## Phase 3: User Story 1 — One Company, Many Sources Resolves to One Node (Priority: P1) 🎯 MVP

**Goal**: Every record resolves to a single Company node. Phone (last 10 digits) is the primary key when present; otherwise the name/website `dedup_key`; MERGE (never duplicate) on repeat scraping; SOURCED_FROM carries `scraped_at` + `raw_record_id`.

**Independent Test**: `tests/test_graphdb.py` unit tests (normalization table incl. `(OPC)`, `_dedup_key` determinism, phone-keyed resolution) run green with no Neo4j required.

### Tests for User Story 1 (tests requested — write FIRST, confirm FAIL, then implement) ⚠️

- [ ] T005 [P] [US1] Create `tests/test_graphdb.py` with the normalization table test: sample ≥30 real company names from `debug_output/{indiamart,justdial,tradeindia}_records.json`, assert `normalize_company_name` output is stable, lowercase, punctuation-free, and that `"Nitai Technologies (OPC) Private Limited"` → `"nitai"`. Assert the 38-name plan sample produces 38 distinct normalized values (no collisions). Reference the expected table in `specs/007-neo4j-entity-resolution/data-model.md` §Normalization sample. **Also add the cross-site phone-keying unit test (C1/C3)**: two records with identical phone but different `company_name` and different `source_url` (one `justdial.com`, one `indiamart.com`) MUST yield the SAME `_dedup_key` (phone last-10 primary — name/site irrelevant), proving phone-keyed matching merges records across sites.

### Implementation for User Story 1

- [ ] T006 [US1] Keep `_dedup_key` in `src/graphdb/client.py` (lines 41–57) UNCHANGED — it already implements the plan §2 identity contract (phone last-10 primary, else `name:<norm>|web:<host>`). Verify it against plan §2 and add a one-line docstring reference if missing.
- [ ] T007 [US1] Implement the deterministic phone match pass as a `_resolve` helper in `src/graphdb/client.py`, run before any write: if `phone` is present and has ≥10 digits, run the pre-query `MATCH (c:Company) WHERE c.dedup_key = $phone_dk RETURN c.dedup_key AS dk, c.company_name AS name` with `$phone_dk = _dedup_key(company_name, phone)`; if a row returns, resolve to that `dk` with `match_type="phone"`. No fuzzy log entry is generated for a phone match.
- [ ] T008 [US1] Implement Q3–Q6 MERGE queries in `upsert_company` (`src/graphdb/client.py:85`) using the resolved `dk` from `_resolve`. Run each with parameters and no duplicate writes:

```cypher
MERGE (c:Company {dedup_key: $dk})
ON CREATE SET c.company_name = $name, c.normalized_name = $norm, c.phone = $phone,
  c.email = $email, c.website = $website, c.address = $address, c.industry_code = $industry_code,
  c.first_seen = $now, c.last_seen = $now, c.sources = $sources
ON MATCH SET c.company_name = $name, c.normalized_name = $norm,
  c.phone = CASE WHEN $phone IS NOT NULL AND $phone <> '' THEN $phone ELSE c.phone END,
  c.email = CASE WHEN $email IS NOT NULL AND $email <> '' THEN $email ELSE c.email END,
  c.website = CASE WHEN $website IS NOT NULL AND $website <> '' THEN $website ELSE c.website END,
  c.address = CASE WHEN $address IS NOT NULL AND $address <> '' THEN $address ELSE c.address END,
  c.industry_code = CASE WHEN $industry_code IS NOT NULL AND $industry_code <> '' THEN $industry_code ELSE c.industry_code END,
  c.last_seen = $now,
  c.sources = CASE WHEN $src_name IS NOT NULL AND NOT $src_name IN COALESCE(c.sources, [])
    THEN COALESCE(c.sources, []) + [$src_name] ELSE c.sources END
```

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (cat:Category {name: $category})
MERGE (c)-[:LISTED_IN]->(cat)
```

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (city:City {name: $city})
MERGE (c)-[:LOCATED_IN]->(city)
```

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (s:Source {name: $source})
MERGE (c)-[r:SOURCED_FROM]->(s)
SET r.scraped_at = $now, r.raw_record_id = $raw_record_id
```

  Params: `sources = [src_name]` if a source is known else `[]` (create path); `src_name` = `None` on create so the append branch is inert; `now` = run date ISO. `first_seen` MUST only ever be set in `ON CREATE` (FR-008). Keep `lead_score`/`lead_score_breakdown` as Company properties on create (data-layer isolation).
- [ ] T009 [US1] Thread `raw_record_id` + `source_name` into the row dicts in `_write_to_neo4j` (`src/pipeline.py:350-363`). Add `"source_name": ...` (reuse `src/graphdb.client._source_name(source_url)`) and `"raw_record_id": f"{source_name}|{company_name}|{primary_contact}".lower()` where `primary_contact` = phone digits if present, else email, else website (whitespace collapsed) — deterministic and stable across identical re-runs. Pass both through to `write_companies`/`upsert_company`.

**Checkpoint**: At this point, User Story 1 is fully functional and testable independently — same-phone records from different sources resolve to one Company node with an accumulating `sources` list.

---

## Phase 4: User Story 2 — Fuzzy Name Matching With a Full Review Trail (Priority: P2)

**Goal**: Phone-less records are compared against existing Company names with `rapidfuzz.token_sort_ratio`; merge only at score ≥ configured threshold (default 90); every comparison — matched or not — is appended to `debug_output/fuzzy_matches.log`.

**Independent Test**: `tests/test_graphdb.py` fuzzy + review-log unit tests (stubbed candidates, no DB): a near-identical variant merges (score ≥ threshold) and IS logged; a dissimilar name does not merge but IS logged with its score; the log line matches the exact schema.

### Tests for User Story 2 (tests requested — write FIRST, confirm FAIL) ⚠️

- [ ] T010 [P] [US2] In `tests/test_config.py` add tests for `get_fuzzy_match_threshold()`: default is `90` when `fuzzy_match_threshold` is absent; reads the int when present in the config dict; falls back to `90` on a non-numeric value.

### Implementation for User Story 2

- [ ] T011 [P] [US2] Add `get_fuzzy_match_threshold(config=None)` to `src/config.py` (after `load_full_config` at line 37): `config = load_full_config()` if `None`, return `config.get("fuzzy_match_threshold", 90)` coerced to `int`, else `90` on `TypeError`/`ValueError`. Add `fuzzy_match_threshold: 90` as a top-level key in `config/targets.yaml`.
- [ ] T012 [P] [US2] Replace `_write_fuzzy_review` in `src/graphdb/client.py` (lines 69–77) with the exact review-log writer. Signature: `_write_fuzzy_review(incoming, incoming_norm, candidate, candidate_norm, score, threshold, verdict)`. Append one pipe-separated line to `debug_output/fuzzy_matches.log` (create dir, never truncate; write the header line once when the file is created). Exact schema:

```text
timestamp|action|incoming_name|incoming_normalized|candidate_name|candidate_normalized|score|threshold|verdict
2026-08-03T12:00:00.000Z|FUZZY_MATCH|Codetrex Infotech Pvt. Ltd.|codetrex infotech|Codetrex Infotech|codetrex infotech|100.0|90|matched
```

  - `timestamp`: ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`); `action` always `FUZZY_MATCH`; `score`: `token_sort_ratio` rounded to 1 decimal; `threshold`: in-effect int; `verdict`: `matched` | `not_matched`. Escape `|` inside names if any. On `OSError`, log a warning and surface the failure (never silently drop).
- [ ] T013 [US2] Implement the fuzzy pass in `_resolve` (`src/graphdb/client.py`) — runs ONLY when the phone pass found no match (FR-005). Scope candidates via index-backed prefix query `MATCH (c:Company) WHERE c.normalized_name STARTS WITH $prefix RETURN c.dedup_key AS dk, c.company_name AS name, c.normalized_name AS norm` with `prefix = norm[:3] if len(norm) >= 3 else norm`. For each candidate compute `score = float(fuzz.token_sort_ratio(norm, cand_norm))` and ALWAYS call `_write_fuzzy_review(...)` (verdict `matched` if `score >= threshold` else `not_matched`). Track best candidate: highest score; on a score tie, lexicographically smallest `company_name`. If best ≥ threshold, resolve with `match_type="fuzzy"` and `fuzzy_score`. Else resolve as new with `match_type=None`. Threshold comes from `get_fuzzy_match_threshold()` and must be threaded from `write_companies`.

**Checkpoint**: User Stories 1 AND 2 both work independently — full resolution pipeline with auditable review trail.

---

## Phase 5: User Story 3 — Idempotent Graph Writes (Priority: P3)

**Goal**: Re-running the same day's data changes no counts; the run reports distinct created / phone-matched / fuzzy-matched counts plus total graph size.

**Independent Test**: `tests/test_graphdb_idempotency.py` (integration) — run the 51-record fixture twice, assert every node/relationship count is identical (delta 0). Skipped when no live Neo4j is reachable.

### Tests for User Story 3 (tests requested — write FIRST, confirm FAIL) ⚠️

- [ ] T014 [P] [US3] Create `scripts/make_graphdb_fixture.py` that reads `debug_output/{indiamart,justdial,tradeindia}_records.json` (28+10+13 = 51 records), augments each with `city_slug`/`category_slug` from crawl context and deterministic `lead_score`/`lead_score_breakdown`, and writes the committed fixture `tests/fixtures/graphdb_batch.json`. **MANDATORY (cross-site phone-merge coverage, C1/C2)**: the real captures contain ZERO cross-record phone matches and no TradeIndia phone/email — the fixture MUST therefore add synthetic records so phone-keyed cross-site merging is actually exercised: (a) one JustDial listing + one IndiaMART listing for the SAME real company with identical phone but different `company_name`/`source_url` (assert this pair shares a phone-last-10 group), (b) one TradeIndia record carrying phone+email (proves Phase 4 enrichment data feeds the phone pass). Assert before writing: ≥1 phone-last-10 group contains records from ≥2 distinct sites. Run it once and check in the generated fixture (the test never re-derives it).
- [ ] T015 [US3] Create `tests/test_graphdb_idempotency.py` marked `@pytest.mark.integration`, `pytest.skip` when `NEO4J_URI`/`NEO4J_PASSWORD` env is unset or connectivity fails. Procedure: (1) `MATCH (n) DETACH DELETE n` on the test DB; (2) `write_companies(driver, BATCH)`; (3) snapshot counts with the exact count queries; (4) run `write_companies(driver, BATCH)` again; (5) re-run the same queries and assert every value equals the Run-1 snapshot (delta 0). Exact count queries:

```cypher
MATCH (c:Company) RETURN count(c) AS companies
MATCH (cat:Category) RETURN count(cat) AS categories
MATCH (city:City) RETURN count(city) AS cities
MATCH (s:Source) RETURN count(s) AS sources
MATCH ()-[r:LISTED_IN]->() RETURN count(r) AS listed_in
MATCH ()-[r:LOCATED_IN]->() RETURN count(r) AS located_in
MATCH ()-[r:SOURCED_FROM]->() RETURN count(r) AS sourced_from
```

  Spot-checks: a pre-existing node's `first_seen` identical across runs; `sources` arrays contain each directory at most once.
  **Cross-site phone-merge assertion (C1/C3)**: after Run 1, run `MATCH (c:Company) WHERE c.phone = $phone RETURN c.company_name AS name, c.sources AS sources` for the synthetic JustDial/IndiaMART pair's shared phone (last-10-digits form) and assert exactly ONE Company node matches and its `sources` contains BOTH directory names. This proves phone-keyed resolution merges records originating from different sites.

### Implementation for User Story 3

- [ ] T016 [US3] Run the idempotency test against a live Neo4j and record the results in `specs/007-neo4j-entity-resolution/quickstart.md` §Idempotency: the two snapshots (table of the 7 counts, Run1 vs Run2), delta = 0 for all seven, and the review-log note (log grew, counts did not). If no Neo4j is reachable, document the skip + the exact command to run it later (`NEO4J_URI=... NEO4J_PASSWORD=... python -m pytest tests/test_graphdb_idempotency.py -m integration -v`).

**Checkpoint**: All user stories independently functional — re-runs provably idempotent.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories (FR-010 / SC-005 reporting; constitution verification).

- [ ] T017 End-of-run graph-size + match-type reporting. In `src/graphdb/client.py` ensure `write_companies` (line 245) returns `created`, `merged_phone`, `merged_fuzzy`, `skipped`; extend it to also log total graph size using `get_stats` (line 317) — Company/Category/City/Source counts + LISTED_IN/LOCATED_IN/SOURCED_FROM counts. In `src/pipeline.py` `main_pipeline` (lines 439–471) log the full match-type breakdown plus total graph size and keep `summary["neo4j_failed"]` (Constitution G4 — a failed run must never look like a 0-count success). Per FR-010/SC-005.
- [ ] T018 Run the full suite from repo root: `python -m pytest -q` (integration tests stay skipped without live Neo4j). Verify constitution gates: `git grep -iE "password|secret|NEO4J_.*leadsbot" -- ":!*.log"` returns only env-loading references (no committed credentials); spot-check `debug_output/fuzzy_matches.log` lines match the exact review-log schema; confirm `lead_score`/`lead_score_breakdown` appear only on the data-layer Company node.

**Checkpoint**: Full suite green; gates verified; feature complete.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on T001 — BLOCKS all user stories.
- **User Stories (Phase 3+)**: All depend on Foundational completion.
  - US1 → US2 → US3 sequentially, or US2 in parallel with US1 once T003 (normalizer) lands (both consume the same `_resolve` helper; coordinate edits to `src/graphdb/client.py`).
- **Polish (Final Phase)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: After Foundational — no dependencies on other stories. Consumes T003 (normalizer), T004 (schema), T002 (credentials).
- **US2 (P2)**: After Foundational — depends on T003 (normalizer); integrates with the `_resolve` helper from T007 but is independently testable via stubbed candidates.
- **US3 (P3)**: After Foundational — needs T004 (schema), T007 (MERGE queries), T009 (raw_record_id threading), and T014 (fixture).

### Within Each User Story

- Tests (included) MUST be written and FAIL before implementation.
- Core implementation before integration (e.g., T007 before T009).
- Story complete before moving to next priority.

### Parallel Opportunities

- **Phase 2**: T002, T004 parallel with each other (different files); T003 (normalizer) is the critical path.
- **Phase 3**: T005 (tests) before T006–T009; T009 (pipeline) is a different file from T007/T008 (client.py).
- **Phase 4**: T010 (config.py), T011 (config/targets.yaml + client.py writer) parallel with each other and with US1; T013 depends on T010/T012.
- **Phase 5**: T014 (script) parallel with US1/US2 work; T015 depends on T014; T016 depends on T015.

---

## Parallel Example: User Story 2

```bash
# Launch config + review-log writer together (different files):
Task: "Add get_fuzzy_match_threshold() to src/config.py + config/targets.yaml"
Task: "Replace _write_fuzzy_review in src/graphdb/client.py"
# Then (depends on both):
Task: "Implement the fuzzy pass in _resolve in src/graphdb/client.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: `python -m pytest tests/test_graphdb.py -q`.
5. Deploy/demo if ready — this alone delivers the core value: one Company node per business across sources.

### Incremental Delivery

1. Setup + Foundational → Foundation ready (env-only credentials, canonical normalizer, canonical schema).
2. Add US1 (phone-keyed resolution + MERGE queries) → Test → MVP.
3. Add US2 (fuzzy + review log) → Test.
4. Add US3 (idempotency fixture + two-run proof) → Test.
5. Polish: end-of-run reporting + full-suite constitution verification.

### Parallel Team Strategy

With multiple developers: after Phase 2, Developer A takes US1, Developer B takes US2 (both edit `src/graphdb/client.py` — coordinate), Developer C takes US3 + fixture.

---

## Notes

- `[P]` tasks = different files, no dependencies.
- `[Story]` label maps task to a user story for traceability (US1 = spec §User Story 1, etc.).
- Each user story is independently completable and testable.
- Verify tests fail before implementing.
- Commit after each task or logical group (feature branch `007-neo4j-entity-resolution`).
- Do NOT commit credentials; `debug_output/` review logs must stay untracked (verify `.gitignore`).
- User-requested breakdown mapping: item 1 → T001; item 2 → T003 + T005; item 3 → T006 + T007; item 4 → T010–T013; item 5 → T004 + T007 + T009; item 6 → T017; item 7 → T014–T016.
