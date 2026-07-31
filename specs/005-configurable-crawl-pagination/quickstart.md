# Quickstart — Configurable Crawl Pagination & Targets Config

**Feature**: 005-configurable-crawl-pagination | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-07-31

## 1. Scope of validation

All validations below run offline (unit tests) or via workflow inspection — no live crawl is required. They map 1:1 to the spec's Success Criteria and Independent Tests.

## 2. Configuration

- `config/targets.yaml` — the pre-populated starter file (10 categories × 10 cities, per-site `max_pages`/`max_requests_per_day`, TradeIndia `tradeindia_code` per city). Schema and sample: [contracts/targets-config-schema.md](./contracts/targets-config-schema.md).
- `TARGETS_CONFIG` env: `config/targets.yaml` (both workflows).

## 3. Validation scenarios

| # | Scenario | How to verify | Criterion |
|---|----------|---------------|-----------|
| V1 | Cross-product expansion: 2 categories × 2 cities → 4 IndiaMART + 4 TradeIndia combos; 10×10 → 100+100 | Unit test on `expand_start_urls`; run summary logs combo count | SC-001, US1 Independent Test |
| V2 | TradeIndia URL correctness | Unit assert: `https://www.tradeindia.com/new-delhi/software-development-city-228067.html`; Bangalore → `bengaluru/...-city-183339.html` | FR-003, R2/R3 |
| V3 | `max_pages` default 10, sole control | Test spider with `SCRAPE_FULL_PAGES` set → still ≤ 10 pages; config `max_pages: 5` → ≤ 5 | FR-005, SC-002, Q5 |
| V4 | Early-stop on 0 new listings | Feed a target 3 pages of listings where page 3 repeats page 2 → pages 4–10 never requested; other targets continue | FR-006, SC-003 |
| V5 | Blocked/errored page ≠ early-stop | Blocked response → existing retry/block path, no early-stop signal | US2-AS4, Edge Case |
| V6 | Daily cap hard stop per domain | IndiaMART cap 40, 100 combos → ≤ 40 IndiaMART requests; TradeIndia unaffected; summary reports cap-reached | FR-008, SC-004, US3 |
| V7 | Enrichment counted against cap | Detail-page/httpx enrichment exhausts remaining budget → enrichment stops and logs cap-reached | FR-008/Q4, Edge Case |
| V8 | Same-day persistence + day reset | Run twice same day → second run respects consumed budget; mock date rollover → budget resets | FR-008, US3-AS3/AS4 |
| V9 | JustDial depth unchanged | `pages: 3` + JD mode logic untouched; JD request count/depth equal to Phase 2 baseline | FR-004, SC-005 |
| V10 | Cron present | Inspect `daily.yml`: `cron: '0 6 * * 1-5'` + `workflow_dispatch`; grep workflows for `targets.yml`/`SCRAPE_FULL_PAGES` (must be absent) | FR-009, SC-006, US4 |
| V11 | Empty lists fail loudly | Config with empty `categories` → warning logged, no combos, run continues | Edge Case |
| V12 | ICP allowlists inert | `icp_categories`/`icp_cities` populated → no crawl/scoring behavior change in this phase | FR-002, US1-AS2 |

## 4. Test commands

```bash
# Full offline suite
python -m pytest tests/ -q

# Targeted
python -m pytest tests/test_config.py tests/test_spider.py -q
```

## 5. Post-change hygiene

- Confirm no references to `config/targets.yml` or `SCRAPE_FULL_PAGES` remain in `.github/workflows/`, `src/`, or `run.py` (grep).
- Spot-check one generated TradeIndia URL from the run log against the browser (codes are stable but vendor-owned; see research.md Risks).
- Re-run the constitution checks (robots compliance, India-only scope, credential safety) as listed in plan.md — all must remain PASS.
