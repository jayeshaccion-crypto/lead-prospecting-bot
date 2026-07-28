# Feature Specification: Lead Prospecting Pipeline

**Feature Branch**: `001-lead-prospecting-pipeline`

**Created**: 2026-07-28

**Status**: Draft

**Scope**: India-only — all configured target sites are Indian business directories.

**Input**: User description: "Build a lead-prospecting pipeline that scrapes Indian business directories with Scrapling, extracts company_name/website/email/phone/address/industry_code, enriches each record via a single fixed enrichment API, deduplicates on normalized domain, and writes to a Google Sheet with a fixed 12-column schema..."

## User Scenarios & Testing

### User Story 1 - Automated Weekly Lead Collection (Priority: P1)

As a sales operations manager, I want the pipeline to automatically scrape public business directories and company websites every Monday morning so that my sales team starts each week with a fresh batch of qualified leads without any manual research effort.

**Why this priority**: This is the core value proposition — zero-touch lead generation on a recurring schedule. Without this, there is no pipeline.

**Independent Test**: Can be fully tested by running the pipeline against a known set of target URLs and verifying that output rows appear in the staging sheet tab with populated company_name, website, email, phone, and address fields.

**Acceptance Scenarios**:

1. **Given** the pipeline is scheduled for Monday 06:00 UTC, **When** the cron trigger fires, **Then** scraping begins for all configured target sites.
2. **Given** a target site is reachable and contains business listings, **When** the scraper completes, **Then** records contain company_name, website, email, phone, address, and industry_code.
3. **Given** a target site is unreachable, **When** the scraper fails after 3 retries (1s, 4s, 16s backoff), **Then** the error is logged to the `scrape_errors` tab with url, timestamp, and error_type, and the run continues with other targets.
4. **Given** more than 30% of target sites fail in a single run, **When** the run completes, **Then** a summary alert fires and the staging tab is not promoted to production.

---

### User Story 2 - Enrichment & Scoring (Priority: P1)

As a sales operations manager, I want each scraped record to be enriched with employee count and revenue band from a trusted data provider and scored against a deterministic formula so that my team can prioritize outreach based on data fit.

**Why this priority**: Both stories are P1 — without enrichment and scoring, the raw scraped data lacks the context needed for sales prioritization. Enrichment happens inline during the same pipeline run.

**Independent Test**: Can be tested by running the pipeline and verifying that employee_count and revenue_band columns are populated for records where the enrichment API returned data, and that lead_score is computed as 0–100 per the formula.

**Acceptance Scenarios**:

1. **Given** a scraped record with a valid website, **When** the enrichment API is called, **Then** employee_count and revenue_band are populated from the API response.
2. **Given** a scraped record with email populated, **When** lead score is computed, **Then** the score includes +40 for has_email.
3. **Given** a scraped record where employee_count is between 10 and 500, **When** lead score is computed, **Then** the score includes +20 for size fit.
4. **Given** the exact same input data on two separate runs, **When** lead score is computed, **Then** the score is identical both times (deterministic).

---

### User Story 3 - Idempotent Deduplication (Priority: P1)

As a sales operations manager, I want the pipeline to deduplicate records by normalized domain so that my team never contacts the same company twice, even if the pipeline is re-run or interrupted mid-run.

**Why this priority**: Data quality is non-negotiable — duplicates damage credibility and waste sales effort.

**Independent Test**: Can be tested by running the pipeline twice against the same source data and verifying that no duplicate rows exist in the output.

**Acceptance Scenarios**:

1. **Given** the pipeline has already written records for a set of domains, **When** the pipeline runs again, **Then** no new rows are appended for already-seen dedup_keys.
2. **Given** two records with the same normalized domain but different enrichment fill levels, **When** deduplication occurs, **Then** the record with more populated enrichment fields (employee_count, revenue_band) is kept and the other is logged to `rejected_duplicates` with reason.
3. **Given** the pipeline is killed mid-write and re-run, **When** it resumes, **Then** no duplicate or orphan rows appear in the sheet.

---

### User Story 4 - Dry-Run & Human Review (Priority: P2)

As a sales operations manager, I want the pipeline to first write results to a staging tab and only promote to production after human review so that I can catch data quality issues before my team sees bad leads.

**Why this priority**: Valuable but not blocking — initial runs can be monitored manually.

**Independent Test**: Can be tested by running the pipeline in dry-run mode and verifying that output appears only in the `staging` tab and the production tab is untouched.

**Acceptance Scenarios**:

1. **Given** the pipeline is started in dry-run mode, **When** it completes, **Then** all output rows appear in the `staging` tab and no rows are written to the production tab.
2. **Given** a human reviews the staging tab against a checklist (row count, field fill rate, exception count), **When** the checklist passes, **Then** the promotion copies staging rows into the production tab.
3. **Given** the checklist fails (e.g., >30% targets failed), **When** the pipeline detects this, **Then** alert fires and staging is not promoted.

---

### User Story 5 - Malformed Data Handling (Priority: P2)

As a sales operations manager, I want the pipeline to never silently drop or corrupt malformed rows so that I have full visibility into data quality issues and can trace every rejection.

**Why this priority**: Data integrity is critical, but the pipeline can function without this in a pinch as long as the core scrape/enrich loop works.

**Independent Test**: Can be tested by feeding deliberately malformed data and verifying that rejected rows appear in the appropriate error tabs with reasons.

**Acceptance Scenarios**:

1. **Given** a scraped record has an empty company_name, **When** validation runs, **Then** the row is rejected and not written to any output tab.
2. **Given** a scraped record has an invalid email format, **When** validation runs, **Then** the email is prefixed with `UNVERIFIED:` and the row is kept.
3. **Given** a scraped record has both email and phone empty, **When** validation runs, **Then** the row is rejected entirely.

### India-Specific Considerations

- All target sites are Indian business directories (Justdial, IndiaMART, TradeIndia, etc.).
- Industry codes in `target_industry_list` reflect common Indian industry classifications (IT Services, BFSI, Pharmaceuticals, Textiles, etc.).
- Phone numbers are Indian format (+91 prefix) and accepted as-is without format normalisation.
- Addresses are Indian addresses (city, state, pincode) and stored as a single text field without structured parsing.
- Enrichment API coverage should be validated for Indian companies before production use.
- Scraping schedule (Monday 06:00 UTC) maps to 11:30 AM IST, suitable for Indian business hours if human review is needed same-day.

### Edge Cases

- What happens when the enrichment API is down or returns errors? — The pipeline logs the failure and continues; enrichment fields remain null for affected records.
- How does the system handle a target site that changes its HTML structure? — Each site's scraper is isolated; a structural failure on one site does not affect others.
- What happens when the Google Sheet API quota is exceeded? — The pipeline retries with backoff; if persistent, the run fails loudly and staging is not promoted.
- What happens if a single domain appears in multiple target sites? — The dedup_key collision rule applies: the row with more enrichment fields is kept; the other is logged to `rejected_duplicates`.

## Requirements

### Functional Requirements

- **FR-001**: Pipeline MUST scrape configured Indian business directories using Scrapling with `robots_txt_obey=True`.
- **FR-002**: Pipeline MUST extract company_name, website, email, phone, address, and industry_code from each scraped record.
- **FR-003**: Pipeline MUST enrich each record with employee_count and revenue_band from a single fixed enrichment API.
- **FR-004**: Pipeline MUST deduplicate records by normalized_domain (lowercased, stripped of `www.` and trailing slash).
- **FR-005**: On dedup_key collision, pipeline MUST keep the row with more populated enrichment fields and log the discarded row to `rejected_duplicates`.
- **FR-006**: Pipeline MUST compute lead_score via deterministic formula and write it to the sheet.
- **FR-007**: Pipeline MUST write output to a Google Sheet with a fixed 12-column schema in order: company_name, website, email, phone, address, industry_code, employee_count, revenue_band, source_url, scraped_at, dedup_key, lead_score.
- **FR-008**: Pipeline MUST write to a `staging` tab first; promotion to the production tab requires human approval.
- **FR-009**: Pipeline MUST run on a weekly schedule (Monday 06:00 UTC) and be idempotent — re-runs on the same day must not create duplicates.
- **FR-010**: Pipeline MUST reject rows where company_name is empty or both email and phone are empty.
- **FR-011**: Pipeline MUST prefix non-RFC-5322-lite emails with `UNVERIFIED:` rather than silently dropping or trusting them.
- **FR-012**: Pipeline MUST wrap each target site in its own try/except — one site failure must not abort the run.
- **FR-013**: Failed fetches MUST retry 3 times with exponential backoff (1s, 4s, 16s), then log to `scrape_errors`.
- **FR-014**: If more than 30% of targets fail, pipeline MUST send an alert and MUST NOT promote staging to production.
- **FR-015**: Credentials MUST be supplied via environment variables only (`GOOGLE_SA_KEY`, `ENRICH_API_KEY`) and never committed to source control.
- **FR-016**: Pipeline MUST abort at startup if required environment variables are missing, before making any network calls.

### Key Entities

- **Lead Record**: A single row representing a prospective company. Attributes: company_name, website, email, phone, address, industry_code, employee_count, revenue_band, source_url, scraped_at, dedup_key, lead_score.
- **Target Site**: A configured public business directory or company website to scrape. Each target has its own URL, parsing rules, and is scraped independently.
- **Dedup Key**: The normalized domain derived from the website field — the primary key for deduplication and for matching LinkedIn manual imports.
- **Enrichment Record**: Supplementary data (employee_count, revenue_band) fetched from the enrichment API for a given company website.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A complete pipeline run produces output rows in the staging tab within 30 minutes for up to 10 target sites.
- **SC-002**: Running the pipeline twice against identical source data produces identical sheet output — no duplicate rows, same lead_score values.
- **SC-003**: A single unreachable target site does not prevent other targets from being scraped in the same run — at minimum 90% of reachable targets succeed.
- **SC-004**: Zero credentials appear in logs, source control, or sheet output across all runs.
- **SC-005**: Malformed rows (empty company_name, missing email and phone) are rejected with traceable reasons 100% of the time — no silent drops.

## Assumptions

- Target business directories and company websites are publicly accessible and do not require authentication or login.
- The enrichment API provides employee_count and revenue_band data for a majority of queried companies.
- The Google Sheet exists with the correct 12-column header row before the first pipeline run.
- Pipeline runs on a system with network access to all target sites, the enrichment API, and the Google Sheets API.
- All target sites are Indian business directories — non-Indian directories are out of scope.
- LinkedIn data is out of scope for v1 — any LinkedIn integration comes only via manual CSV import into the `linkedin_manual` tab.
- Email verification (SMTP ping) is out of scope for v1 — emails are surfaced as-is with an `UNVERIFIED:` prefix if invalid format.
- CRM synchronization (Salesforce/HubSpot) is out of scope for v1.
