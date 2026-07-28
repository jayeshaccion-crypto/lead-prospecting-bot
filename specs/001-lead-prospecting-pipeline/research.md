# Research: Lead Prospecting Pipeline

## Technology Decisions

### Scrapling for Web Scraping
- **Decision**: Scrapling with `StealthyFetcher`, `adaptive=True`, `robots_txt_obey=True`
- **Rationale**: Spec mandates Scrapling. StealthyFetcher provides browser-like TLS fingerprinting without Selenium/Playwright. CSS selector parsing via Scrapling's built-in HTML parser avoids lxml boilerplate. Per-site parsers are isolated and site-specific.
- **Alternatives considered**: Playwright (rejected — too heavy, violates minimal-dependency constraint); raw httpx+parsel (rejected — spec mandates Scrapling).

### Google Sheets API v4 (Service Account)
- **Decision**: Service account auth using `google.oauth2.service_account.Credentials`, scoped to `https://www.googleapis.com/auth/spreadsheets`
- **Rationale**: Spec mandates service account (unattended/scheduled). No user OAuth flow. Credentials loaded from base64-decoded `GOOGLE_SA_KEY` env var.
- **Alternatives considered**: User OAuth (rejected — requires manual token refresh, not suitable for cron).

### Pydantic for Row Validation
- **Decision**: Pydantic v2 models for `LeadRecord`, `ScrapeError`, `RejectedDuplicate`
- **Rationale**: Type validation, RFC 5322-lite email patterns via `EmailStr`, custom validators for dedup_key normalization. Clean error messages for rejected rows.
- **Alternatives considered**: dataclasses (rejected — no built-in validation); attrs (rejected — less ecosystem adoption than pydantic).

### APScheduler vs Cron
- **Decision**: System cron for production; APScheduler for development/testing convenience
- **Rationale**: Cron is simpler and more reliable for production weekly schedules. APScheduler provided as a convenience wrapper for `python -m src --scheduler` so the pipeline can be tested on arbitrary intervals without modifying crontab.
- **Alternatives considered**: Cron alone (sufficient for production); APScheduler alone (adds unnecessary complexity for a single weekly job).

### Enrichment API Client
- **Decision**: httpx with configurable base URL and API key header. One fixed provider per the spec — no provider fallback.
- **Rationale**: httpx supports async (future-proofing for parallel enrichment) and connection pooling. Enrichment provider identity is configurable via env var or config but must be locked to one provider per run.
- **Alternatives considered**: requests (rejected — no async support); aioresponses for testing (deferred — keep httpx sync for v1).

### Structured Logging to Google Sheets
- **Decision**: Errors are logged directly to the `scrape_errors` and `rejected_duplicates` sheet tabs via the Sheets API. Python `logging` module used for console/process-level logging (runtimes, warnings, debug); only structured error records go to the sheet.
- **Rationale**: The spec requires error logging to sheet tabs for human review. Console logging is for operational monitoring.

### Email Validation
- **Decision**: RFC 5322-lite regex pattern via pydantic's `EmailStr`. Invalid emails prefixed with `UNVERIFIED:` in the output cell.
- **Rationale**: Spec mandates this behavior. No SMTP verification in v1.

### India-Only Scope
- **Decision**: All target sites are Indian business directories only.
- **Rationale**: The enrichment API must be validated for Indian company coverage. Indian phone numbers (+91) are accepted without format normalisation. Addresses are free-text Indian addresses. Industry codes in `TARGET_INDUSTRY_LIST` reflect common Indian classifications (IT Services, BFSI, Pharma, etc.).
- **Target directories**: Justdial, IndiaMART, TradeIndia (primary); additional Indian directories can be added per-site.
- **Non-goal**: Non-Indian directories (YellowPages.com, Yelp, etc.) are explicitly out of scope.

