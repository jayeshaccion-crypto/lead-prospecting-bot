# Implementation Plan: Lead Prospecting Pipeline

**Branch**: `001-lead-prospecting-pipeline` | **Date**: 2026-07-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-lead-prospecting-pipeline/spec.md`

## Summary

Build a Python 3.11 batch pipeline that scrapes **Indian** business directories (Justdial, IndiaMART, TradeIndia) using Scrapling, enriches records via a fixed API, deduplicates by normalized domain, and writes sales-ready rows to Google Sheets with a 12-column schema. Runs weekly via cron, writes to a staging tab first, promotes to production after human review.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- Scrapling (stealthy fetch + HTML parse)
- google-api-python-client, google-auth (Google Sheets API v4, service account)
- pydantic (row validation)
- APScheduler (scheduling — alternative: system cron)
- httpx or requests (enrichment API calls)
- python-dotenv (local dev env loading)

**Storage**: Google Sheets API v4 (service account, no user OAuth). Auxiliary storage: in-sheet error tabs (`scrape_errors`, `rejected_duplicates`), no local database.

**Testing**: pytest with pytest-mock for unit tests; a test Google Sheet for integration tests; Scrapling's test utilities for mock HTML fixtures.

**Target Platform**: Linux server (headless, cron-based). Compatible with Windows/macOS for local dev.

**Project Type**: CLI batch script / Python module. Invoked as `python -m lead_prospecting` or via a single entry-point script. Not a web service.

**Performance Goals**: A full run against 10 target sites completes within 30 minutes. Each target site scrape respects a per-site timeout to prevent one slow site from blocking the run.

**Constraints**:
- No Selenium, Playwright, or browser automation — Scrapling's StealthyFetcher must handle all targets.
- No LinkedIn scraping by any code path.
- All credentials via env vars only — fail-closed at startup if missing.
- `robots_txt_obey=True` on all Scrapling fetches.
- No ML or AI-based scoring — deterministic formula only.

**Scale/Scope**: 10–20 Indian target sites, ~50–500 leads per week. Single-process pipeline, no horizontal scaling needed.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

All five constitution principles are satisfied by the technical approach:

| Principle | Compliance Evidence |
|---|---|
| I. Robots.txt Compliance | Scrapling `StealthyFetcher` with `robots_txt_obey=True` |
| II. No LinkedIn Scraping | No LinkedIn targets configured; all code paths auditable |
| III. Credential Security (Fail-Closed) | `GOOGLE_SA_KEY` and `ENRICH_API_KEY` via env vars only; startup abort if missing |
| IV. Idempotent Sheet Writes | dedup_key check before append; collision resolution by enrichment field count |
| V. Resilient Scraping | Per-site try/except with 3x exponential backoff; 30% threshold blocks promotion |

**No violations found. Gate passes. Proceeding to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/001-lead-prospecting-pipeline/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0 — technical research & decisions
├── data-model.md        # Phase 1 — entity definitions & validation rules
├── quickstart.md        # Phase 1 — validation guide
├── contracts/           # Phase 1 — interface contracts
└── tasks.md             # Phase 2 — task breakdown (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
├── __init__.py
├── __main__.py          # Entry point: python -m src
├── config.py            # Env var loading, target config, industry list
├── models.py            # Pydantic models (LeadRecord, ScrapeError, etc.)
├── scraper/
│   ├── __init__.py
│   ├── engine.py        # Orchestrates scraping across all targets
│   ├── targets.py       # Per-site scrape logic & HTML parsing
│   └── utils.py         # Normalize domain, email validation, retry helpers
├── enrichment/
│   ├── __init__.py
│   └── client.py        # Enrichment API client
├── sheets/
│   ├── __init__.py
│   ├── client.py        # Google Sheets API wrapper (service account)
│   └── tabs.py          # Tab management: staging, production, error tabs
├── scoring.py           # Deterministic lead score computation
├── validation.py        # Row validation rules (pydantic)
├── pipeline.py          # Main pipeline orchestration
└── scheduler.py         # APScheduler or cron entry hook

tests/
├── __init__.py
├── conftest.py           # Fixtures: mock sheets, mock HTML, mock enrichment
├── test_models.py
├── test_scoring.py
├── test_validation.py
├── test_dedup.py
├── test_sheets.py
├── test_pipeline.py
└── fixtures/             # Sample HTML pages, JSON responses
```

**Structure Decision**: Single Python package under `src/` with sub-packages for scraper, enrichment, and sheets. Tests mirror the source layout under `tests/`. No web framework — this is a CLI batch script.

## Complexity Tracking

No constitution violations. Complexity is appropriate for the scope.
