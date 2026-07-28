# Feature Specification: Automated Lead Prospecting Pipeline

## Summary
Automate lead prospecting by scraping Indian business directories with
**Scrapling**, extracting core contact fields, enriching each record via a
single fixed enrichment API, deduplicating on normalized domain, and writing
sales-ready rows to a Google Sheet on a weekly schedule.

## Goals
- Produce a consistent, reproducible weekly batch of qualified leads with zero
  manual research.
- Guarantee the same input state always produces the same output rows
  (idempotent, deterministic scoring, deterministic dedup).
- Fail loudly and specifically rather than silently dropping or corrupting data.

## Non-Goals (explicitly out of scope for v1)
- No LinkedIn scraping. LinkedIn's Terms of Service restrict automated scraping
  of profile data, and this has been litigated (e.g. hiQ Labs v. LinkedIn).
  LinkedIn data enters the system only via manual CSV export/import into a
  separate `linkedin_manual` tab, matched by `normalized_domain`.
- No email verification (SMTP ping / deliverability check) — deferred to v2.
- No CRM synchronization — deferred to v2.
- No AI-based lead scoring or judgment calls — scoring is a pure deterministic
  formula (see below), not a model inference.

## Integrations
| Component | Choice | Notes |
|---|---|---|
| Scraper | [Scrapling](https://github.com/D4Vinci/Scrapling) | `StealthyFetcher`, `adaptive=True`, `robots_txt_obey=True` |
| Storage | Google Sheets API v4 | Service account auth, not user OAuth (needed for unattended/scheduled runs) |
| Enrichment | One fixed provider (e.g. Clearbit / OpenCorporates / Companies House) | Must be selected and locked before implementation; no silent provider fallback |

## Credentials
- `GOOGLE_SA_KEY` — base64-encoded service account JSON, scope
  `https://www.googleapis.com/auth/spreadsheets`.
- `ENRICH_API_KEY` — enrichment provider API key.
- Both are environment variables only. Never committed to source control.
- If either is missing at run start, the pipeline aborts before making any
  network calls or sheet writes (fail closed).

## Data Model — Google Sheet Columns (fixed order, row 1 = header, never reordered)

| Col | Field | Source |
|---|---|---|
| A | company_name | scraped |
| B | website | scraped |
| C | email | scraped (prefixed `UNVERIFIED:` if regex-invalid) |
| D | phone | scraped |
| E | address | scraped |
| F | industry_code | scraped |
| G | employee_count | enrichment |
| H | revenue_band | enrichment |
| I | source_url | scraped |
| J | scraped_at | ISO 8601 UTC timestamp |
| K | dedup_key | normalized_domain |
| L | lead_score | computed (see formula) |

Additional tabs:
- `staging` — dry-run output, written every run before promotion.
- `scrape_errors` — `{url, timestamp, error_type}` per failed fetch.
- `rejected_duplicates` — rows discarded by the dedup rule, with reason.
- `linkedin_manual` — manually imported LinkedIn data, matched by `dedup_key`.

## Deduplication Rule
- Primary key: `normalized_domain` = website lowercased, `www.` stripped,
  trailing slash stripped.
- On collision: keep the row with the more recently populated enrichment
  fields (more non-null values among employee_count/revenue_band); discard
  the other.
- Never merge two partial rows into one silently. Discarded rows are logged
  to `rejected_duplicates`, not deleted without trace.

## Lead Score Formula (deterministic, no model inference)
```
score = 40 * has_email
      + 20 * has_phone
      + 20 * (10 <= employee_count <= 500)
      + 20 * (industry_code in target_industry_list)
```
Range: 0–100. `target_industry_list` is a fixed config value, versioned
alongside the pipeline code.

## Validation Rules (applied before any sheet write)
- Reject (do not write) a row if `company_name` is empty, OR if both `email`
  and `phone` are empty.
- Email must match an RFC 5322-lite pattern. If it doesn't, keep the row but
  prefix the value `UNVERIFIED:` — never silently drop, never silently trust.

## Scheduling
- Cron: `0 6 * * 1` (every Monday, 06:00 UTC).
- Idempotent: re-running on the same day must not create duplicate rows
  (checked via `dedup_key` against existing sheet contents before append).

## Error Handling
- Each target site is wrapped in its own try/except; one site's failure never
  aborts the whole run.
- Failed fetches retry 3x with exponential backoff (1s, 4s, 16s), then log to
  `scrape_errors` and continue to the next target.
- If more than 30% of targets fail in a single run, send one summary alert
  (webhook or email) and do **not** promote `staging` to the production tab
  for that run.

## Scope — India-Only
All target business directories are Indian. Industry codes, enrichment API
coverage, and dedup logic are optimised for Indian companies. Non-Indian
directories are out of scope for this feature.

## Deploy Process
1. Run in dry-run mode — all output goes to the `staging` tab only, no alerts
   fire, production tab is untouched.
2. A human reviews a fixed checklist: row count vs. expected, % of required
   fields populated, 0 unhandled exceptions in the run log.
3. Only after that checklist passes does the pipeline copy `staging` rows into
   the production tab.

## Acceptance Criteria
- [ ] Running the pipeline twice against the same source pages produces
      identical sheet output (no duplicate rows, same `lead_score` values).
- [ ] Killing the process mid-run and re-running does not corrupt the sheet
      or double-count rows.
- [ ] A single unreachable target site does not prevent other targets from
      being scraped in the same run.
- [ ] No credentials appear in logs, source control, or the sheet itself.
- [ ] LinkedIn is never scraped by any code path in this feature.

## Future Expansion (tracked separately, not part of this spec)
- v2: email deliverability verification (SMTP ping) as its own spec.
- v2: CRM sync (Salesforce/HubSpot) as its own spec.
