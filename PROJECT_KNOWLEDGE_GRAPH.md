<PROJECT_KNOWLEDGE_GRAPH version="1.0" last_updated="2026-07-29">

PROJECT: lead-prospecting-bot
DOMAIN SUMMARY: Automated lead prospecting pipeline that scrapes Indian business directories (Justdial, IndiaMART, TradeIndia) using Scrapling, enriches records via a single fixed enrichment API, deduplicates on normalized domain, scores leads deterministically, and writes sales-ready rows to an SQLite database on a weekly schedule.

ENTITIES:
- LeadRecord: A single prospect company. Fields: company_name, website, email, phone, address, industry_code, employee_count, revenue_band, source_url, scraped_at, dedup_key, lead_score. Validated via Pydantic. Source: src/models.py:18
- RawRecord: Unvalidated scraped record from a target site parser. Fields: company_name, website, email, phone, address, industry_code, source_url. Source: src/scraper/targets.py:19
- ScrapeError: A record of a scrape failure. Fields: url, timestamp, error_type. Source: src/models.py:59
- RejectedDuplicate: A record of a duplicate rejected during dedup. Fields: dedup_key, kept_company, rejected_company, reason, timestamp. Source: src/models.py:67
- InvalidRecord: NamedTuple for a validation failure. Fields: record (LeadRecord), reason (str). Source: src/validation.py:10
- TargetSite: A configured business directory. Fields: name, entry_url, parser (registered parser function), pages, fetch_kwargs. Source: config/targets.yml
- DatabaseClient: SQLite client that mirrors SheetsClient interface. Manages Leads, staging, scrape_errors, rejected_duplicates tables. Source: src/database/client.py:18

RELATIONSHIPS:
- TargetSite --[scraped_by]--> Parser (parse_justdial, parse_indiamart, parse_tradeindia)
- Parser --[produces]--> RawRecord
- RawRecord --[converted_by(raw_record_to_lead)]--> LeadRecord
- LeadRecord --[enriched_by]--> EnrichmentAPI (external)
- LeadRecord --[validated_by]--> ValidationRules
- LeadRecord --[deduplicated_by]--> DedupLogic (dedup_key collision)
- LeadRecord --[scored_by]--> ScoringFormula
- LeadRecord --[written_to]--> DatabaseClient (Leads / staging tabs)
- ScrapeError --[written_to]--> DatabaseClient (scrape_errors tab)
- RejectedDuplicate --[written_to]--> DatabaseClient (rejected_duplicates tab)

SYSTEM ARCHITECTURE:
- Modules/Services:
  - src/__main__.py: CLI entry point with --dry-run, --promote, --scheduler flags
  - src/pipeline.py: Orchestrates the full pipeline: scrape -> enrich -> dedup -> validate -> score -> write staging -> promote
  - src/scraper/engine.py: Iterates targets, checks robots.txt, delegates to site parsers, aggregates results
  - src/scraper/targets.py: Site-specific parsers for Justdial (__NEXT_DATA__ + CSS), IndiaMART (__INITIAL_STATE__ + CSS), TradeIndia (CSS), plus RawRecord dataclass and pagination helpers
  - src/scraper/utils.py: Utilities: robots.txt caching, domain normalization, email validation (RFC 5322-lite), retry decorator with exponential backoff
  - src/config.py: YAML-based targets config loading, TARGET_INDUSTRY_LIST (20 industries), DB_PATH from env
  - src/models.py: Pydantic models (LeadRecord, ScrapeError, RejectedDuplicate), validators, now_utc()
  - src/validation.py: Validation rules (company_name non-empty, email/phone required), email UNVERIFIED: prefixing via filter_valid_records
  - src/scoring.py: Deterministic lead score computation (0-100): email(+40), phone(+20), size fit(+20), industry match(+20)
  - src/scheduler.py: APScheduler loop — cron Monday 06:00 UTC or configurable interval
  - src/database/client.py: SQLite DatabaseClient with table init, CRUD, dedup_key-based dedup checks
  - src/database/tabs.py: Tab definitions (LEADS_HEADERS, STAGING_HEADERS, etc.), ensure_all_tabs, write_staging
- Data flow: CLI args -> main_pipeline() -> scrape_all_targets() -> raw_record_to_lead() -> deduplicate_records() -> filter_valid_records() -> score_all_records() -> write_staging() -> [if !dry_run] check_failure_threshold() -> promote_to_production()
- External dependencies/APIs:
  - Scrapling (>=0.4): StealthySession for headless browser scraping with Cloudflare solving
  - Enrichment API: External provider, configurable via env vars, called per-unique-domain after scrape
  - SQLite: Local storage (data/leads.db), Cloudflare D1 compatible
  - APScheduler (>=3.10): Scheduling
- Storage: SQLite with 4 tables (Leads, staging, scrape_errors, rejected_duplicates), 12-column fixed schema

CONTRACTS/SPECS:
- LeadRecord schema: 12 fields, Pydantic model. company_name required non-empty, website/source_url validated as URLs, lead_score validated 0-100. Source: src/models.py:18, specs/001-lead-prospecting-pipeline/data-model.md
- Scraper interface: RawRecord dataclass + registered parser function (response, source_url) -> list[RawRecord]. Retry: 3 attempts, exponential backoff (1s, 4s, 16s). Source: specs/001-lead-prospecting-pipeline/contracts/scraper-interface.md
- Enrichment API: GET /enrich?domain={normalized_domain}, Authorization: Bearer <ENRICH_API_KEY>. Response: {domain, company_name, employee_count, revenue_band}. Non-200/timeout -> log + continue with nulls. No retry. Source: specs/001-lead-prospecting-pipeline/contracts/enrichment-api.md
- Database schema: 4 tables with fixed column definitions. Leads/staging: 12 columns matching LeadRecord. scrape_errors: 3 columns. rejected_duplicates: 5 columns. Source: src/database/client.py:25, specs/001-lead-prospecting-pipeline/contracts/google-sheet-schema.md
- DatabaseClient interface: ensure_tab(), clear_tab(), append_rows(), get_all_rows(), read_existing_dedup_keys(), append_if_not_duplicate(). Source: src/database/client.py:18
- Lead scoring formula: 40*has_email + 20*has_phone + 20*(10<=emp_count<=500) + 20*(industry in target_list), max 100. Deterministic. Source: src/scoring.py:5
- Validation rules: company_name required, at least one of email/phone required, invalid email prefixed with "UNVERIFIED:". Source: src/validation.py:21, specs/001-lead-prospecting-pipeline/data-model.md:22
- Pipeline orchestration: main_pipeline(dry_run=False). Raises PipelineThresholdError if >30% targets fail on non-dry-run. Source: src/pipeline.py:314
- Promotion: promote_to_production() copies staging -> Leads with dedup_key collision check. Source: src/pipeline.py:201
- Scheduling: APScheduler cron "mon 06:00 UTC" or custom interval. Source: src/scheduler.py:22
- CLI interface: --dry-run (staging only), --promote (manual promotion), --scheduler (start scheduler loop), --interval-days (default 7). Source: src/__main__.py:5

BUSINESS RULES / CONSTRAINTS:
- BR-001: Pipeline MUST scrape using Scrapling with robots_txt_obey=True
- BR-002: Enrichment uses ONE fixed provider per run — no silent provider fallback
- BR-003: Dedup key = normalized domain (lowercased, stripped of www. and trailing slash)
- BR-004: On dedup_key collision, keep row with more populated enrichment fields; tie-break alphabetically
- BR-005: Never merge two partial rows — discarded rows logged to rejected_duplicates with reason
- BR-006: Lead score is deterministic formula only — no ML/AI inference
- BR-007: Failed fetches retry 3x with exponential backoff (1s, 4s, 16s)
- BR-008: One target failure must NOT abort the entire run
- BR-009: >30% target failure rate -> abort promotion, raise PipelineThresholdError
- BR-010: Credentials via environment variables ONLY (GOOGLE_SA_KEY, ENRICH_API_KEY) — never committed
- BR-011: Pipeline MUST abort at startup if required env vars missing
- BR-012: Invalid email format -> prefix with "UNVERIFIED:", never silently drop or trust
- BR-013: Empty company_name OR (both email and phone empty) -> reject row, log reason
- BR-014: Staging tab cleared before each write; production append-only via dedup_key check
- BR-015: All records without a dedup_key pass through dedup as-is (never dropped)
- BR-016: Premium customers get priority fulfillment (defined in worked example KG only — not implemented in this project)
- BR-017: India-only scope — all target sites are Indian directories

NON-GOALS / OUT OF SCOPE (project-wide):
- No LinkedIn scraping — LinkedIn data enters only via manual CSV import into linkedin_manual tab
- No email verification (SMTP ping/deliverability) — deferred to v2
- No CRM synchronization (Salesforce/HubSpot) — deferred to v2
- No AI-based lead scoring — scoring is pure deterministic formula
- No multi-currency support
- No backorders support
- No Google Sheets integration (replaced with SQLite)

GLOSSARY:
- "lead" = A prospect company record ready for sales outreach
- "enrichment" = Fetching supplementary data (employee_count, revenue_band) from an external API per company website
- "dedup_key" = Normalized domain (lowercased, www.-stripped, no trailing slash) used as primary dedup identifier
- "dedup" = Deduplication process that keeps the record with more enrichment fields on collision
- "staging" = Intermediate database tab written every pipeline run, cleared before each write
- "promotion" = Copying staging rows to the Leads production tab after human review or threshold check
- "dry_run" = Pipeline mode that writes only to staging, skips promotion and threshold alerts
- "target" = A configured business directory URL with an associated parser function
- "industry_code" = Industry classification string from scraped data (not normalized)
- "revenue_band" = Enriched revenue range string (e.g. "$10M-$50M")
- "lead_score" = Integer 0-100 computed via deterministic formula
- "normalized_domain" = Website URL lowercased, www. stripped, trailing slash stripped

KNOWN GAPS / UNVERIFIED AREAS:
- Discount/promo logic is not modeled in this KG
- Enrichment API coverage for Indian companies not yet validated in production
- Enrichment API provider not yet selected/locked — placeholder integration only
- Source site HTML structure changes not yet handled (each site's scraper is isolated)
- Google Sheets API quota handling not implemented (migrated to SQLite)
- LinkedIn manual import tab exists in schema but no ingestion code
- Email deliverability (SMTP ping) not implemented
- CRM sync not implemented
- Webhook/email alert for threshold breach not implemented
- No monitoring/alerting infrastructure in place

GOVERNANCE:
- Owner: Platform Team
- Coverage: ~85%
- Confidence: 90%
- Review Date: 2026-09-01
- Deprecated Nodes: none
- Pending Changes: none

</PROJECT_KNOWLEDGE_GRAPH>
