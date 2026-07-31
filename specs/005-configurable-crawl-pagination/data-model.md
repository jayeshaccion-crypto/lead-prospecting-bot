# Phase 1 Data Model — Configurable Crawl Pagination & Targets Config

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Contracts**: [contracts/](./contracts/) | **Date**: 2026-07-31

## Entities

### TargetsConfig (config/targets.yaml)

Loaded by `src/config.py` `load_full_config()` (default path `config/targets.yaml`). Shape — full schema and sample in [contracts/targets-config-schema.md](./contracts/targets-config-schema.md).

| Key | Type | Default | Used by |
|-----|------|---------|---------|
| `targets` | `list[Target]` | — | Spider session setup, caps, `max_pages` |
| `categories` | `list[Category]` | starter 10 | Cross-product URL expansion |
| `cities` | `list[City]` | starter 10 | Cross-product URL expansion |
| `url_templates` | `dict[str, str]` | per-site | `_build_source_url` / `expand_start_urls` |
| `icp_categories` | `list[str]` | `[]` | `get_icp_categories()` (Phase 6 scoring only) |
| `icp_cities` | `list[str]` | `[]` | `get_icp_cities()` (Phase 6 scoring only) |

### Category

| Field | Type | Example |
|-------|------|---------|
| `slug` | `str` | `software-development` |
| `labels` | `dict[str, str]` | `{justdial: "IT-Services", indiamart: "software-development-services", tradeindia: "software-development"}` |

### City

| Field | Type | Example |
|-------|------|---------|
| `slug` | `str` | `new-delhi` |
| `labels` | `dict[str, str]` | `{justdial: "Delhi", indiamart: "new-delhi", tradeindia: "new-delhi"}` |
| `tradeindia_code` | `str` | `228067` (required; used only by the TradeIndia template `{code}` placeholder) |

### Target

Per-site crawl configuration. IndiaMART/TradeIndia use `max_pages` (default 10); JustDial keeps its existing `pages` key and is not changed (FR-004/SC-005).

| Field | Type | Default | Scope |
|-------|------|---------|-------|
| `name` | `str` | — | all |
| `enabled` | `bool` | — | all |
| `parser` | `str` | — | all |
| `max_pages` | `int` | `10` | IndiaMART, TradeIndia (sole pagination control, FR-005) |
| `pages` | `int` | `3` | JustDial only (unchanged) |
| `max_requests_per_day` | `int` | — | all (FR-007/FR-008) |
| `fetch_kwargs` | `dict` | — | all (unchanged) |

### CrawlCombo

Generated value — the unit of a start URL. Constructed by `expand_start_urls()` (contract: [start-url-expansion.md](./contracts/start-url-expansion.md)).

| Field | Type | Meaning |
|-------|------|---------|
| `site` | `str` | `indiamart` or `tradeindia` |
| `category_slug` | `str` | source category slug |
| `city_slug` | `str` | source city slug |
| `url` | `str` | fully formatted page-1 URL |

The target key for early-stop dedup and per-target accounting is the triple `(site, category_slug, city_slug)`.

### DailyCapState (data/request_counts.json)

Existing `DomainRequestCounter` store. Unchanged JSON shape: keyed by date and domain, holding integer request counts for the current calendar day. Behavior extensions per FR-008:
- every domain request increments the counter — listing pages (at yield time, both in `start_requests` and `parse`) and enrichment fetches (in `on_close`, before each detail-page/httpx fetch);
- `allowed(domain, cap)` gates each request; when a domain is exhausted, that domain is hard-stopped (no further listing pages, no further enrichment) while other domains continue;
- counters persist across same-day runs (second run sees first run's consumption) and reset when the stored date != today.

## Flow

1. `src/config.py:load_full_config()` → TargetsConfig (top-level keys; `get_icp_categories`/`get_icp_cities` read `icp_categories`/`icp_cities`).
2. `src/scraper/targets.py:expand_start_urls(categories, cities, url_templates)` → `list[CrawlCombo]` (IndiaMART + TradeIndia only; category-major × city-minor deterministic order).
3. `LeadSpider.start_requests()` → for each enabled site, for each combo: cap check → robots check → proxy resolution → yield page-1 `Request` (lazy — no page 2+ up front). JustDial path unchanged.
4. `LeadSpider.parse()` → extract records; compute per-target new count (normalized-name dedup); record all records into `all_records`; if `new > 0` and `page < max_pages` and cap allows → yield next-page `Request`; else stop that target.
5. `LeadSpider.on_close()` → enrichment (TradeIndia detail pages, IndiaMART httpx) with per-fetch cap check; cap-exhausted enrichment skipped and logged.
6. Run summary reports per-domain: requests made, cap reached (bool), early-stopped targets.

## Constitution Re-check (post-Phase 1)

All gates still PASS (see [plan.md](./plan.md) Constitution Check). No violations; Complexity Tracking table remains empty. No new persistence beyond the existing `request_counts.json`; no new network-facing behavior beyond config-controlled bounds.
