# Contract: daily-cap-counting

**Feature**: 005-configurable-crawl-pagination | **Spec**: [spec.md](../spec.md) FR-007, FR-008, SC-004, Edge Cases | **Date**: 2026-07-31

## 1. Counting scope (Q4 — ALL requests to a domain)

Every request to a domain increments the persisted daily counter:

| Source | Where it is issued |
|--------|--------------------|
| Paginated listing pages (IndiaMART, TradeIndia) | at yield time — page 1 in `start_requests`, pages 2+ in `parse` |
| JustDial eager pages | unchanged — counted per request as today, per-combo loop untouched (A1: JD accounting is out of scope and deferred to Phase 2, preserving SC-005) |
| TradeIndia detail-page enrichment | `on_close` → `src/scraper/targets.py:_enrich_from_detail_pages` (line ~322), before each detail fetch |
| IndiaMART httpx enrichment fallback | `on_close` → `src/scraper/targets.py:_enrich_indiamart_via_httpx` (line ~399), before each httpx fetch |

The cap is **request-count based**, not time-based: each `DomainRequestCounter.allowed()` call increments the persisted counter by exactly 1 and compares against the cap. It is orthogonal to the per-domain `download_delay`/`DOMAIN_DELAYS` throttle (a time-based rate limit applied by the scheduler), so the two never conflict. The cap key is the URL host (`source_url.split('/')[2]`, e.g. `dir.indiamart.com`), while the throttle key is the sid — both map 1:1 to a site (Findings U2/U3).

## 2. Enforcement — hard stop per domain (Q2)

- Before issuing ANY request to a domain, check `DomainRequestCounter.allowed(domain, cap)` where `cap = max_requests_per_day` from that site's `targets` entry.
- If a domain is exhausted:
  - no further listing pages for that domain are yielded (remaining combos skipped);
  - no further enrichment fetches for that domain are issued (skipped and logged as `cap-reached`);
  - other domains continue unaffected;
  - the run summary reports the cap was reached for that domain (FR-008).
- Raising the cap mid-day only unlocks remaining budget; counters already consumed stay consumed (spec Edge Case).

## 3. Persistence & day boundary

- State store unchanged: `data/request_counts.json`, keyed by date and domain, via the existing `DomainRequestCounter` (src/scraper/spider.py, ~line 154).
- A run on the same calendar day accounts for requests already consumed by earlier runs (spec Edge Case / User Story 3 Independent Test).
- A new calendar day resets the per-domain budgets (spec Edge Case).

## 4. Interaction with lazy pagination

Because pages are yielded lazily, the cap is checked at **every** yield point (page 1 in `start_requests`, each next page in `parse`) — this keeps cap accounting exactly 1 unit per page and preserves the hard-stop guarantee even when the cross-product far exceeds the cap (SC-004: verified at 100+ combinations). In the current eager model the cap is consumed once per combo regardless of page count; lazy pagination changes the unit to 1 per page request for IndiaMART/TradeIndia, which is the FR-008 "all requests" accounting and an intentional correction (Finding U2). JustDial keeps its current per-combo accounting (see §1) and is deferred to Phase 2.

## 5. Acceptance

- IndiaMART `max_requests_per_day: 40` + 100 combos → ≤ 40 IndiaMART requests that calendar day (spec User Story 3; SC-004).
- Mid-run exhaustion skips remaining IndiaMART combos; TradeIndia continues; summary notes the cap.
- A second same-day run issues none once the cap is consumed; next-day run resets.
- Enrichment work never pushes a domain past its cap (spec Edge Case).
