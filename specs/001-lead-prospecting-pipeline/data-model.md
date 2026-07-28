# Data Model: Lead Prospecting Pipeline

## LeadRecord

The primary entity. One row per prospect company.

| Field | Type | Source | Validation | Notes |
|---|---|---|---|---|
| company_name | string | scraped | Required, non-empty | |
| website | string | scraped | Valid URL | |
| email | string | scraped | RFC 5322-lite; prefixed `UNVERIFIED:` if invalid | Optional |
| phone | string | scraped | Any format accepted | Optional |
| address | string | scraped | Any format accepted | Optional |
| industry_code | string | scraped | Any string | Optional |
| employee_count | int or null | enrichment | Must be int if present | From enrichment API |
| revenue_band | string or null | enrichment | Any string | From enrichment API |
| source_url | string | scraped | Valid URL | Where this record was found |
| scraped_at | datetime | computed | ISO 8601 UTC | Timestamp of scrape |
| dedup_key | string | computed | Lowercased domain, strip `www.`, strip trailing `/` | Normalized from `website` |
| lead_score | int | computed | 0–100 | Deterministic formula |

### Validation Rules

1. `company_name` MUST be non-empty. Empty → row rejected.
2. At least one of `email` or `phone` MUST be non-empty. Both empty → row rejected.
3. `email` must match RFC 5322-lite. Non-match → prefix value with `UNVERIFIED:` in the stored cell.
4. `lead_score` computed as: `40*has_email + 20*has_phone + 20*(10 <= employee_count <= 500) + 20*(industry_code in target_industry_list)`

## ScrapeError

Logged to the `scrape_errors` sheet tab.

| Field | Type | Notes |
|---|---|---|
| url | string | The target URL that failed |
| timestamp | datetime | ISO 8601 UTC |
| error_type | string | e.g., "timeout", "http_error", "parse_error" |

## RejectedDuplicate

Logged to the `rejected_duplicates` sheet tab.

| Field | Type | Notes |
|---|---|---|
| dedup_key | string | The key that collided |
| kept_company | string | company_name of the kept row |
| rejected_company | string | company_name of the discarded row |
| reason | string | Why this row was discarded (fewer enrichment fields) |
| timestamp | datetime | ISO 8601 UTC |

## State Transitions

### Pipeline Run Lifecycle

```
START → Check env vars [fail → ABORT]
  ↓
Scrape all targets (per-site try/except, 3x retry)
  ↓
Validate scraped rows (reject invalid, flag bad emails)
  ↓
Enrich each record (API call per unique domain)
  ↓
Deduplicate (check dedup_key against existing sheet content + current batch)
  ↓
Compute lead_score
  ↓
Write to staging tab
  ↓
Check failure threshold (<30%? → YES)     [NO → ALERT, abort promotion]
  ↓
Report summary (rows scraped, enriched, rejected, errors)
  ↓
[Human reviews staging, approves promotion]
  ↓
Copy staging rows to production tab
```

### Dedup Key Collision Resolution

```
Two rows with same dedup_key:
  - Compare non-null count in [employee_count, revenue_band]
  - Row with more non-null values → kept
  - Other row → logged to rejected_duplicates with reason
  - Never merge fields between the two
```
