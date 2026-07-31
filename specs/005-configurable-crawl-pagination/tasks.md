# Tasks: Configurable Crawl Pagination & Targets Config

**Input**: Design documents from `/specs/005-configurable-crawl-pagination/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test-file update tasks are included where the existing suite would break (fixture/schema change) or where the plan mandates new coverage (tests/test_config.py) and the spec's Independent Tests must be verifiable.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/`, `config/`, `.github/workflows/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Point the pipeline at the renamed config file so every subsequent task operates on `config/targets.yaml`.

- [X] T001 Update `load_full_config()` default path from `config/targets.yml` to `config/targets.yaml` in `src/config.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config getters read the new top-level keys required by ALL user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Update `get_icp_categories(config)` and `get_icp_cities(config)` to read top-level `icp_categories` / `icp_cities` keys (was `icp.categories` / `icp.cities`) in `src/config.py`

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Category and City Expansion Config (Priority: P1) 🎯 MVP

**Goal**: A single `config/targets.yaml` with top-level `categories`, `cities`, `icp_categories`, `icp_cities`, pre-populated with the starter 10 IT/software categories × 10 major Indian cities. IndiaMART and TradeIndia each receive exactly N×M start URLs (cross-product), one page-1 request per combination, with TradeIndia city URLs formatted using per-city `tradeindia_code` (`{code}` placeholder).

**Independent Test**: Point the pipeline at a config listing 2 categories and 2 cities and confirm exactly 4 IndiaMART and 4 TradeIndia start URLs are produced; grow the lists and confirm the count grows as the cross-product with no code change (SC-001; spec User Story 1 Independent Test; quickstart V1, V2).

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T003 [P] [US1] Add expansion unit tests in `tests/test_config.py`: 2×2 → 4+4 combos, 10×10 → 100+100; assert exact URLs `https://dir.indiamart.com/new-delhi/software-development-services.html` and `https://www.tradeindia.com/new-delhi/software-development-city-228067.html`; assert Bangalore uses `bengaluru` label + code 183339; assert empty `categories` returns `[]` with warning
- [X] T004 [P] [US1] Update `small_config` fixture in `tests/test_spider.py` to the new top-level schema (`categories`, `cities` with `tradeindia_code`, `url_templates`, `icp_categories`/`icp_cities`) so the existing suite loads the renamed structure

### Implementation for User Story 1

- [X] T005 [P] [US1] Create `config/targets.yaml` with the exact schema and pre-populated sample from `contracts/targets-config-schema.md` (10 categories with per-site labels, 10 cities with per-city `tradeindia_code`, per-site `max_pages` / `max_requests_per_day`, `url_templates` incl. TradeIndia `{code}`, empty `icp_categories`/`icp_cities`), then remove `config/targets.yml`
- [X] T006 [P] [US1] Implement `CrawlCombo` dataclass and pure function `expand_start_urls(categories, cities, url_templates, sites=("indiamart", "tradeindia")) -> list[CrawlCombo]` per `contracts/start-url-expansion.md` (category-major × city-minor deterministic order, per-site label resolution, TradeIndia `{code}` from `city["tradeindia_code"]`, empty-list warning, JustDial excluded) in `src/scraper/targets.py`
- [X] T007 [US1] Update `LeadSpider.__init__` to read top-level `categories`, `cities`, `url_templates` from `load_full_config()` (replacing the `expansion` reads) in `src/scraper/spider.py`
- [X] T008 [US1] Wire `expand_start_urls` into `start_requests`: for each enabled IndiaMART/TradeIndia combo resolve `sid = SID_BY_NAME[combo.site]`, run the gates in the current code order (robots → cap → proxy — robots first so disallowed combos never consume the cap), and yield the page-1 `Request` carrying `sid=` plus `_make_session_kwargs(sid, ...)` session kwargs (so `DOMAIN_DELAYS` throttling and the stealth/plain session split keep applying across the expanded set); exactly N×M page-1 requests per site; JustDial request flow unchanged in `src/scraper/spider.py`

**Checkpoint**: User Story 1 complete - config contract + cross-product start URLs working and independently testable (SC-001)

---

## Phase 4: User Story 2 - Configurable Pagination with Early Stop (Priority: P2)

**Goal**: The configured `max_pages` (default 10) is the sole pagination control; `SCRAPE_FULL_PAGES` is retired. Pagination is lazy: `parse` requests the next page for a category × city target ONLY when the current page produced ≥1 *new* listing (run-local, per-target, normalized-name dedup), the page count is below `max_pages`, and the domain cap allows it.

**Independent Test**: Configure `max_pages: 10` for IndiaMART, seed a target whose results end on page 3, and confirm pages 4-10 are never requested for that target while other targets continue (SC-002/SC-003; spec User Story 2 Independent Test; quickstart V3, V4, V5).

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T009 [P] [US2] Add/update pagination tests in `tests/test_spider.py`: no target exceeds its `max_pages`; a page of all-duplicate listings stops pagination; a blocked/errored page does NOT trigger early-stop; set-but-stale `SCRAPE_FULL_PAGES` is ignored

### Implementation for User Story 2

- [X] T010 [US2] Remove the `SCRAPE_FULL_PAGES` gate so `max_pages` (default 10) applies unconditionally in `start_requests` in `src/scraper/spider.py`; the gate is retired for ALL sites — JustDial is restored to its configured `pages` (3), per the "config value = baseline" decision (SC-005; contracts/pagination-early-stop.md §1)
- [X] T011 [US2] Implement lazy pagination + early-stop: `start_requests` yields page-1 only; `parse` maintains per-target seen-set `dict[tuple[str, str, str], set[str]]` keyed `(site, category_slug, city_slug)`, normalizes company names (`casefold().strip()`), passes duplicate records through to `all_records` unchanged, and yields the next-page `Request` (via existing `_build_page_url`, wait_selector dropped for page > 1, carrying `sid=SID_BY_NAME[site]` + `_make_session_kwargs` session kwargs so per-domain throttling continues, and `meta["pages_total"]=max_pages`) only when new>0 AND page < `max_pages` AND cap allows, else stops that target in `src/scraper/spider.py`

**Checkpoint**: User Story 2 complete - bounded depth with early-stop, independently testable (SC-002, SC-003)

---

## Phase 5: User Story 3 - Per-Domain Daily Request Caps (Priority: P3)

**Goal**: Every request to a domain — paginated listing pages, TradeIndia detail-page enrichment, and the IndiaMART httpx enrichment fallback — counts against `max_requests_per_day`. The cap is a hard stop per domain (other domains continue), persisted across same-day runs and reset on a new calendar day.

**Independent Test**: Set IndiaMART's cap to a small value, configure a category × city list that far exceeds the cap, run twice on the same day, and confirm total IndiaMART requests never exceed the cap and the second run respects the first run's consumed budget (SC-004; spec User Story 3 Independent Test; quickstart V6, V7, V8).

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T012 [P] [US3] Add/update cap tests in `tests/test_spider.py`: hard stop per domain (IndiaMART exhausted → TradeIndia continues); enrichment counts against the cap; second same-day run issues none once consumed; day boundary resets budget

### Implementation for User Story 3

- [X] T013 [US3] Add a `DomainRequestCounter.allowed(domain, cap)` check with the site's `max_requests_per_day` at every page yield point (page-1 in `start_requests`, next pages in `parse`); when denied for a domain, stop yielding that domain's pages while other domains continue in `src/scraper/spider.py`
- [X] T014 [P] [US3] Add a cap-guard callable parameter to `_enrich_from_detail_pages` and `_enrich_indiamart_via_httpx` in `src/scraper/targets.py`; when the guard denies a fetch, skip it and log `cap-reached` for the domain
- [X] T015 [US3] Wire the cap-guard into `on_close` enrichment calls (TradeIndia detail pages + IndiaMART httpx) and add per-domain cap-reached reporting to the run summary in `src/scraper/spider.py`

**Checkpoint**: User Story 3 complete - daily volume bounded regardless of cross-product size (SC-004)

---

## Phase 6: User Story 4 - Daily Scheduled Run (Priority: P4)

**Goal**: The GitHub Actions workflow runs automatically on weekdays at `0 6 * * 1-5` (06:00 UTC / 11:30 IST) in addition to manual dispatch, and both workflows point at the renamed config file.

**Independent Test**: Inspect the workflow and confirm a daily cron schedule is present alongside manual dispatch; optionally trigger `workflow_dispatch` to confirm the job runs on demand (SC-006; spec User Story 4 Independent Test; quickstart V10).

### Implementation for User Story 4

- [X] T016 [US4] Update `daily.yml` per `contracts/cron-workflow.md`: retain `schedule.cron: '0 6 * * 1-5'` and `workflow_dispatch`; change env `TARGETS_CONFIG` to `config/targets.yaml`; remove the `SCRAPE_FULL_PAGES` env entry in `.github/workflows/daily.yml`
- [X] T017 [P] [US4] Update `scrape.yml`: add env `TARGETS_CONFIG: config/targets.yaml` to the pipeline step; remove the `SCRAPE_FULL_PAGES` env entry in `.github/workflows/scrape.yml`

**Checkpoint**: User Story 4 complete - automated weekday runs on the new config

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verification and hygiene across all user stories

- [X] T018 Run the full offline suite and fix regressions: `python -m pytest tests/ -q`
- [X] T019 Run `quickstart.md` validation scenarios V1-V12 and confirm each maps to a green check
- [X] T020 [P] Grep hygiene: confirm no references to `config/targets.yml` or `SCRAPE_FULL_PAGES` remain in `.github/workflows/`, `src/`, or `run.py`
- [X] T021 [P] Update any docs/README references to the old `config/targets.yml` path

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001) completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational (T002) completion
  - US2, US3, US4 can proceed in parallel with US1 (see User Story Dependencies)
  - Or sequentially in priority order (US1 → US2 → US3 → US4)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational - Depends on US1 only for `max_pages` key + page-1 start requests already existing in `start_requests` (T008); code touches the same `parse` path but is otherwise independent
- **User Story 3 (P3)**: Can start after Foundational - Depends on US1 only for `max_requests_per_day` key; `DomainRequestCounter` and cap enforcement already exist and are extended, not created
- **User Story 4 (P4)**: Can start after Foundational - Independent of US1-US3 except it must NOT complete before T001 (config rename) lands, since the env points at the new file

### Within Each User Story

- Tests (where included) MUST be written and FAIL before implementation
- Config/schema before code
- Pure function (expand_start_urls) before integration (start_requests)
- Story complete before moving to next priority

### Parallel Opportunities

- Phase 1 + 2 are sequential (both edit `src/config.py`)
- Once Foundational completes, all four user stories can start in parallel (if team capacity allows)
- Within US1: T003, T004, T005, T006 are all [P] (different files: `tests/test_config.py`, `tests/test_spider.py`, `config/targets.yaml`, `src/scraper/targets.py`); T007, T008 are sequential after them (same file `src/scraper/spider.py`)
- Within US2: T009 [P] (tests) vs T010/T011 (spider.py)
- Within US3: T012 [P] (tests), T013 (spider.py), T014 (targets.py) parallel; T015 sequential after T013+T014
- Within US4: T016 (daily.yml) and T017 (scrape.yml) are [P]
- Polish: T018, T020, T021 [P]

---

## Parallel Example: User Story 1

```bash
# Launch all [P] tasks for User Story 1 together:
Task: "Add expansion unit tests in tests/test_config.py"
Task: "Update small_config fixture in tests/test_spider.py"
Task: "Create config/targets.yaml per contracts/targets-config-schema.md"
Task: "Implement CrawlCombo + expand_start_urls in src/scraper/targets.py"

# Then, sequentially (both edit src/scraper/spider.py):
Task: "Update LeadSpider.__init__ to top-level keys"
Task: "Wire expand_start_urls into start_requests (page-1 yields)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002) (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (T003-T008)
4. **STOP and VALIDATE**: Test User Story 1 independently (quickstart V1, V2)
5. Deploy/demo if ready — config contract + 100×2 start URLs working

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently (bounded, early-stopped pagination)
4. Add User Story 3 → Test independently (daily caps)
5. Add User Story 4 → Test independently (scheduled runs)
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (T003-T008)
   - Developer B: User Story 2 (T009-T011) — after T008 lands
   - Developer C: User Story 3 (T012-T015) — after T005 lands
   - Developer D: User Story 4 (T016-T017)
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- Scope fidelity (constitution VIII): this feature touches ONLY `config/targets.yaml`, `src/config.py`, `src/scraper/targets.py`, `src/scraper/spider.py`, `.github/workflows/daily.yml`, `.github/workflows/scrape.yml`, `tests/test_config.py`, `tests/test_spider.py`, and docs. `src/scraper/engine.py`, JustDial crawl depth, and Phase 6 scoring are explicitly OUT of scope.
- JustDial semantics (analysis findings I1/A1): SC-005's "Phase 2 baseline" is JustDial's configured `pages` value (3), not the `SCRAPE_FULL_PAGES`-clamped value; the gate retirement restores configured depths for all sites (spec.md Assumptions). JustDial's per-combo cap accounting was fixed during code review (F1): each page request now consumes one `max_requests_per_day` unit, matching the per-request accounting of IndiaMART/TradeIndia (previously one unit per combo under-counted `pages` requests).
