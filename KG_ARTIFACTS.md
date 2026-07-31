# Knowledge Graph Artifacts — Lead Prospecting Bot

Part of the deterministic AI-Native KG-Driven Engineering workflow (see `AINative-KGDriven.md`).

---

## 1. ASSUMPTION REGISTER

Persistent across the project. Read from, not re-derived, on every task.

| ID | Description | Reason | Confidence | Affected Components | Status |
|---|---|---|---|---|---|
| A-001 | Target sites are publicly accessible, no auth required | Industry directories are public | 100% | scraper/engine.py, scraper/targets.py | Confirmed |
| A-002 | Enrichment API returns data for majority of Indian companies | Market research assumption | 75% | pipeline.py (enrichment step) | Pending |
| A-003 | Pipeline runs on system with network access to all targets + APIs | Deployment environment | 100% | All | Confirmed |
| A-004 | India-only scope — no non-Indian directories | Spec constraint | 100% | config/targets.yaml | Confirmed |
| A-005 | LinkedIn data out of scope for v1 | Spec decision | 100% | N/A | Confirmed |
| A-006 | Email verification (SMTP) out of scope for v1 | Spec decision | 100% | validation.py | Confirmed |
| A-007 | CRM sync out of scope for v1 | Spec decision | 100% | N/A | Confirmed |
| A-008 | Enrichment API failures degrade gracefully (nulls, not crash) | Design decision | 100% | pipeline.py | Confirmed |
| A-009 | SQLite is sufficient for v1 scale (not replacing Google Sheets as primary) | Migration decision | 90% | database/client.py | Confirmed |
| A-010 | Dedup key collision resolution (richer record wins) matches business expectation | Assumption | 90% | pipeline.py (deduplicate_records) | Confirmed |

Status: Confirmed / Rejected / Pending

---

## 2. TRACEABILITY MATRIX

One row per requirement touched. Populated per change.

| Requirement | Source | Design Decision | Files | Tests | Verification |
|---|---|---|---|---|---|
| FR-001: Scrape with Scrapling, robots.txt obey | spec.md §Integrations | StealthySession with robots_txt_obey=True | src/scraper/engine.py, src/scraper/utils.py | test_engine.py | Manual + CI |
| FR-002: Extract core fields | spec.md §Data Model | RawRecord dataclass + site parsers | src/scraper/targets.py | test_engine.py | Run output |
| FR-003: Enrich via API | spec.md §Integrations | Enrichment per unique domain in pipeline | src/pipeline.py | (integration) | Run output |
| FR-004: Dedup by normalized domain | spec.md §Dedup Rule | dedup_key = lowercased domain, strip www./trailing slash | src/pipeline.py:279-311, src/database/client.py:109-131 | test_dedup.py | Passes |
| FR-005: Keep richer on collision | spec.md §Dedup Rule | Compare enrichment field count, tie-break alphabetically | src/pipeline.py:33-94 | test_dedup.py | Passes |
| FR-006: Deterministic lead score | spec.md §Score Formula | 40*email + 20*phone + 20*size + 20*industry, capped 100 | src/scoring.py | test_scoring.py | Passes |
| FR-007: Fixed 12-column schema | spec.md §Data Model | LeadRecord model + record_to_row() | src/models.py, src/pipeline.py:97-121 | test_dedup.py | Passes |
| FR-008: Staging then promotion | spec.md §Deploy | write_staging + promote_to_production | src/pipeline.py:201-245, src/database/tabs.py | test_pipeline.py | Passes |
| FR-009: Weekly schedule, idempotent | spec.md §Scheduling | APScheduler cron + dedup_key check on append | src/scheduler.py, src/database/client.py:116-131 | test_scheduler.py | Passes |
| FR-010: Reject empty company_name | spec.md §Validation | validate_record() check | src/validation.py:21-43 | test_validation.py | Passes |
| FR-011: UNVERIFIED: prefix for bad email | spec.md §Validation | is_valid_email() + flag_invalid_email() | src/validation.py:46-81, src/scraper/utils.py:55-84 | test_validation.py | Passes |
| FR-012: Per-target try/except | spec.md §Error Handling | Individual try/except in scrape_all_targets | src/scraper/engine.py:27-41 | test_engine.py | Passes |
| FR-013: 3x retry with backoff | spec.md §Error Handling | retry() decorator (1s, 4s, 16s) | src/scraper/utils.py:87-115 | (integration) | Passes |
| FR-014: >30% failure abort | spec.md §Error Handling | check_failure_threshold() | src/pipeline.py:169-198 | test_pipeline.py | Passes |
| FR-015: Env-only credentials | spec.md §Credentials | .env.example, load_dotenv at startup | src/__main__.py, run.py | N/A | Manual |
| FR-016: Abort if env vars missing | spec.md §Credentials | Env check at startup before network calls | src/__main__.py | N/A | Manual |
| SC-001: Run under 30min for 10 targets | spec.md §Success Criteria | Perf not measured — acceptance criterion | All | N/A | Benchmark |
| SC-002: Idempotent sheet output | spec.md §Success Criteria | dedup_key prevents duplicates | src/database/client.py:116-131 | test_dedup.py | Passes |
| SC-003: Single failure doesn't block others | spec.md §Success Criteria | Per-target try/except | src/scraper/engine.py | test_engine.py | Passes |
| SC-004: Zero credentials in logs/code | spec.md §Success Criteria | Env-only pattern, no hardcoded keys | All | N/A | Audit |
| SC-005: Malformed rows rejected with trace | spec.md §Success Criteria | InvalidRecord with reason | src/validation.py | test_validation.py | Passes |

---

## 3. RISK MATRIX

Fill for any non-trivial change.

| Dimension | Assessment |
|---|---|
| Breaking Change | All public interfaces (LeadRecord, DatabaseClient methods) are internal — no external consumers. Schema changes require coordinated migration of database/client.py + tabs.py. |
| Security | Credentials via env vars only. No secrets in code/logs. Enrichment API key sent as Bearer token over HTTPS. SQLite has no auth (local file). |
| Performance | Single-threaded sequential pipeline. Scraping is I/O-bound (network). 3 targets x 1-3 pages ~ few minutes. Detail page enrichment is the bottleneck (sequential per-target). |
| Scalability | Vertical only for v1. Adding more targets increases wall-clock time linearly. No parallel scraping across targets. SQLite handles thousands of rows easily. |
| Compatibility | Python >=3.12, Scrapling >=0.4, APScheduler >=3.10. SQLite is stdlib. D1-compatible SQL for future Cloudflare migration. |
| Migration | From Google Sheets → SQLite complete. Future migration to Cloudflare D1 requires SQL review (already D1-compatible). |
| Rollback Plan | Staging tab cleared each run — no rollback needed. Production append-only — can delete rows manually. git revert for code. |
| Monitoring / Alerting | Logging only (Python logger). No webhook/email alert for >30% threshold breach. Manual log review required. |
