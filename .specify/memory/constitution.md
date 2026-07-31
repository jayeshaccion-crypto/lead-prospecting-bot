<!--
  Sync Impact Report:
  - Version change: 1.1.0 → 1.2.0
  - Modified principles:
    - III. Credential Security → broadened to cover proxy/Neo4j/generic credentials + commit prohibition
    - IV. Idempotent Sheet Writes → Idempotent Operations (every phase, not just sheets)
    - V. Resilient Scraping → amended with "fail loudly" requirement
  - Updated section: Scoring formula in Data Quality & Validation (new weights)
  - Added sections:
    - Entity Resolution Transparency (new paragraph in Data Quality & Validation)
    - Data Layer Isolation (new paragraph in Data Quality & Validation)
  - Removed sections: None
  - Templates requiring updates:
    - constitution-template.md: ✅ updated
    - plan-template.md: ✅ existing Constitution Check section sufficient
    - spec-template.md: ✅ existing scope/requirements section sufficient
    - tasks-template.md: ✅ existing task categorization sufficient
  - Follow-up TODOs: None
-->
# Lead Prospecting Bot Constitution

## Scope — India-Only
All target business directories are Indian. Industry codes, enrichment API coverage,
phone/address formats, and all documentation are scoped to Indian companies. Non-Indian
directories (YellowPages.com, Yelp, etc.) are explicitly excluded.

## Core Principles

### I. Robots.txt Compliance (NON-NEGOTIABLE)
All scraping MUST use Scrapling's `StealthyFetcher` with `robots_txt_obey=True` and
`adaptive=True`. Every target site's `robots.txt` is authoritative. A scraper MUST NOT
fetch any URL disallowed by the target's `robots.txt`. This applies to all code paths —
no scraping bypass, override, or silent fallback is permitted.

### II. No LinkedIn Scraping (v1 Absolute Prohibition)
The pipeline MUST NOT scrape LinkedIn by any code path. LinkedIn data enters the system
only via manual CSV export/import into the dedicated `linkedin_manual` tab, matched by
`normalized_domain`. This prohibition applies to all direct fetches, sub-scrapers,
enrichment callbacks, and transitive dependencies. Violations in v1 are a blocking defect.

### III. Credential Security (Fail-Closed, No Commits)
All credentials (proxy URLs, proxy lists, API keys, database passwords, Neo4j URIs/user/pass)
MUST be supplied as environment variables only. Credentials MUST NOT appear in source code,
configuration files under version control, logs, error messages, sheet output, or anywhere
that could be committed to git. If any required credential is missing or empty at startup,
the component that depends on it MUST fail explicitly (logged warning + `ScrapeError`) —
never silently skip or degrade. The `.env` file pattern MUST be in `.gitignore`. Credential
equivalents MUST NOT be committed even in commented-out form.

### IV. Idempotent Operations
Every phase of the pipeline (scraping, enrichment, deduplication, scoring, Neo4j write,
sheet write) MUST be idempotent. Re-running the same day's data twice MUST NOT change
record/node/relationship counts on the second run. Neo4j writes use MERGE on `dedup_key`;
sheet writes check for existing rows by `dedup_key` before appending; scoring is
deterministic on the same input; enrichment skips records that already have phone+email.
On dedup_key collision, keep the row with more non-null enrichment fields; discard the
other with a logged reason in `rejected_duplicates`. Idempotency violations are a blocking
defect — prove by re-running the same data and showing unchanged counts.

### V. Resilient Scraping — Fail Loudly, Never Silently Degrade
Each target site MUST be wrapped in its own try/except — one site's failure MUST NOT abort
the entire run. Failed fetches MUST retry 3 times with exponential backoff (1s, 4s, 16s)
before being logged to `scrape_errors`.

**Fail-loudly requirement** — Every target MUST communicate its disposition explicitly:
- If a target is skipped (no proxy, disabled, proxy pool exhausted): a clear
  `logger.warning` or `ScrapeError("ProxyNotConfigured")` MUST be emitted. Never skip
  a target with a quiet 0-record contribution.
- If a downstream dependency fails (Neo4j write fails, detail-page enrichment errors):
  the failure MUST be logged at WARNING or ERROR level with enough context to diagnose.
  If Neo4j write fails entirely, the pipeline summary MUST include an explicit
  `"neo4j_failed": true` flag — not just `neo4j_created=0` that looks like empty data.
- The final run summary MUST state every target's disposition so daily volume numbers
  are never ambiguous.

If more than 30% of targets fail in a single run, the pipeline MUST NOT promote staging
to production for that run.

## Data Quality & Validation

### Required Fields Validation
Before any sheet write, each row MUST pass these gates:
- `company_name` MUST be non-empty — rows with empty company_name are rejected entirely.
- At least one of `email` or `phone` MUST be non-empty — rows missing both are rejected
  entirely.
- Email MUST match an RFC 5322-lite pattern. Non-matching emails are prefixed with
  `UNVERIFIED:` — never silently dropped, never silently trusted.

### Deterministic Scoring
Lead score is computed by a pure deterministic formula only:
```
has_phone:                          +25
has_email:                          +15
has_website:                        +15
multi_source, 2+ sites:             +25   \_ pick higher tier only,
multi_source, all 3 sites:          +35   /  not additive
recency: first_seen == today        +10
         within last 7 days          +5
         older                       +0
ICP match (category or city):       +10
```
Range: 0–100, capped at 100. The component breakdown MUST be
stored as `lead_score_breakdown` (JSON) alongside the total `lead_score` for auditability.
No ML inference, no AI-based scoring, no judgment calls. `icp_categories` and `icp_cities`
are fixed config values versioned alongside the pipeline code. Same input MUST always
produce the same score.

### Entity Resolution Transparency
Every entity-resolution merge (phone-match or fuzzy name-match) MUST be logged with
sufficient detail before the write is committed:
- **Phone matches**: logged at INFO level with both company names + phone used.
- **Fuzzy matches**: logged at INFO level AND written to a dedicated review log file
  (`debug_output/fuzzy_matches.log`) with both company names, the similarity score, and
  the threshold used. This file is for manual spot-checking — wrong merges corrupt the
  graph permanently and are hard to unwind.
- Matches below the threshold (90) MUST also be logged at DEBUG level with score and
  candidate name — never silently discarded without trace.
- Every run MUST log separate counts for: new Company nodes created, existing matched
  by phone, existing matched by fuzzy name, and total graph size (node + relationship counts).

### Data Layer Isolation (Score Separation)
`lead_score` and `lead_score_breakdown` MUST exist ONLY in the data layer (SQLite
Leads table, Neo4j Company node properties). They MUST NOT appear in:
- Dashboard HTML/JS/CSS output (`build_dashboard.py` query, table columns, sort, filter,
  tooltips, embedded JSON sent to frontend, or any user-facing render)
- Any user-facing export, CSV preview, or notification
The dashboard MUST be grep-confirmed clean of `lead_score` references before every
deployment.

### Deduplication Key
`dedup_key` is the normalized domain: website lowercased, `www.` stripped, trailing slash
stripped. For entity resolution in Neo4j, the strongest signal is phone number (last 10
digits, hashed via dedup_key). When phone is unavailable, fall back to name + website.

## Deployment & Release

### Two-Phase Promotion
1. Dry-run mode writes all output to the `staging` tab only — no alerts fire, production
   tab untouched.
2. After human review against a fixed checklist (row count vs expected, % of required
   fields populated, 0 unhandled exceptions), the pipeline copies `staging` rows into
   the production tab.

### Scheduling
Pipeline runs on cron `0 6 * * 1-5` (weekdays 06:00 UTC / 11:30 IST). The pipeline is
idempotent — re-running on the same day MUST NOT create duplicate rows or nodes.

### Error Handling & Observability
- Failed fetches are logged to `scrape_errors` tab with `{url, timestamp, error_type}`.
- Rejected duplicates are logged to `rejected_duplicates` tab with reason.
- Staging tab holds dry-run output for every run.
- `linkedin_manual` tab holds manually imported LinkedIn data, matched by `dedup_key`.
- Neo4j write failures produce an explicit `"neo4j_failed": true` flag in the summary.
- Fuzzy-match review log written to `debug_output/fuzzy_matches.log`.

## Knowledge Graph Grounding

### VI. CodeGraph-First Retrieval (NON-NEGOTIABLE)
Before writing any spec, plan, task, or code, the agent MUST query CodeGraph for the
relevant module/entity context (callers, callees, impact scope). Blind file scanning is
not permitted when indexed symbols exist. If CodeGraph returns no results for a named
symbol, the agent may fall back to file search and flag the gap in the Known Gaps section
of the Knowledge Graph.

### VII. CONTEXT USED Declaration
Every non-trivial output MUST open with a `CONTEXT USED / ASSUMPTIONS / OUT OF SCOPE`
block naming which KG entities, contracts, and business rules were consulted. If information
was missing and had to be assumed, the assumption MUST be scored per the Confidence scale
(100%/90%/75%/50%/<50%) and logged in the Assumption Register.

### VIII. Scope-Fidelity Enforcement
Any `/plan` or `/tasks` output that would touch code outside the declared scope — as
determined by CodeGraph's impact analysis — MUST be flagged explicitly. Scope creep must
be called out, not silently absorbed.

### IX. Knowledge Graph Authoritative
The Knowledge Graph (`KNOWLEDGE_GRAPH.md`) is the authoritative source of project entities,
contracts, and business rules. If it is missing information needed for a task, the agent
MUST stop and ask rather than inventing entities, business rules, or contracts. Guesses in
the KG's Known Gaps section are acceptable only if labelled as unverified.

### X. Reproducibility Statement
Every substantial response MUST end with: `Reproducible: Yes/No — <reason>.` A "Yes" means
another engineer with the same KG and same input would get materially the same output.
"No" means judgment calls were made that a human should review.

## Governance

This constitution supersedes all other development guidance for the Lead Prospecting Bot
project. Amendments require a documented proposal, approval, and a migration plan for
existing behavior. Every pull request and review MUST verify compliance with these
principles. Complexity deviations from these principles MUST be justified in writing.

**Version**: 1.2.0 | **Ratified**: 2026-07-28 | **Last Amended**: 2026-07-30
