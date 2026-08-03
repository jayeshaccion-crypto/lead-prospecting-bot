<PROJECT_KNOWLEDGE_GRAPH version="1.1" last_updated="2026-07-30">

PROJECT: lead-prospecting-bot
DOMAIN SUMMARY: Automated lead prospecting pipeline that scrapes Indian business directories (Justdial, IndiaMART, TradeIndia) using Scrapling (StealthySession headless browser), enriches records inline (httpx for IndiaMART phones, entity extraction from HTML), deduplicates on normalized domain, and writes sales-ready rows to both SQLite (for dashboards) and Neo4j (for graph traversal/relationship queries). Two execution paths exist: standalone `run.py` (day-to-day scraping) and `src/pipeline.py` via the scheduler (staging/promotion flow with validation, scoring, and threshold checks).

ENTITIES:
- LeadRecord: A validated prospect company record. Fields: company_name, website, email, phone, address, industry_code, employee_count, revenue_band, source_url, scraped_at, dedup_key, lead_score. Validated via Pydantic. Source: src/models.py:18
- RawRecord: Unvalidated scraped record from a target site parser. Fields: company_name, website, email, phone, address, industry_code, source_url. Source: src/scraper/targets.py:22
- ScrapeError: A record of a scrape failure for a target URL. Fields: url, timestamp, error_type. Source: src/models.py:59
- RejectedDuplicate: A record of a duplicate rejected during dedup. Fields: dedup_key, kept_company, rejected_company, reason, timestamp. Source: src/models.py:67
- InvalidRecord: NamedTuple for a validation failure. Fields: record (LeadRecord), reason (str). Source: src/validation.py:10
- TargetSite: A configured business directory. Fields: name, entry_url, parser (registered parser function), pages, fetch_kwargs (timeout, max_detail_pages, page_delay, target_delay). Source: config/targets.yaml
- DatabaseClient: SQLite client mirroring SheetsClient interface. Manages Leads, staging, scrape_errors, rejected_duplicates. Source: src/database/client.py:18
- GraphCompany (Neo4j): Graph node representing a company. Fields: dedup_key (unique), company_name, normalized_name, phone, email, website, address, industry_code, first_seen, last_seen, sources (list), lead_score, lead_score_breakdown. Source: src/graphdb/client.py (Q3_MERGE_COMPANY, MERGE on dedup_key)
- GraphCategory (Neo4j): Graph node. Fields: name (unique). Source: src/graphdb/client.py (Q4_LISTED_IN)
- GraphCity (Neo4j): Graph node. Fields: name (unique). Source: src/graphdb/client.py (Q5_LOCATED_IN)
- GraphSource (Neo4j): Graph node. Fields: name (unique). Source: src/graphdb/client.py (Q6_SOURCED_FROM)

RELATIONSHIPS (SQLite / Python):
- TargetSite --[scraped_by (registered parser)]--> Parser (parse_justdial, parse_indiamart, parse_tradeindia)
- Parser --[produces]--> RawRecord
- RawRecord --[converted_by (raw_record_to_lead)]--> LeadRecord
- LeadRecord --[deduplicated_by]--> DedupLogic (dedup_key collision, richer record wins)
- LeadRecord --[validated_by]--> ValidationRules (company_name + email|phone required)
- LeadRecord --[scored_by]--> ScoringFormula (40*email + 20*phone + 20*size + 20*industry, cap 100)
- LeadRecord --[written_to]--> DatabaseClient (Leads / staging tabs)
- ScrapeError --[written_to]--> DatabaseClient (scrape_errors tab)
- RejectedDuplicate --[written_to]--> DatabaseClient (rejected_duplicates tab)
- RawRecord --[inlines_to]--> run.py (standalone path, no staging/promotion)
- LeadRecord --[graph_written_by (write_companies / _upsert_company_in_tx)]--> GraphCompany (Neo4j)

RELATIONSHIPS (Neo4j):
- (GraphCompany)-[:LISTED_IN]->(GraphCategory)
- (GraphCompany)-[:LOCATED_IN]->(GraphCity)
- (GraphCompany)-[:SOURCED_FROM {scraped_at, raw_record_id}]->(GraphSource)

SYSTEM ARCHITECTURE:
- Modules/Services:
  - run.py: Standalone pipeline entry (run directly via `python run.py`). Scrapes all targets, converts RawRecords, writes SQLite, writes Neo4j (write_companies + ensure_schema), builds dashboard. No staging/promotion/validation/scoring.
  - src/__main__.py: CLI entry point with --dry-run, --promote, --scheduler flags. Calls src/pipeline.py. Source: src/__main__.py:1
  - src/pipeline.py: Orchestrates scrape → enrich → dedup → validate → score → write staging → promote → write Neo4j (`_write_to_neo4j`). Raises PipelineThresholdError on >30% failure. Source: src/pipeline.py:314
  - src/scraper/engine.py: Iterates targets, checks robots.txt (fail-open), delegates to scrape_target(), aggregates results. Source: src/scraper/engine.py:14
  - src/scraper/targets.py: Site-specific parsers — Justdial (__NEXT_DATA__ + XHR + CSS), IndiaMART (__INITIAL_STATE__ + CSS + httpx phone enrichment), TradeIndia (CSS, contact info JS-only). RawRecord dataclass, detail page enrichment (browser disabled via max_detail_pages:0), pagination helpers, retry loop (3 attempts, 429→30s/60s waits, empty→5s, exception→10s). Source: src/scraper/targets.py:1
  - src/scraper/utils.py: Utilities — robots.txt caching (fail-open), domain normalization, email validation (RFC 5322-lite), retry decorator (exponential backoff). Source: src/scraper/utils.py
  - src/config.py: YAML targets config loading, TARGET_INDUSTRY_LIST (20 industries), DB_PATH env var. Source: src/config.py:1
  - src/models.py: Pydantic models (LeadRecord, ScrapeError, RejectedDuplicate), field validators, now_utc(). Source: src/models.py:1
  - src/validation.py: Validation rules + filter_valid_records(). Source: src/validation.py:1
  - src/scoring.py: Deterministic lead score computation (0-100). Source: src/scoring.py:1
  - src/scheduler.py: APScheduler loop — Monday 06:00 UTC or custom interval. Source: src/scheduler.py:22
  - src/database/client.py: SQLite DatabaseClient with CRUD + dedup_key collision prevention. Source: src/database/client.py:18
  - src/database/tabs.py: Tab definitions + ensure_all_tabs + write_staging. Source: src/database/tabs.py:1
  - src/graphdb/__init__.py: Neo4j driver singleton (get_driver()), configured via NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD env vars read at call time. Raises RuntimeError if NEO4J_PASSWORD unset. Source: src/graphdb/__init__.py:1
  - src/graphdb/schema.py: Neo4j constraints (4 unique property constraints) and indexes (2). Source: src/graphdb/schema.py:1
  - src/graphdb/client.py: High-level Cypher queries — write_companies()/upsert_company() (entity resolution), query_by_location(), query_company_detail(), get_company_count(), get_stats(). Source: src/graphdb/client.py:1
  - src/graphdb/migrate.py: Bulk SQLite → Neo4j migration with dedup_key merge strategy. Source: src/graphdb/migrate.py:1
  - build_dashboard.py: Generates HTML dashboard from SQLite Leads table. Source: build_dashboard.py
  - scripts/migrate_neo4j.py: CLI entry point for SQLite → Neo4j migration. Source: scripts/migrate_neo4j.py
- Data flow (run.py — standalone): run.py → scrape_all_targets() → raw_record_to_lead (inline dedup_key) → SQLite INSERT → Neo4j write_companies() (ensure_schema) → build_dashboard()
- Data flow (pipeline.py — scheduler/CLI): __main__.py → main_pipeline() → scrape_all_targets() → raw_record_to_lead() → deduplicate_records() → filter_valid_records() → score_all_records() → write_staging() → [!dry_run] check_failure_threshold() → promote_to_production() → write Neo4j (_write_to_neo4j).
- External dependencies/APIs:
  - Scrapling (>=0.4): StealthySession headless browser with Cloudflare solving, capture_xhr, network_idle
  - httpx (stdlib-compatible): Plain-HTTP enrichment for IndiaMART phone extraction (detail pages)
  - neo4j (5.20.0): Python driver for Neo4j graph database (installed 5.20.0)
  - SQLite: Local storage (data/leads.db), Cloudflare D1 compatible dialect
  - APScheduler (>=3.10): Scheduling (src/scheduler.py / __main__.py path only)
- Storage:
  - SQLite with 4 tables (Leads, staging, scrape_errors, rejected_duplicates), 12-column fixed schema
  - Neo4j with 4 node labels (Company, Category, City, Source), 3 relationship types (LISTED_IN, LOCATED_IN, SOURCED_FROM), 4 constraints, 2 indexes

CONTRACTS/SPECS:
- LeadRecord schema: 12 fields, Pydantic model. company_name required non-empty, website/source_url validated as URLs, lead_score validated 0-100. Source: src/models.py:18, specs/001-lead-prospecting-pipeline/data-model.md
- RawRecord dataclass: 7 fields. Source: src/scraper/targets.py:22
- Parser interface: registered parser function (response, source_url) -> list[RawRecord]. 3 registered: parse_justdial, parse_indiamart, parse_tradeindia. Retry in scrape_target(): 3 attempts, 429→30s/60s waits, empty 200→5s wait, exception→10s wait. Source: src/scraper/targets.py:475
- StealthySession kwargs: headless=True, solve_cloudflare=True, load_dom=True, network_idle=True, capture_xhr=.*. Source: src/scraper/targets.py:488
- IndiaMART httpx enrichment: Called automatically after browser scrape. Fetches listing page via StealthySession, extracts detail URLs, fetches each via httpx, extracts Indian mobile phones via regex (?:\+?91[-\s]?)?[6-9]\d{9}. Non-destructive (only sets phone if missing). Source: src/scraper/targets.py:388
- Detail page enrichment (browser): max_detail_pages=0 for all 3 sites (disabled). Source: config/targets.yaml
- DatabaseClient interface: ensure_tab(), clear_tab(), append_rows(), get_all_rows(), read_existing_dedup_keys(), append_if_not_duplicate(). Source: src/database/client.py:18
- SQLite schema: Leads (12 cols), staging (12 cols), scrape_errors (3 cols), rejected_duplicates (5 cols). Staging cleared each run; production via append_if_not_duplicate. Source: src/database/tabs.py, src/database/client.py:116
- Lead scoring formula: 40*has_email + 20*has_phone + 20*(10<=emp_count<=500) + 20*(industry in target_list), max 100. Deterministic. Source: src/scoring.py:5
- Validation rules: company_name required non-empty, at least one of email/phone non-empty, invalid email -> "UNVERIFIED:" prefix. Source: src/validation.py:21
- Pipeline orchestration: main_pipeline(dry_run=False). Raises PipelineThresholdError if >30% targets fail on non-dry-run. Source: src/pipeline.py:314
- Promotion: promote_to_production() reads staging, checks failure threshold, copies to Leads with dedup_key collision check. Source: src/pipeline.py:201
- Scheduling: APScheduler cron "mon 06:00 UTC" or custom interval. Source: src/scheduler.py:22
- CLI interface: --dry-run (staging only), --promote (manual promotion), --scheduler (start scheduler loop), --interval-days (default 7). --dry-run and --promote mutually exclusive. Source: src/__main__.py:5
- Neo4j driver: get_driver() returns bolt://localhost:7687 default (NEO4J_URI), user NEO4J_USER default neo4j, password NEO4J_PASSWORD (no default — RuntimeError if unset). Credentials read at call time, not import time. Source: src/graphdb/__init__.py:17
- Neo4j upsert: write_companies() runs entity resolution per record (phone last-10-digits primary key, else fuzzy token_sort_ratio >= 90 on legal-suffix-only normalization) and MERGEs Company nodes (dedup_key) + Category/City/Source nodes and LISTED_IN/LOCATED_IN/SOURCED_FROM edges. company_name/normalized_name/first_seen set only ON CREATE; last_seen/lead_score updated on match; sources appended if absent. Every fuzzy comparison written to debug_output/fuzzy_matches.log. All writes in one transaction per record. Source: src/graphdb/client.py
- Neo4j schema: 4 unique constraints (Company.dedup_key, Category.name, City.name, Source.name). 2 indexes (Company.company_name, Company.normalized_name). Source: src/graphdb/schema.py:10
- Neo4j queries: query_by_location(city), query_company_detail(company_name partial match), get_stats() with per-label counts (Company/Category/City/Source + relationship counts). Source: src/graphdb/client.py
- Dashboard build: build_dashboard.py reads SQLite db, generates HTML. Source: build_dashboard.py:1

BUSINESS RULES / CONSTRAINTS:
- BR-001: Pipeline MUST scrape using Scrapling StealthySession with headless=True, solve_cloudflare=True, load_dom=True, network_idle=True
- BR-002: Enrichment is inline — IndiaMART phones via httpx (plain HTTP), other data from listing page HTML. No external enrichment API provider in active use.
- BR-003: Dedup key = normalized domain (lowercased, stripped of www. and trailing slash). Source: run.py:48, src/pipeline.py:290
- BR-004: On dedup_key collision, keep row with more populated enrichment fields (employee_count, revenue_band); tie-break alphabetically. Source: src/pipeline.py:70
- BR-005: Never merge two partial rows — discarded rows logged to rejected_duplicates with reason. Source: src/pipeline.py:76
- BR-006: Lead score is deterministic formula only — email(+40), phone(+20), size 10-500(+20), industry match in TARGET_INDUSTRY_LIST(+20), capped 100. Source: src/scoring.py:5
- BR-007: Failed fetches retry 3x per page. 429 → 30s/60s wait. Empty 200 → 5s wait. Exception → 10s wait. Source: src/scraper/targets.py:507
- BR-008: One target failure must NOT abort the entire run — per-target try/except in scrape_all_targets(). Source: src/scraper/engine.py:48
- BR-009: >30% target failure rate → abort promotion, raise PipelineThresholdError (pipeline.py path only; run.py ignores errors beyond logging). Source: src/pipeline.py:188
- BR-010: Credentials via environment variables ONLY — never committed. Source: README
- BR-011: Pipeline MUST abort at startup if required env vars missing (pipeline.py path only). Source: src/pipeline.py
- BR-012: Invalid email format → prefix with "UNVERIFIED:", never silently drop or trust. Source: src/validation.py:68
- BR-013: Empty company_name OR (both email and phone empty) → reject row, log reason. Source: src/validation.py:36
- BR-014: Staging tab cleared before each write; production append-only via dedup_key check. Source: src/database/tabs.py:39, src/database/client.py:116
- BR-015: All records without a dedup_key pass through dedup as-is (never dropped). Source: src/pipeline.py:56
- BR-016: India-only scope — all target sites are Indian business directories. Source: config/targets.yaml
- BR-017: Site-wide contact values MUST be rejected during enrichment — KNOWN_SITE_WIDE_PHONES = {"01146710423"}, KNOWN_SITE_WIDE_EMAILS = {"helpdesk@tradeindia.com"}. Source: src/scraper/targets.py:42
- BR-018: Directory/social domains MUST NOT be assigned as company website — DIRECTORY_DOMAINS filters facebook.com, twitter.com, linkedin.com, youtube.com, justdial.com, indiamart.com, tradeindia.com, google.com, whatsapp.com, googletagmanager.com, schema.org. Source: src/scraper/targets.py:34
- BR-019: Browser detail page enrichment is disabled (max_detail_pages=0) — body retrieval always fails with Protocol error in this network environment. IndiaMART uses httpx fallback instead. Source: config/targets.yaml
- BR-020: Neo4j write is non-fatal — failure logs warning but pipeline continues. Source: run.py:92
- BR-021: Neo4j write is idempotent — MERGE on dedup_key; first_seen/company_name/normalized_name set only ON CREATE; verified delta-0 across identical re-runs (see specs/007-neo4j-entity-resolution/quickstart.md). Source: src/graphdb/client.py
- BR-022: run.py truncates all tables (DELETE FROM) before each write. Source: run.py:65
- BR-023: Two pipeline paths exist (run.py standalone vs src/pipeline.py via scheduler). They diverge in enrichment, validation, scoring, and staging/promotion. Both write to Neo4j. This is a known architectural debt.
- BR-024: Destructive Neo4j cleanup (MATCH (n) DETACH DELETE n) requires explicit opt-in env var NEO4J_RESET_ALLOWED=1. Source: tests/test_graphdb_idempotency.py, scripts/demo_idempotency.py

NON-GOALS / OUT OF SCOPE (project-wide):
- No LinkedIn scraping — LinkedIn data enters only via manual CSV import into linkedin_manual tab
- No email verification (SMTP ping/deliverability) — deferred to v2
- No CRM synchronization (Salesforce/HubSpot) — deferred to v2
- No AI-based lead scoring — scoring is pure deterministic formula
- No multi-currency support
- No backorders support
- No external enrichment API in active use (contract exists in specs but is stale)
- No parallel scraping — sequential per-target, wall-clock scales linearly

GLOSSARY:
- "lead" = A prospect company record ready for sales outreach
- "dedup_key" = Normalized domain (lowercased, www.-stripped, trailing-slash-stripped) used as primary dedup identifier
- "dedup" = Deduplication process that keeps the record with more enrichment fields on collision
- "staging" = Intermediate database tab written every pipeline run, cleared before each write
- "promotion" = Copying staging rows to the Leads production tab after threshold check
- "dry_run" = Pipeline mode (pipeline.py) that writes only to staging, skips promotion and threshold alerts
- "target" = A configured business directory URL with an associated parser function
- "industry_code" = Industry classification string from scraped data (not normalized)
- "revenue_band" = Revenue range string from scraped data
- "lead_score" = Integer 0-100 computed via deterministic formula (email + phone + size + industry)
- "normalized_domain" = Website URL lowercased, www. stripped, trailing slash stripped
- "enrichment" = Post-scrape data extraction from detail pages or via httpx (IndiaMART phones)
- "site-wide value" = Contact info that appears on every page of a directory (e.g., helpdesk@tradeindia.com) — not company-specific, must be rejected
- "StealthySession" = Scrapling fetcher providing a real headless browser with anti-bot evasion
- "httpx enrichment" = Plain-HTTP fetch of IndiaMART detail pages to extract phones (bypasses browser body retrieval failure)

KNOWN GAPS / UNVERIFIED AREAS:
- Two divergent pipeline paths (run.py vs src/pipeline.py) — both write to Neo4j, but they differ in enrichment, validation, scoring, and staging behavior. No single code path does everything.
- External enrichment API contract (specs/001-lead-prospecting-pipeline/contracts/enrichment-api.md) is stale — not in active use by run.py. The pipeline.py path references it but the enrichment/client.py module may not exist.
- Neo4j write is not fully aligned with SQLite lifecycle — run.py DELETE FROM Leads then re-inserts, but Neo4j MERGE on dedup_key means records removed from SQLite survive in Neo4j (idempotent but not a delete-sync).
- No monitoring/alerting for any pipeline path — threshold breach only logs to console.
- LinkedIn manual import tab exists in schema but no ingestion code.
- Source site HTML structure changes not proactively monitored (each parser is isolated).
- No parallel/multi-threaded scraping — wall-clock time scales linearly with page count.
- IndiaMART 429 rate limiting on this IP — httpx enrichment may fail consistently with high retry latency.
- TradeIndia contact info is entirely JS API-driven — only names available from CSS parser.
- robots.txt check is fail-open (returns True if unreachable) — potential scraping policy gap.
- Neo4j is installed at C:\neo4j\neo4j-community-2026.06.0, running with Java 23 (unsupported); may fail to restart after reboot.

GOVERNANCE:
- Owner: Platform Team
- Coverage: ~90%
- Confidence: 85%
- Review Date: 2026-09-01
- Deprecated Nodes: External Enrichment API contract (stale, not in active use)
- Pending Changes:
  - SIMILAR_TO relationship population logic
  - Delete-sync from SQLite to Neo4j (removed records currently survive in Neo4j)

</PROJECT_KNOWLEDGE_GRAPH>
