---
description: "Task list for governance compliance feature implementation"
---

# Tasks: Governance Compliance

**Input**: Design documents from `specs/002-governance-compliance/`

**Prerequisites**: plan.md, spec.md, constitution.md

## Phase 1: Setup — neo4j Dependency Verification

**Purpose**: Verify neo4j driver is installable and importable before any code changes.

- [ ] T001 Verify `neo4j==5.20.0` is installable and importable via `pip install neo4j==5.20.0; python -c "import neo4j; print(neo4j.__version__)"` from repo root

---

## Phase 2: Foundational — Checkpointing Infrastructure

**Purpose**: Enable checkpointing that US5 idempotency depends on.

- [ ] T002 Pass `crawldir=".scrapling_checkpoints"` to `super().__init__()` in `src/scraper/spider.py:142`
- [ ] T003 Append `.scrapling_checkpoints/` to `.gitignore`

---

## Phase 3: User Story 1 — Every Target's Disposition Logged (P1)

**Goal**: Neo4j failures produce `"neo4j_failed": true`, never silent `neo4j_created: 0`. All log levels corrected per constitution. JD ASN stats accurately label distinct proxy IPs.

- [ ] T004 [US1] Fix `src/pipeline.py:368` — change `except ImportError:` block from `logger.warning` + silent return to `logger.error` + `raise`
- [ ] T005 [US1] Fix `src/pipeline.py:371` — change `except Exception:` block from `logger.warning` + silent return to `logger.error` + `raise`
- [ ] T006 [US1] Wrap `_write_to_neo4j()` call in `main_pipeline()` at `src/pipeline.py:420-429` with try/except that sets `summary["neo4j_failed"] = True` on failure
- [ ] T007 [P] [US1] Track distinct proxy IPs via a `set()` not a counter at `src/scraper/spider.py:421-424` for JD ASN stats

---

## Phase 4: User Story 5 — Idempotency Proof (P3)

**Goal**: Standalone Neo4j write script proves MERGE idempotency. CI pins exact neo4j version.

- [ ] T008 [P] [US5] Create `scripts/test_neo4j_write.py` — reads `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`, runs MERGE, counts, re-runs MERGE (asserts count unchanged), DETACH DELETEs test node, prints node count created and queried, exits 0/1
- [ ] T009 [P] [US5] Add `pip install neo4j==5.20.0` step before `pip install -e "."` in `.github/workflows/daily.yml:41-42`

---

## Phase 5: User Story 2 — Entity-Resolution Merge Audit Log (P1)

**Goal**: Every fuzzy name-match written to `debug_output/fuzzy_matches.log`. Phone matches logged at INFO. Sub-threshold candidates logged at DEBUG.

- [ ] T010 [P] [US2] Append fuzzy-match entries to `debug_output/fuzzy_matches.log` in `src/graphdb/client.py:131-140` with format `[timestamp] FUZZY_MATCH score=N threshold=90 "NameA" -> "NameB"`; create `debug_output/` dir on first write
- [ ] T011 [P] [US2] Log phone matches at INFO level with both company names and phone used in `src/graphdb/client.py` within `upsert_company()`
- [ ] T012 [P] [US2] Log sub-threshold fuzzy candidates (score < 90) at DEBUG level with candidate name and score in `src/graphdb/client.py` within `upsert_company()`

---

## Phase 6: User Story 3 — Score Isolation Verified (P2)

**Goal**: `lead_score`/`lead_score_breakdown` exist in SQLite and Neo4j but NEVER in dashboard HTML.

- [ ] T013 [US3] Grep `src/build_dashboard.py` and generated `dashboard.html` for `lead_score` — remove any matches, confirm `grep -c "lead_score" dashboard.html` returns 0

---

## Phase 7: User Story 4 — No Committed Credentials (P2)

**Goal**: No credential strings in tracked files. `.env` in `.gitignore`.

- [ ] T014 [P] [US4] Run `git grep -i "WEBSHARE_PROXY_URL\|RESIDENTIAL_PROXY\|NEO4J_URI\|NEO4J_PASSWORD\|NEO4J_USER"` across tracked files — confirm only `.env.example`, CI workflow files, and docs match; no real credentials
- [ ] T015 [US4] Confirm `.env` is listed in `.gitignore` via `grep -c "\.env" .gitignore`

---

## Phase 8: Polish — Cross-Cutting Validation

**Purpose**: Final sweep for all constitutional rules.

- [ ] T016 Run `git status` confirming `.scrapling_checkpoints/` and `debug_output/` are not tracked
- [ ] T017 Run `grep -rn "lead_score" dashboard.html 2>/dev/null` confirming zero matches
- [ ] T018 Run `pytest tests/` — all 352 existing tests pass

---

## Dependencies

- **T001** → blocks T008 (need neo4j importable before writing test script)
- **T001** → blocks T009 (need neo4j version known before pinning in CI)
- **T002 - T003** → blocks no user story (checkpointing is infrastructure)
- **T004 - T007** (Phase 3 US1) → independent of all other phases
- **T008** (Phase 4 US5) → depends on T001 (neo4j must be importable)
- **T009** (Phase 4 US5) → depends on T001, independent of T008-T007
- **T010 - T012** (Phase 5 US2) → independent of all other phases
- **T013** (Phase 6 US3) → independent of all other phases
- **T014 - T015** (Phase 7 US4) → independent of all other phases
- **T016 - T018** (Phase 8) → depends on all prior phases

## Parallel Execution

- T004 + T005 (same file, different blocks) — parallel
- T004/T005 + T007 (different files) — parallel
- T004/T005/T007 + T008 (log fixes + test script) — parallel per user's requirement
- T010/T011/T012 (same function, different match types) — parallel
- T013 + T014/T015 (score isolation + credential scan) — parallel
- All of Phase 3 (US1) + Phase 5 (US2) + Phase 6 (US3) + Phase 7 (US4) — fully parallel

## Implementation Strategy

### MVP (User Story 1 Only)

1. Phase 1: T001 — verify neo4j dep
2. Phase 3: T004-T007 — fix log levels, JD ASN stats, neo4j_failed flag
3. Validate: pipeline logs every target's disposition; Neo4j failures produce `"neo4j_failed": true`

### Full Delivery

1. Phase 1 + Phase 2 → foundation ready
2. Phase 3 (US1) → fail-loudly compliance
3. Phase 4 (US5) → idempotency proof + CI pinning
4. Phase 5 (US2) → entity-resolution audit trail
5. Phase 6 (US3) + Phase 7 (US4) → score isolation + credential verification
6. Phase 8 → final validation sweep

## User Story Test Criteria

| Story | Independent Test |
|-------|------------------|
| US1 | Pipeline with no proxies logs "Justdial skipped: ProxyNotConfigured", "IndiaMART skipped: ProxyNotConfigured", "TradeIndia: N records". Neo4j unreachable → `summary["neo4j_failed"] = True` |
| US2 | After entity-resolution run, `debug_output/fuzzy_matches.log` exists with timestamped entries containing both names, score, and threshold |
| US3 | `grep -c "lead_score" dashboard.html` returns 0; SQLite Leads table has `lead_score` and `lead_score_breakdown` columns |
| US4 | `git grep` for credential patterns across tracked files returns no real credentials; `.env` is gitignored |
| US5 | `scripts/test_neo4j_write.py` exits 0 with matching node counts before and after second MERGE; CI workflow has neo4j pin step |
