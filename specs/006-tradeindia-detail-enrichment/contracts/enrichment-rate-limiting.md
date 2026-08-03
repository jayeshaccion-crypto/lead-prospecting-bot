# Contract: Detail-Enrichment Rate-Limiting (Phase-1 per-domain cap)

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](../spec.md)

## Requirement (FR-007 / req #4)

The new detail-page requests must respect the same per-domain daily request budget as the rest of the crawl (the Phase-1 hard cap, FR-008 of feature 005). Enabling enrichment must never let a domain exceed its daily budget.

## Verified existing wiring (no re-architecture)

- `LeadSpider.on_close` (`src/scraper/spider.py:880`) already:
  1. builds `needy = [ (i, u) for i, u in detail_urls if i < len(all_records) and not (all_records[i].phone and all_records[i].email) ]`;
  2. `cap_guard = self._cap_guard_for("www.tradeindia.com", daily_cap)` when `daily_cap` is set;
  3. truncates to `needy[:max_detail]` where `max_detail = fetch_kwargs.get("max_detail_pages", 20)`;
  4. calls `_enrich_from_detail_pages(session=None, all_records, needy[:max_detail], timeout, cap_guard)`.
- `_enrich_from_detail_pages` (`src/scraper/targets.py:323`) consumes ONE budget unit per detail-page fetch via `cap_guard()`, applies a 0.5s wait per fetch, and stops further fetches when the guard denies ("Daily cap reached — skipping remaining detail-page enrichment").

## Consequences

- Every TradeIndia detail-page request already counts against the same per-domain daily budget as pagination (no unbounded growth).
- The per-run slot cap (default 20) bounds requests within a run; the per-domain daily guard bounds across runs within the same calendar day.
- This feature adds the detail URL (contract [detail-page-url.md](./contracts/detail-page-url.md)) and per-field extraction (contract [enrichment-extraction.md](./contracts/enrichment-extraction.md)); both plug into the existing on_close step. No change to the cap/counter machinery.

## Acceptance / tests

- With a `max_requests_per_day=2` on a TradeIndia target and >2 needy records, total TradeIndia detail requests ≤ 2; once the guard denies, enrichment skips and is logged.
- Fill-rate reporting (`phone=X/N, email=Y/N, website=Z/N`) is recomputed after enrichment in `on_close` (already present).