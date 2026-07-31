# Implementation Plan: Configurable Crawl Pagination & Targets Config

**Branch**: `005-configurable-crawl-pagination` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-configurable-crawl-pagination/spec.md`

## Summary

Restructure `config/targets.yml` into `config/targets.yaml` exposing top-level `categories`, `cities`, `icp_categories`, and `icp_cities`, pre-populated with the existing 10 categories × 10 cities. Generate IndiaMART and TradeIndia start URLs as the deterministic cross-product of categories × cities (100 combos per site at the starter size), with per-city TradeIndia `-city-{code}` URL codes stored in the config. Pagination becomes lazy and early-stopped: a target stops at its configured `max_pages` (default 10) or as soon as a page returns 0 *new* listings for that target, whichever comes first. Every request to a domain — listing pages, detail-page enrichment, and httpx enrichment — counts against a per-domain daily cap (`max_requests_per_day`), enforced as a hard stop per domain with counts persisted across runs in the same calendar day. The `SCRAPE_FULL_PAGES` environment gate is retired; the config value is the sole pagination control. The daily GitHub Actions workflow already carries the `0 6 * * 1-5` weekday cron; it is retained and the config env is updated to the renamed file.

JustDial is explicitly out of scope for depth changes (FR-004/SC-005): its configured `pages` depth (3), URL generation, and Phase 2 mode logic are untouched by this feature. The `SCRAPE_FULL_PAGES` retirement restores each target to its configured depth; JustDial's Phase 2 baseline is its configured value (3), per the SC-005 interpretation in spec.md Assumptions.

## Technical Context

**Language/Version**: Python 3.12 (3.14 fallback per project), asyncio via Scrapling's `Spider`/`CrawlerEngine`.

**Primary Dependencies**: `scrapling` (Spider framework: `start_requests`, `parse`, `on_close`, `CrawlerEngine`), PyYAML (`yaml.safe_load` in `src/config.py`), `httpx` (IndiaMART enrichment fallback).

**Storage**: File-based state — `config/targets.yaml` (targets config, `TARGETS_CONFIG` env), `data/request_counts.json` (per-day per-domain request counters, existing `DomainRequestCounter` store).

**Testing**: pytest (`tests/test_spider.py` with the `small_config` fixture mocking `load_full_config`; tests are pure offline — no live network).

**Target Platform**: GitHub Actions scheduled workflows (Ubuntu runner), Windows for local dev; pipeline invoked via `python -m src --pipeline` / `run.py`.

**Project Type**: CLI pipeline (library + CLI entrypoints `run.py`, `src/__main__.py`).

**Performance Goals**: No target requests more than its configured max pages (default 10); total requests per domain per day never exceed `max_requests_per_day` regardless of cross-product size.

**Constraints**: robots.txt compliance MUST be preserved (StealthyFetcher, `robots_txt_obey=True`, `adaptive=True`) — pagination depth and caps must not bypass robots handling. Credential safety: no secrets in config/commits. Deterministic URL generation (temperature=0 design ethos: pure functions, ordered lists, no dict-ordering surprises).

**Scale/Scope**: 10 categories × 10 cities → 100 start URLs per site (IndiaMART + TradeIndia). Caps keep live request volume bounded (e.g., IndiaMART 40/day, TradeIndia 100/day at starter values). No new dependencies.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Robots.txt / respectful crawling**: PASS. Depth and caps *reduce* request volume and never raise it above current per-target behavior unless configured; lazy pagination adds nothing to robots handling (robots check still gates every URL before fetch, exactly as today).
- **Scope discipline (India-only, no LinkedIn)**: PASS. Cities list stays India-only; no new domains are introduced.
- **Credential security**: PASS. No secrets in the config; `tradeindia_code` values are public directory URL codes, not credentials.
- **Idempotent operations**: PASS. Persisted daily counters keyed by date make re-runs safe (second run respects first run's consumption); early-stop is deterministic per run.
- **Fail loudly**: PASS. Empty categories/cities logs an explicit warning; cap-reached and early-stop events are reported in the run summary.
- **JustDial mode separation**: PASS. JustDial's depth (`pages`), URL logic, and Phase 2 mode selection are untouched; `SCRAPE_FULL_PAGES` retirement does not touch JustDial.

*Re-check after Phase 1 design: re-verified in [Phase 1: data-model.md §Constitution](#). No violations found; Complexity Tracking table below remains empty.*

## Project Structure

### Documentation (this feature)

```text
specs/005-configurable-crawl-pagination/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # Feature specification (+ clarifications session 2026-07-31)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── targets-config-schema.md     # Exact targets.yaml schema + sample starter file
│   ├── start-url-expansion.md       # Cross-product generation logic
│   ├── pagination-early-stop.md     # Lazy pagination + "0 new listings" semantics
│   ├── daily-cap-counting.md        # Per-domain cap + enrichment counting
│   └── cron-workflow.md             # Exact workflow changes
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
config/
└── targets.yaml          # Renamed + restructured (was targets.yml)

src/
├── config.py             # load_full_config default -> config/targets.yaml; top-level getters
└── scraper/
    ├── targets.py        # expand_start_urls() + _build_source_url({code}) + enrichment cap checks
    ├── spider.py         # LeadSpider: lazy start_requests/parse, early-stop, per-target seen-set,
    │                     #   DomainRequestCounter counting all domain requests
    └── engine.py         # scrape_all_targets: unchanged entry (reads renamed config)

.github/workflows/
├── daily.yml             # cron '0 6 * * 1-5' kept; TARGETS_CONFIG -> targets.yaml; drop SCRAPE_FULL_PAGES
└── scrape.yml            # add TARGETS_CONFIG env to pipeline step

tests/
├── test_config.py        # schema/expansion tests (new)
└── test_spider.py        # update small_config fixture; early-stop + cap tests
```

**Structure Decision**: Single existing project; no new modules. URL expansion lives in `src/scraper/targets.py` (co-located with `_build_page_url`, which the new logic drives); config loading stays in `src/config.py`; spider behavior changes stay in `src/scraper/spider.py`. This matches the existing 003-spider-migration layout precedent and keeps blast radius to three source files plus workflows.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)* | | |

## Phase 0: Research — see [research.md](./research.md)

Key findings: IndiaMART city URL `https://dir.indiamart.com/{city}/{category}.html`; TradeIndia city URL `https://www.tradeindia.com/{city}/{category}-city-{code}.html` with per-city numeric codes that are NOT derivable from the slug (verified: new-delhi 228067, mumbai 207486, bengaluru 183339, pune 213577, hyderabad 196467, chennai 187278, kolkata 200579, ahmedabad 178823, jaipur 197559, surat 220891). All three page-URL builders append `?page={page}` for page > 1. `SCRAPE_FULL_PAGES` gate currently clamps depth (spider.py) — retired by this plan. Full reasoning in research.md.

## Phase 1: Design — see [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

- `contracts/targets-config-schema.md` — exact `targets.yaml` schema and the complete pre-populated sample starter file (all 10 categories, 10 cities with `tradeindia_code`, per-site `max_pages`/`max_requests_per_day`).
- `contracts/start-url-expansion.md` — `expand_start_urls()` pure function contract: deterministic cross-product order, label resolution, `{code}` formatting, empty-list behavior.
- `contracts/pagination-early-stop.md` — lazy pagination (page 1 in `start_requests`, next pages yielded from `parse`), `max_pages` default 10, exact "0 new listings" definition (run-local, per-target, normalized-name dedup), blocked-page handling.
- `contracts/daily-cap-counting.md` — `DomainRequestCounter` counting listing + enrichment requests; hard stop per domain; persistence across same-day runs; day-boundary reset.
- `contracts/cron-workflow.md` — exact `daily.yml`/`scrape.yml` diffs.

## Phase 2: Tasks — delegated to `/speckit.tasks` (not created by `/speckit.plan`)
