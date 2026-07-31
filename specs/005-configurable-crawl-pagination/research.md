# Phase 0 Research — Configurable Crawl Pagination & Targets Config

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-07-31

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| R1 | Rename `config/targets.yml` → `config/targets.yaml` and restructure to top-level `targets`, `categories`, `cities`, `url_templates`, `icp_categories`, `icp_cities` | FR-001/FR-002 require top-level keys; the spec assumption authorizes filename normalization; `TARGETS_CONFIG` env default updated in `src/config.py` so launch path is unchanged. |
| R2 | TradeIndia switches from the category-only template `https://www.tradeindia.com/manufacturers/{category}.html` to the city-scoped `https://www.tradeindia.com/{city}/{category}-city-{code}.html` | FR-003 requires the categories × cities cross-product for TradeIndia; the city-scoped URL is the verified format and the `{code}` suffix is per-city, not derivable, so it is stored in config. |
| R3 | `tradeindia_code` is a required per-city field used to format the TradeIndia template `{code}` placeholder | Verified across 10 cities (see Research Findings). The code is a directory URL code, publicly embedded in URLs; not a credential. |
| R4 | Pagination is lazy: `start_requests` yields only page 1 per category × city target; `parse` yields the next-page `Request` only when the page produced ≥1 *new* listing and `page < max_pages` | Enables early-stop without wasted requests; keeps cap accounting exact per page. |
| R5 | "0 new listings" = a page whose listings are all already seen for that exact (site, category_slug, city_slug) target in the current run, deduped by normalized company name (casefold + strip) | Matches the spec Assumption. Duplicate records still flow into `all_records` so Phase 5 dedup (a downstream concern) keeps its current semantics. |
| R6 | JustDial keeps its existing `pages` key, `entry_url`/probe logic, and mode-based flow untouched | FR-004/SC-005: this feature must not change JustDial's crawl depth or request count. |
| R7 | Per-target `max_pages` (default 10) applies to IndiaMART and TradeIndia only; the `SCRAPE_FULL_PAGES` environment gate is retired (no longer read) | FR-005 + clarification Q5: config value is the sole pagination control. |
| R8 | Daily cap counts ALL requests to a domain: paginated listing pages, detail-page enrichment (`_enrich_from_detail_pages`), and httpx enrichment (`_enrich_indiamart_via_httpx`) | FR-008 + clarification Q4. Enforced before each such request via `DomainRequestCounter.allowed(domain, cap)`. |
| R9 | Daily cap = hard stop per domain; counts persist in `data/request_counts.json` across same-day runs and reset on a new calendar day | FR-008 + clarification Q2; existing state store reused. |
| R10 | Cron stays `0 6 * * 1-5` (06:00 UTC = 11:30 IST weekdays) in `daily.yml`; both workflows' config env updated to `config/targets.yaml`; `SCRAPE_FULL_PAGES` env removed from `daily.yml` | FR-009 + clarification Q3; `scrape.yml` must not silently scrape 0 targets after the file rename. |

## URL Format Research (verified 2026-07-31)

### IndiaMART — city-scoped directory
```
https://dir.indiamart.com/{city}/{category}.html
```
Example: `dir.indiamart.com/delhi/manufacturing-software.html`. City and category use the site's own slug style (e.g. `new-delhi`, `software-development-services`). Pagination: `?page={page}` for page > 1 (existing `_im_page_url`).

### TradeIndia — city-scoped directory with numeric city code
```
https://www.tradeindia.com/{city}/{category}-city-{code}.html
```
The `-city-{code}` suffix is required; the numeric code is per-city and independent of category. Verified codes for the starter city set:

| City slug (site label) | tradeindia_code | Verified URL pattern |
|------------------------|-----------------|----------------------|
| new-delhi (`new-delhi`) | `228067` | `/new-delhi/textile-fabrics-city-228067.html` |
| mumbai (`mumbai`) | `207486` | `/mumbai/software-city-207486.html` |
| bengaluru (`bengaluru`) | `183339` | `/bengaluru/software-city-183339.html` |
| pune (`pune`) | `213577` | `/pune/engineering-consulting-services-city-213577.html` |
| hyderabad (`hyderabad`) | `196467` | `/hyderabad/software-development-city-196467.html` |
| chennai (`chennai`) | `187278` | `/chennai/software-city-187278.html` |
| kolkata (`kolkata`) | `200579` | `/kolkata/software-city-200579.html` |
| ahmedabad (`ahmedabad`) | `178823` | `/ahmedabad/software-development-city-178823.html` |
| jaipur (`jaipur`) | `197559` | `/jaipur/software-city-197559.html` |
| surat (`surat`) | `220891` | `/surat/payroll-software-city-220891.html` |

Note: TradeIndia's Bangalore slug is `bengaluru`, so the city's `tradeindia` label must be `bengaluru` (not `bangalore`). Pagination: `?page={page}` for page > 1 (existing `_ti_page_url`).

### JustDial
Not expanded by this feature (FR-004). URL generation and depth remain governed by Phase 2 mode logic; `?page={page}` pagination continues unchanged.

## Current-Implementation Anchors (verified)

- `src/scraper/spider.py`: `LeadSpider.start_requests` (line ~406) builds per-site page requests; `_build_source_url` (line ~282) formats the template via `_site_label` (line ~247); the `SCRAPE_FULL_PAGES` gate currently clamps pagination depth and is retired by R7; `DomainRequestCounter` (~line 154) enforces the daily cap at start-request time; `parse` (line ~539) is the response callback; enrichment runs in `on_close` via `src/scraper/targets.py`.
- `src/scraper/targets.py`: page builders `_jd_page_url`/`_im_page_url`/`_ti_page_url` (lines ~469/475/481) dispatch from `_build_page_url` (line ~506); enrichment `_enrich_from_detail_pages` (line ~322), `_enrich_indiamart_via_httpx` (line ~399).
- `src/config.py`: `load_full_config()` defaults to `TARGETS_CONFIG` or `config/targets.yml`; `get_icp_categories(config)`/`get_icp_cities(config)` read the ICP allowlists (must read top-level keys after R1).
- `.github/workflows/daily.yml`: cron `0 6 * * 1-5`, env `TARGETS_CONFIG: config/targets.yml`, env `SCRAPE_FULL_PAGES`.
- `.github/workflows/scrape.yml`: cron `0 6 * * 1`, no `TARGETS_CONFIG` (uses default — must be updated after rename).
- `tests/test_spider.py`: `small_config` fixture mocks `load_full_config` with 1 category × 1 city + `url_templates`; pagination/cap tests reference the current eager model and need updating for lazy pagination.

## Risks

- **TradeIndia code drift**: directory codes are stable but could change if TradeIndia re-indexes cities. Mitigated by storing codes in one config file (single point of maintenance) and by the quickstart verification procedure (spot-check a generated URL before long runs).
- **Lazy pagination regression on existing pagination tests**: tests that assert all page Requests are yielded up front must be rewritten to the lazy contract. Mitigated by keeping the pure URL logic (`_build_page_url`) unchanged and only moving the yield timing.
- **Silent 0-target scrape in `scrape.yml`** after the rename: mitigated by adding `TARGETS_CONFIG: config/targets.yaml` to `scrape.yml` in the same change.
