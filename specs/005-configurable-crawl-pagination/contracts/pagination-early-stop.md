# Contract: pagination-early-stop

**Feature**: 005-configurable-crawl-pagination | **Spec**: [spec.md](../spec.md) FR-005, FR-006, FR-004, SC-002, SC-003, SC-005 | **Date**: 2026-07-31

## 1. Model

Pagination is **lazy and early-stopped** for IndiaMART and TradeIndia targets:

- `start_requests` yields only **page 1** per category × city target (contract [start-url-expansion.md](./start-url-expansion.md)).
- `parse` yields the next-page `Request` **only if all of**:
  1. the current page produced **≥ 1 new listing** for that target (definition below),
  2. `page < max_pages` (per-target config, default 10),
  3. the domain's daily cap still allows the request (see [daily-cap-counting.md](./daily-cap-counting.md)).
- If any condition fails, no further page is requested for that target (early-stop). Other targets continue.

JustDial: depth is unchanged at the configured level. The `SCRAPE_FULL_PAGES` retirement (FR-005) restores JustDial to its configured `pages` (3) and does not exempt it; the Phase 2 baseline is the configured value, not the gate-clamped value (SC-005). JustDial keeps its existing eager `pages` loop and Phase 2 mode logic (FR-004/SC-005); this contract does not apply to it.

## 2. "0 new listings" — exact semantics (spec Assumption + Edge Case)

- Scope: the current run only, per target key `(site, category_slug, city_slug)`.
- Novelty test: a listing is "new" if its normalized company name has not been seen for that target in this run. Normalization: `name.casefold().strip()` (fallback: dedup key already extracted by the parser).
- Per-target seen-set: `dict[tuple[str, str, str], set[str]]` on the spider instance, populated as pages are parsed.
- A page is "0 new listings" when **every** listing on it was already in the per-target seen-set.
- **Records still flow through**: duplicate listings are NOT dropped at this point — they continue into `all_records` exactly as today so Phase 5 dedup (a downstream concern) keeps its semantics. The seen-set only decides whether to request the next page.
- **Blocked/errored pages are NOT "0 new"**: they go through the existing retry/block/proxy-rotation handling first; early-stop triggers only on a genuinely empty (parsed, non-blocked) page (spec Edge Case).

## 3. Page URL construction

Reuse the existing pure builder `_build_page_url(parser_name, base_url, page)` in `src/scraper/targets.py` (line ~506), which dispatches to `_jd_page_url`/`_im_page_url`/`_ti_page_url` — all append `?page={page}` for page > 1. The next-page `Request` is built with the same session kwargs as today (wait_selector dropped for page > 1, per existing behavior) and `page+1` / `max_pages` carried in `meta`, and it MUST also carry `sid=SID_BY_NAME[site]` plus the same `_make_session_kwargs(sid, ...)` session kwargs as page 1, so `DOMAIN_DELAYS` per-domain throttling and the stealth/plain session split continue to apply across all yielded pages (Finding U1). The next-page request relies on the per-domain robots cache established by page 1 — no per-page robots re-check, matching current behavior (Finding U6). For IndiaMART/TradeIndia, `meta["pages_total"]` carries `max_pages`; JustDial continues to carry its `pages` value (Finding U5).

## 4. `SCRAPE_FULL_PAGES` retirement (FR-005 / Q5)

- The env gate that currently clamps pagination in `LeadSpider.start_requests` is removed; the config `max_pages` (default 10) applies unconditionally.
- A set-but-stale `SCRAPE_FULL_PAGES` variable is ignored (spec Edge Case). Remove it from `.github/workflows/daily.yml` env.

## 5. Acceptance

- A target with `max_pages: 10` requests at most 10 pages (SC-002).
- A target whose results end on page 3 issues zero requests for pages 4–10 (SC-003; spec User Story 2 Independent Test).
- A page whose listings all repeat earlier pages of the same target triggers early-stop (spec Edge Case).
- Empty `categories`/`cities` → no combos, warning logged, run continues (spec Edge Case).
