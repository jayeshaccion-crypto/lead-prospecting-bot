---

description: "Task list for the Lead Prospecting Pipeline feature"

---

# Tasks: Lead Prospecting Pipeline

**Input**: Design documents from `specs/001-lead-prospecting-pipeline/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Test tasks are included where specified in the feature specification.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- Paths shown below assume single project structure per plan.md

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create project directory structure per plan.md (src/, tests/, tests/fixtures/, config/)
- [X] T002 [P] Create `pyproject.toml` with project metadata and core dependencies (scrapling, google-api-python-client, google-auth, pydantic, httpx, python-dotenv)
- [X] T003 [P] Create `src/__init__.py` and `src/__main__.py` entry point with argparse for --dry-run and --scheduler flags
- [X] T004 [P] Create `config/targets.yml` template with example target site configuration format
- [X] T005 [P] Create `tests/__init__.py` and `tests/conftest.py` with shared fixtures (mock HTML, mock enrichment response, mock sheets service)
- [X] T006 [P] Create `.env.example` documenting required env vars (GOOGLE_SA_KEY, ENRICH_API_KEY, SHEET_ID, TARGETS_CONFIG)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T007 [P] Implement config loading in `src/config.py`: env var reading, YAML target config parser, target_industry_list constant
- [X] T008 [P] Implement pydantic models in `src/models.py`: LeadRecord, ScrapeError, RejectedDuplicate with all fields and validation rules from data-model.md
- [X] T009 Implement domain normalization utility in `src/scraper/utils.py`: normalize_domain() lowercases, strips www. prefix, strips trailing slash
- [X] T010 [P] Implement Google Sheets client in `src/sheets/client.py`: SheetsClient class with service account auth from decoded GOOGLE_SA_KEY, methods for read_existing_dedup_keys, append_rows, ensure_tab
- [X] T011 Implement sheet tab management in `src/sheets/tabs.py`: tab_exists, ensure_tab for creating leads/staging/scrape_errors/rejected_duplicates tabs with proper headers from contracts/google-sheet-schema.md
- [X] T012 Implement email validation utility in `src/scraper/utils.py`: is_valid_email() using RFC 5322-lite pattern, flag_invalid_email() that prefixes with `UNVERIFIED:` when invalid
- [X] T013 [P] Implement retry decorator in `src/scraper/utils.py`: retry with exponential backoff (1s, 4s, 16s), max 3 attempts

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Automated Weekly Lead Collection (Priority: P1) 🎯 MVP

**Goal**: Scrape public business directories and company websites using Scrapling, extracting all core fields from each target site.

**Independent Test**: Run pipeline against 1-2 test target URLs and verify rows appear in staging tab with populated company_name, website, email, phone, address, industry_code.

- [X] T014 Implement Scrapling fetcher factory in `src/scraper/engine.py`: create_fetcher() returning StealthyFetcher with adaptive=True, robots_txt_obey=True
- [X] T015 [P] [US1] Implement per-target scrape function in `src/scraper/targets.py`: scrape_target() that fetches URL via StealthyFetcher, applies site-specific parser, returns list of RawRecord
- [X] T016 [US1] Implement target site parser example in `src/scraper/targets.py`: Site-specific parser function extracting company_name, website, email, phone, address, industry_code from HTML using Scrapling CSS selectors
- [X] T017 [US1] Implement scrape orchestration in `src/scraper/engine.py`: scrape_all_targets() that iterates over configured targets, wraps each in try/except, applies retry on fetch failures, aggregates results
- [X] T018 [US1] Implement Scrapling fetch wrapper in `src/scraper/engine.py`: fetch_with_retry() calling StealthyFetcher.fetch with configured timeout and retry logic from T013
- [X] T019 [US1] Implement error logging for scrape failures in `src/scraper/engine.py`: logs failed targets to ScrapeError model with url, timestamp, error_type

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently — raw records can be scraped from target sites.

---

## Phase 4: User Story 2 - Enrichment & Scoring (Priority: P1)

**Goal**: Enrich each scraped record with employee_count and revenue_band from the fixed enrichment API, then compute lead_score deterministically.

**Independent Test**: Run pipeline and verify employee_count and revenue_band columns are populated for records where API returned data, and lead_score is 0-100 per formula.

- [X] T020 [P] [US2] Implement enrichment API client in `src/enrichment/client.py`: EnrichmentClient with configurable base URL and API key header, get_enrichment(domain) method returning employee_count and revenue_band
- [X] T021 [P] [US2] Implement lead scoring in `src/scoring.py`: compute_lead_score() with deterministic formula from data-model.md, configurable target_industry_list
- [X] T022 [US2] Implement enrichment orchestration in `src/enrichment/client.py`: enrich_records() that calls API per unique domain, handles non-200 and timeout gracefully (leaves enrichment fields null)
- [X] T023 [US2] Implement enrichment integration test in `tests/test_enrichment.py`: mock API response and verify enrichment fields are populated correctly on LeadRecord

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently — records can be scraped, enriched, and scored.

---

## Phase 5: User Story 3 - Idempotent Deduplication (Priority: P1)

**Goal**: Deduplicate records by normalized_domain, resolving collisions by enrichment field completeness, and logging rejections to the rejected_duplicates tab.

**Independent Test**: Insert two records with same dedup_key but different enrichment levels; verify the richer record is kept and the other is logged to rejected_duplicates.

- [X] T024 [P] [US3] Implement deduplication logic in `src/pipeline.py`: deduplicate_records() that groups by dedup_key, compares enrichment field count, keeps the richer, returns (kept_records, rejected_records)
- [X] T025 [US3] Implement idempotent sheet append in `src/sheets/client.py`: append_if_not_duplicate() that reads existing dedup_keys from sheet before appending, skips already-seen keys
- [X] T026 [US3] Implement rejected_duplicates logging in `src/pipeline.py`: writes RejectedDuplicate rows to rejected_duplicates sheet tab with dedup_key, kept_company, rejected_company, reason, timestamp
- [X] T027 [US3] Implement dedup integration test in `tests/test_dedup.py`: mock two records with same domain, verify one kept, one rejected, sheet dedup_key check prevents double-write

**Checkpoint**: All P1 user stories should now be independently functional.

---

## Phase 6: User Story 4 - Dry-Run & Human Review (Priority: P2)

**Goal**: Implement two-phase promotion: dry-run writes to staging tab, production promotion requires manual approval after passing quality checks.

**Independent Test**: Run with --dry-run flag, verify output appears only in staging tab. Verify that promotion copies staging rows to production tab.

- [X] T028 [US4] Implement pipeline orchestration in `src/pipeline.py`: main_pipeline() that orchestrates scrape → enrich → dedup → score → validate → write_to_staging
- [X] T029 [US4] Implement dry-run mode in `src/pipeline.py`: skip production tab write when --dry-run is set, write only to staging tab
- [X] T030 [US4] Implement failure threshold check in `src/pipeline.py`: check_failure_threshold() that aborts promotion if >30% of targets failed
- [X] T031 [US4] Implement promotion logic in `src/pipeline.py`: promote_to_production() that copies staging rows to production tab after human approval signal
- [X] T032 [US4] Implement staging write in `src/sheets/tabs.py`: write_staging() that clears and rewrites staging tab with current batch rows
- [X] T033 [US4] Implement promotion command entry point in `src/__main__.py`: --promote flag that copies staging to production with threshold check

**Checkpoint**: User Story 4 complete — dry-run and promotion workflow works end-to-end.

---

## Phase 7: User Story 5 - Malformed Data Handling (Priority: P2)

**Goal**: Validate every row before writing: reject rows with empty company_name or missing both email and phone, prefix invalid emails with UNVERIFIED:, never silently drop.

**Independent Test**: Feed deliberately malformed records (empty company_name, missing email+phone, bad email format) and verify each is handled correctly.

- [X] T034 [US5] Implement row validation in `src/validation.py`: validate_record() checking company_name non-empty, at least one of email/phone present, email format compliance
- [X] T035 [US5] Implement validation integration in `src/pipeline.py`: filter_valid_records() that applies validation to all scraped+enriched records, separates valid from rejected
- [X] T036 [US5] Implement rejected row logging in `src/pipeline.py`: writes rejected records with reason to console log (logging.warning) for operational visibility
- [X] T037 [US5] Implement validation tests in `tests/test_validation.py`: test empty company_name rejection, missing email+phone rejection, invalid email prefix, valid record pass

**Checkpoint**: All user stories should now be independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [X] T038 [P] Implement scheduler entry in `src/scheduler.py`: APScheduler wrapper that runs pipeline on configurable interval, plus cron-compatible main entry
- [X] T039 Implement `src/pipeline.py` run_summary(): generate structured summary of rows scraped, enriched, rejected, errors per target
- [X] T040 [P] Write console logging throughout pipeline: structured logging per phase with row counts and timing
- [X] T041 [P] Implement startup credential check in `src/config.py`: verify GOOGLE_SA_KEY and ENRICH_API_KEY are present and non-empty at import time, exit with clear error message
- [X] T042 Implement end-to-end integration test in `tests/test_pipeline.py`: mock all external services, run full pipeline, verify staging tab content and scrape_errors tab
- [X] T043 [P] Add docstrings to all public functions across src/ modules
- [X] T044 Create top-level `run.py` convenience script: loads .env, calls python -m src with passed args

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-7)**: All depend on Foundational phase completion
  - US1, US2 can proceed in parallel (they depend on different sub-modules)
  - US3 depends on US1 (scraping) and US2 (enrichment) for data to deduplicate
  - US4 depends on US1, US2, US3 (full data pipeline before staging/promotion)
  - US5 can be done in parallel with US3, US4 (validation is isolated logic)
- **Polish (Phase 8)**: Depends on all user stories being complete

### Execution Order (Recommended)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: US1 (scrape) + Phase 4: US2 (enrich/score) — parallel or sequential
4. Phase 5: US3 (dedup) — depends on US1 + US2
5. Phase 6: US4 (staging/promotion) — depends on US1 + US2 + US3
6. Phase 7: US5 (validation) — can overlap with US3/US4
7. Phase 8: Polish

### Parallel Opportunities

- T002, T003, T004, T005, T006 can run in parallel (Setup phase)
- T007, T008, T010 can run in parallel (Foundational phase)
- T020, T021 can run in parallel (US2 enrichment + scoring)
- US1 and US2 scrapers can be implemented in parallel
- US5 validation is independent and can overlap with US3/US4

---

## Implementation Strategy

### MVP First (US1 + US2 + US3 — All P1 Stories)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1 (scraping)
4. Complete Phase 4: US2 (enrichment + scoring)
5. Complete Phase 5: US3 (deduplication)
6. **MVP READY**: Pipeline scrapes, enriches, scores, and deduplicates — can write to staging
7. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 (scraping) → Test independently → raw data collection works
3. Add US2 (enrich/score) → Test independently → leads enriched and scored
4. Add US3 (dedup) → Test independently → no duplicates, collision resolution works
5. Add US4 (staging/promotion) → dry-run + promotion workflow
6. Add US5 (validation) → malformed data handling
7. Polish → scheduler, logging, docs
