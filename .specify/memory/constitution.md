<!--
  Sync Impact Report:
  - Version change: 0.0.0 → 1.0.0
  - Principles: 5 core principles created from spec.md requirements
  - Added sections: Core Principles (5 items), Data Quality & Validation, Deployment & Release
  - Templates requiring updates:
    - constitution-template.md: ✅ updated (this file)
    - plan-template.md: ✅ checked — no changes needed
    - spec-template.md: ✅ checked — no changes needed
    - tasks-template.md: ✅ checked — no changes needed
-->
# Lead Prospecting Bot Constitution

## Scope — India-Only
All target business directories are Indian. Industry codes, enrichment API coverage, phone/address formats, and all documentation are scoped to Indian companies. Non-Indian directories (YellowPages.com, Yelp, etc.) are explicitly excluded.

## Core Principles

### I. Robots.txt Compliance (NON-NEGOTIABLE)
All scraping MUST use Scrapling's `StealthyFetcher` with `robots_txt_obey=True` and `adaptive=True`. Every target site's `robots.txt` is authoritative. A scraper MUST NOT fetch any URL disallowed by the target's `robots.txt`. This applies to all code paths — no scraping bypass, override, or silent fallback is permitted.

### II. No LinkedIn Scraping (v1 Absolute Prohibition)
The pipeline MUST NOT scrape LinkedIn by any code path. LinkedIn data enters the system only via manual CSV export/import into the dedicated `linkedin_manual` tab, matched by `normalized_domain`. This prohibition applies to all direct fetches, sub-scrapers, enrichment callbacks, and transitive dependencies. Violations in v1 are a blocking defect.

### III. Credential Security (Fail-Closed)
All credentials MUST be supplied as environment variables only (`GOOGLE_SA_KEY`, `ENRICH_API_KEY`). Neither key may appear in source code, configuration files, logs, error messages, or sheet output. If either variable is missing or empty at startup, the pipeline MUST abort before making any network calls or sheet writes. Credentials MUST never be committed to source control.

### IV. Idempotent Sheet Writes
Every write to Google Sheets MUST check for existing rows by `dedup_key` (normalized_domain) before appending. Re-running the pipeline on the same day MUST NOT create duplicate rows. On dedup_key collision, keep the row with more non-null enrichment fields (`employee_count`, `revenue_band`); discard the other. Discarded rows MUST be logged to the `rejected_duplicates` tab with reason — never merged silently, never deleted without trace.

### V. Resilient Scraping (No Single-Point Failure)
Each target site MUST be wrapped in its own try/except — one site's failure MUST NOT abort the entire run. Failed fetches MUST retry 3 times with exponential backoff (1s, 4s, 16s) before being logged to the `scrape_errors` tab. If more than 30% of targets fail in a single run, the pipeline MUST send a summary alert and MUST NOT promote the `staging` tab to production for that run.

## Data Quality & Validation

### Required Fields Validation
Before any sheet write, each row MUST pass these gates:
- `company_name` MUST be non-empty — rows with empty company_name are rejected entirely.
- At least one of `email` or `phone` MUST be non-empty — rows missing both are rejected entirely.
- Email MUST match an RFC 5322-lite pattern. Non-matching emails are prefixed with `UNVERIFIED:` — never silently dropped, never silently trusted.

### Deterministic Scoring
Lead score is computed by a pure deterministic formula only:
```
score = 40*has_email + 20*has_phone + 20*(10<=emp<=500) + 20*(industry in target_industry_list)
```
Range: 0–100. No ML inference, no AI-based scoring, no judgment calls. `target_industry_list` is a fixed config value versioned alongside the pipeline code. Same input MUST always produce the same score.

### Deduplication Key
`dedup_key` is the normalized domain: website lowercased, `www.` stripped, trailing slash stripped. This is the primary key for all dedup operations and for matching LinkedIn manual imports.

## Deployment & Release

### Two-Phase Promotion
1. Dry-run mode writes all output to the `staging` tab only — no alerts fire, production tab untouched.
2. After human review against a fixed checklist (row count vs expected, % of required fields populated, 0 unhandled exceptions), the pipeline copies `staging` rows into the production tab.

### Scheduling
Pipeline runs on cron `0 6 * * 1` (every Monday 06:00 UTC). The pipeline is idempotent — re-running on the same day MUST NOT create duplicate rows.

### Error Handling & Observability
- Failed fetches are logged to `scrape_errors` tab with `{url, timestamp, error_type}`.
- Rejected duplicates are logged to `rejected_duplicates` tab with reason.
- Staging tab holds dry-run output for every run.
- `linkedin_manual` tab holds manually imported LinkedIn data, matched by `dedup_key`.

## Knowledge Graph Grounding

### VI. CodeGraph-First Retrieval (NON-NEGOTIABLE)
Before writing any spec, plan, task, or code, the agent MUST query CodeGraph for the relevant module/entity context (callers, callees, impact scope). Blind file scanning is not permitted when indexed symbols exist. If CodeGraph returns no results for a named symbol, the agent may fall back to file search and flag the gap in the Known Gaps section of the Knowledge Graph.

### VII. CONTEXT USED Declaration
Every non-trivial output MUST open with a `CONTEXT USED / ASSUMPTIONS / OUT OF SCOPE` block naming which KG entities, contracts, and business rules were consulted. If information was missing and had to be assumed, the assumption MUST be scored per the Confidence scale (100%/90%/75%/50%/<50%) and logged in the Assumption Register.

### VIII. Scope-Fidelity Enforcement
Any `/plan` or `/tasks` output that would touch code outside the declared scope — as determined by CodeGraph's impact analysis — MUST be flagged explicitly. Scope creep must be called out, not silently absorbed.

### IX. Knowledge Graph Authoritative
The Knowledge Graph (`KNOWLEDGE_GRAPH.md`) is the authoritative source of project entities, contracts, and business rules. If it is missing information needed for a task, the agent MUST stop and ask rather than inventing entities, business rules, or contracts. Guesses in the KG's Known Gaps section are acceptable only if labelled as unverified.

### X. Reproducibility Statement
Every substantial response MUST end with: `Reproducible: Yes/No — <reason>.` A "Yes" means another engineer with the same KG and same input would get materially the same output. "No" means judgment calls were made that a human should review.

## Governance

This constitution supersedes all other development guidance for the Lead Prospecting Bot project. Amendments require a documented proposal, approval, and a migration plan for existing behavior. Every pull request and review MUST verify compliance with these principles. Complexity deviations from these principles MUST be justified in writing.

**Version**: 1.1.0 | **Ratified**: 2026-07-28 | **Last Amended**: 2026-07-30
