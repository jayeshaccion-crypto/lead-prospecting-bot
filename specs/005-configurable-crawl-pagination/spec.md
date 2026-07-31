# Feature Specification: Configurable Crawl Pagination & Targets Config

**Feature Branch**: `005-configurable-crawl-pagination`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "Add config/targets.yaml containing: categories: [5-10 IT/software-adjacent categories], cities: [5-10 major Indian cities], icp_categories: [], icp_cities: [] (optional allowlists, used later in Phase 6 scoring). Generate start_urls for IndiaMART and TradeIndia as the cross-product of categories x cities (JustDial's URL generation is governed separately by Phase 2's mode logic — do not expand JustDial's crawl depth in this phase). Increase pages per target up to a configurable max (default 10), with early-stop once a page returns 0 new listings. Add a per-domain daily request cap (config value, e.g. IndiaMART max 40/day) enforced regardless of how large the category/city list grows. Add a daily cron trigger to the GitHub Actions workflow."

## Clarifications

### Session 2026-07-31

- Q1: Pre-populate the categories/cities lists with a starter set, or leave placeholders to fill in before the first live run? → A: Pre-populate with the existing 10 IT/software-adjacent categories and 10 major Indian cities already present in `config/targets.yml` — the pipeline works on the first run with no operator editing.
- Q2: Should the per-domain daily request cap be a hard stop or a soft warning? → A: Hard stop per domain — once a domain's daily budget is exhausted, no further requests are issued to that domain for the rest of the calendar day (other domains continue), and the run summary reports the cap was reached.
- Q3: What time should the daily cron use? → A: `0 6 * * 1-5` — 06:00 UTC (11:30 IST) on weekdays, matching the pipeline's existing scheduled workflow.
- Q4: Does the per-domain daily cap count all requests to a domain, or only paginated listing pages? → A: The cap counts all requests to the domain — paginated listing pages, detail-page enrichment, and the httpx enrichment fallback alike.
- Q5: Should the configurable max-pages replace the existing `SCRAPE_FULL_PAGES` gate, or does the env gate still clamp pagination? → A: The config value becomes the sole pagination control; the `SCRAPE_FULL_PAGES` environment gate is retired, so the configured max (default 10) always applies.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Category and City Expansion Config (Priority: P1)

An operator opens a single configuration file and edits the list of IT/software-adjacent categories (5-10) and major Indian cities (5-10). The pipeline reads that file and, for IndiaMART and TradeIndia, generates one start URL for every category × city combination — so 10 categories × 10 cities produce 100 start URLs per site, with no per-combination code changes needed when the lists grow.

**Why this priority**: The category and city lists are the fundamental driver of crawl breadth. Everything else in this feature (pagination depth, caps) governs how those start URLs are consumed. Getting the config contract right first makes the remaining behavior testable.

**Independent Test**: Point the pipeline at a config listing 2 categories and 2 cities and confirm exactly 4 IndiaMART and 4 TradeIndia start URLs are produced; then grow the lists and confirm the count grows as the cross-product, with no code change.

**Acceptance Scenarios**:

1. **Given** a config with N categories and M cities, **When** the pipeline starts a crawl, **Then** IndiaMART and TradeIndia each receive N×M start URLs (one per category × city combination).
2. **Given** the optional ICP allowlists (`icp_categories`, `icp_cities`) are empty, **When** scoring runs, **Then** no category or city contributes ICP-match points (the allowlists have no effect until populated in a later phase).
3. **Given** the categories list contains only IT/software-adjacent entries (5-10) and cities are major Indian cities, **When** the config is loaded, **Then** the pipeline accepts and uses them without modification.

---

### User Story 2 - Configurable Pagination with Early Stop (Priority: P2)

An operator sets a maximum number of pages per target (configurable, default 10). The crawler requests pages 1..max for each IndiaMART and TradeIndia category × city target, but stops requesting further pages for a target as soon as a page returns 0 new listings — so effort is not wasted on paginating past the end of results.

**Why this priority**: Pagination depth directly determines data completeness and request volume. The early-stop keeps that volume proportional to what a directory actually has, which is what makes a large default (10) safe to adopt.

**Independent Test**: Configure max pages = 10 for IndiaMART, seed a target whose results end on page 3, and confirm pages 4-10 are never requested for that target while other targets continue.

**Acceptance Scenarios**:

1. **Given** a target with max pages set to 10, **When** the crawl runs, **Then** no more than 10 pages are requested for that target.
2. **Given** a target whose page P returns 0 new listings, **When** the crawl runs, **Then** pages P+1 through max are not requested for that target.
3. **Given** JustDial is enabled for crawling (residential mode from Phase 2), **When** the crawl runs, **Then** JustDial's crawl depth is unchanged by this feature and remains governed by Phase 2's mode logic.
4. **Given** a page returns a blocked or errored body rather than a genuinely empty result, **When** the crawl runs, **Then** it is handled by existing retry/block rules and does not trigger early-stop.

---

### User Story 3 - Per-Domain Daily Request Caps (Priority: P3)

An operator configures a maximum number of requests per calendar day for each domain (e.g., IndiaMART max 40/day). The cap is a hard ceiling: no matter how many categories and cities are configured, once a domain's daily budget is exhausted, no further requests are issued to that domain for the rest of the day, and the run reports that the cap was reached.

**Why this priority**: This protects the pipeline from runaway request volume as the category/city list grows, and it preserves the proxy/rate budget for the directories. It is a guardrail rather than a data-delivery path, hence lower than the expansion stories.

**Independent Test**: Set IndiaMART's cap to a small value, configure a large category × city list (so the cross-product far exceeds the cap), run twice on the same day, and confirm total IndiaMART requests never exceed the cap and the second run respects the first run's consumed budget.

**Acceptance Scenarios**:

1. **Given** IndiaMART's daily cap is 40 and the category × city cross-product exceeds 40 combinations, **When** the crawl runs, **Then** no more than 40 IndiaMART requests are issued that calendar day.
2. **Given** a domain's cap is reached mid-run, **When** further combinations for that domain come up, **Then** they are skipped, other domains continue unaffected, and the run summary states the cap was reached for that domain.
3. **Given** a second run on the same calendar day, **When** it starts, **Then** it accounts for requests already consumed that day and issues none once the cap is exhausted.
4. **Given** a new calendar day begins, **When** the pipeline runs, **Then** the per-domain budget resets.

---

### User Story 4 - Daily Scheduled Run (Priority: P4)

The pipeline runs automatically on a weekday cron schedule (06:00 UTC / 11:30 IST) in GitHub Actions, in addition to being triggerable manually, so fresh leads are collected without an operator starting each run by hand.

**Why this priority**: Automation is the point of a scheduled pipeline, but it depends on the crawl behavior above being safe (capped and early-stopped). It is the last slice because it is trivial once the crawl is bounded.

**Independent Test**: Inspect the workflow and confirm a daily cron schedule is present alongside manual dispatch; optionally trigger `workflow_dispatch` to confirm the job runs on demand.

**Acceptance Scenarios**:

1. **Given** the scheduled workflow, **When** the weekday cron time arrives (06:00 UTC / 11:30 IST), **Then** the pipeline runs automatically without manual intervention.
2. **Given** an operator triggers a manual run, **When** dispatch is requested, **Then** the pipeline runs on demand even between scheduled times.

---

### Edge Cases

- What happens when the categories or cities list is empty? → No start URLs are generated for that site and an explicit warning is logged; the run continues with whatever targets are valid.
- What happens when a page is blocked or errors instead of returning 0 listings? → Existing retry/block handling applies (including proxy rotation); early-stop is triggered only by a genuinely empty page.
- What happens when a page returns listings but all of them were already collected earlier in the run? → They are counted as 0 *new* listings for that target, so early-stop still applies.
- What happens when the daily cap is reached before all category × city combinations are visited? → The remaining combinations are skipped for that domain and the summary reports the cap was reached.
- What happens when enrichment/detail-page work would push a domain past its cap? → It counts against the cap like any other request to that domain; once exhausted, enrichment for that domain is skipped and logged as cap-reached.
- What happens across a day boundary (cap exhausted at 23:59, next run at 00:01)? → The new calendar day resets the per-domain budgets.
- What happens if an operator raises the cap mid-day? → The persisted counter still reflects requests already made; new headroom applies only to remaining budget.
- What happens when max pages is set higher than a directory actually has? → Early-stop prevents wasted requests once a page returns 0 new listings.
- What happens if the retired `SCRAPE_FULL_PAGES` variable is still set? → It is ignored; the configured per-target maximum page count (default 10) applies unconditionally.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The targets configuration MUST expose `categories` (5-10 IT/software-adjacent categories) and `cities` (5-10 major Indian cities) as the authoritative expansion lists, pre-populated with the current starter set of 10 categories and 10 cities.
- **FR-002**: The targets configuration MUST expose optional `icp_categories` and `icp_cities` allowlists, empty by default, reserved for use by a later-phase scoring step.
- **FR-003**: System MUST generate start URLs for IndiaMART and TradeIndia as the cross-product of categories × cities.
- **FR-004**: System MUST NOT expand JustDial's crawl depth as a result of this feature; JustDial's URL generation and pagination MUST remain governed by the separate Phase 2 mode logic.
- **FR-005**: The targets configuration MUST be the sole control of pagination depth, allowing a per-target maximum page count with a default of 10; the existing `SCRAPE_FULL_PAGES` environment gate MUST be retired so the configured maximum always applies.
- **FR-006**: System MUST stop requesting further pages for a category × city target once a page returns 0 new listings (early-stop).
- **FR-007**: The targets configuration MUST allow a per-domain daily request cap (e.g., IndiaMART max 40/day).
- **FR-008**: System MUST enforce each domain's daily request cap regardless of the size of the category × city cross-product, persisting counts across runs on the same calendar day. The cap MUST count all requests to the domain — paginated listing pages, detail-page enrichment, and the httpx enrichment fallback. Once a domain's cap is reached, System MUST issue no further requests to that domain for the rest of the calendar day (hard stop per domain); other domains MUST continue unaffected, and the run summary MUST report the cap was reached.
- **FR-009**: The GitHub Actions workflow MUST include a daily cron trigger (weekdays 06:00 UTC / 11:30 IST) in addition to manual dispatch.

### Key Entities *(include if feature involves data)*

- **Categories**: The 5-10 IT/software-adjacent verticals (e.g., software development, web design, cloud services) used to build search URLs for IndiaMART and TradeIndia.
- **Cities**: The 5-10 major Indian cities (e.g., New Delhi, Mumbai, Bangalore) used to build search URLs for IndiaMART and TradeIndia.
- **ICP Allowlists**: Optional category and city allowlists (`icp_categories`, `icp_cities`) that are empty by default and consumed by a later-phase scoring step when populated.
- **Target Limits**: Per-target configuration holding the maximum page count (default 10) and the per-domain daily request cap.
- **Daily Cap State**: The persisted per-domain request counts for the current calendar day, used to enforce caps across multiple runs on the same day.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For N categories × M cities, IndiaMART and TradeIndia each produce exactly N×M start URLs (verifiable from run logs and tests).
- **SC-002**: No target ever requests more pages than its configured maximum (default 10).
- **SC-003**: A target whose page P returns 0 new listings issues zero requests for pages P+1 through its maximum.
- **SC-004**: Total requests to any single domain — including detail-page enrichment and httpx enrichment — never exceed its configured daily cap on a single calendar day, even when the category × city cross-product exceeds 100 combinations.
- **SC-005**: JustDial's configured crawl depth (`pages`) and Phase 2 mode selection are unchanged; the `SCRAPE_FULL_PAGES` retirement restores each target to its configured depth, and JustDial's baseline is its configured `pages` value (3), not the gate-clamped value.
- **SC-006**: The scheduled workflow triggers automatically on weekdays at 06:00 UTC (11:30 IST) without manual intervention.

## Assumptions

- "targets.yaml" refers to the existing targets configuration file (currently `config/targets.yml`, the default target of `TARGETS_CONFIG`); restructuring it to expose the requested top-level keys and normalizing the filename are resolved at planning without changing how the pipeline is launched.
- "0 new listings" means a page that yields no listings that were not already collected for that category × city target during the current run (i.e., deduplicated against earlier pages of the same target).
- The default maximum page count of 10 applies to IndiaMART and TradeIndia only; JustDial keeps its existing configured depth, which Phase 2 mode logic governs.
- The configurable maximum page count is the sole pagination control; the `SCRAPE_FULL_PAGES` environment gate is retired and no longer clamps depth (per clarification Q5).
- The "Phase 2 baseline" in SC-005 refers to JustDial's configured `pages` value (3); the `SCRAPE_FULL_PAGES` environment gate was a development-time clamp applied to all sites, and its retirement restores each target to its configured depth — JustDial is not exempted from the retirement, and its configured depth and Phase 2 mode logic are unchanged.
- The per-domain daily request cap persists per calendar day in the existing daily state store and resets at the start of a new calendar day.
- The categories and cities lists are pre-populated with the existing starter set of 10 categories and 10 cities, so the pipeline is runnable without operator edits (per clarification Q1).
- The daily cap is enforced as a hard stop per domain — other domains continue after one domain exhausts its budget (per clarification Q2).
- The daily cap counts every request to a domain — paginated listing pages, detail-page enrichment, and the httpx enrichment fallback (per clarification Q4).
- The daily cron trigger is confirmed as `0 6 * * 1-5` — weekdays 06:00 UTC (11:30 IST), matching the pipeline's existing scheduled workflow (per clarification Q3).
- Existing JustDial modes (residential / datacenter-ASN-test / no-proxy) are preserved unchanged; this feature neither increases JustDial crawl depth nor changes its mode selection.
- The ICP allowlists default to empty and MUST have no effect on scoring until a later phase populates them.
