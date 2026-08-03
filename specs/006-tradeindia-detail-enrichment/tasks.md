# Tasks: TradeIndia Detail-Page Enrichment

**Input**: Design documents from `/specs/006-tradeindia-detail-enrichment/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: No TDD/test tasks are requested; verification is by the independent-test criteria per story and the required `pytest` regression in Polish.

**Organization**: Tasks grouped by user story for independent implementation/testing. The evidence-gate (T003) is the single hard prerequisite for the extraction tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: runs in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 / none for setup/foundational

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Minimal project hooks for the rendered-capture inspection and debug artifacts.

- [X] T001 [P] Add a `_save_rendered_html(name: str, html, out_dir="debug_output")` helper in `src/scraper/targets.py` and ensure the `debug_output/` directory exists on import (mirrors existing `_save_debug_html`). NO extraction logic here.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Produce the real captured page + the detail-URL plumbing that ALL extraction tasks depend on.

**⚠️ CRITICAL**: No US2 extraction task may begin until T003 has cleared (reported mechanism).

- [X] T002 Resolve/confirm the detail-page URL from listing cards: in `_parse_ti_from_css` and `_parse_ti_via_similarity` (`src/scraper/targets.py`), capture the company anchor `href` (`.company-url` / `a[href]`; keep `.company-url` candidate, `a[href]` fallback), compute `detail_url = urljoin(response.url, href)` and store it per `RawRecord` (`data-model.md`). Card with no resolvable href → `detail_url = None`. Do NOT overwrite `source_url`. (contracts/detail-page-url.md)
- [X] T003 Evidence-gate (user task 1): render ONE real TradeIndia detail page with `StealthyFetcher` (headless, `solve_cloudflare`, `load_dom`, `network_idle`, let client render settle), save the DOM to `debug_output/tradeindia_detail_inspection.html` via T001, and REPORT the protection mechanism (`plain text` | `tel:`/`mailto:` | `js-reveal-button` | `obfuscated` | `login-gate`) with quoted evidence for phone/email/website. Use a first detail URL from T002 or a bootstrap/known company URL. **(contract detail-page-capture.md)**. STOP and confirm the approach BEFORE T005-T007 if the mechanism is not plain/tel-mailto (FR-003/Q1); record the confirmed mechanism as the governing basis.

**Checkpoint**: Foundation ready. Mechanism reported; detail-URL source known.

---

## Phase 3: User Story 1 - Enable Detail-Page Enrichment with Configurable Cap (Priority: P1) 🎯 MVP

**Goal**: The pipeline runs TradeIndia detail enrichment for needy records up to a configurable per-run cap (default 20), reusing the existing per-domain cap machinery.

**Independent Test**: With `max_requests_per_day` unconstrained, N needy records → at most 20 detail requests per run; records already possessing phone+email are not requested; non-existent `detail_url` records are skipped (horizontal).

- [X] T004 [US1] Wire detail URLs into enrichment in `LeadSpider.on_close` (`src/scraper/spider.py`): build `needy` from resolved `detail_url` (skip indexes where the record already has BOTH phone and email, or whose `detail_url` is None), truncate to `needy[:max_detail]` where `max_detail = fetch_kwargs.get("max_detail_pages", 20)`, and call `_enrich_from_detail_pages(session=None, self.all_records, needy[:max_detail], timeout, cap_guard)` (cap 20 default). (contracts/enrichment-rate-limiting.md)
- [X] T005 [US1] Confirm/ensure the configurable cap: `config/targets.yaml` TradeIndia keeps `fetch_kwargs.max_detail_pages: 20` and the code default matches 20; adjust either so the config value is the sole control (SC-001, per feature-005 SC-005 precedent).

**Checkpoint**: US1 fully functional — enrichment runs within the 20-page cap; SC-001 satisfied.

---

## Phase 4: User Story 2 — Evidence-Based Extraction & Unavailable Logging (Priority: P2)

**Goal**: Phone/email/website extracted from each detail page per the reported mechanism; any unextractable field logs `enrichment_unavailable: <field>`. No silent blanks (FR-005).

**Independent test**: Given a captured page, each needed field either populates or produces exactly one `enrichment_unavailable: phone|email|website` line; site-wide values rejected; filled fields never overwritten.

### Implementation for User Story 2

- [X] T006 [US2] Phone extraction (or mark unavailable) in `src/scraper/targets.py`: apply the mechanism-appropriate path (plain text `(?:\+?91[-\s]?)?[6-9]\d{9}`, `tel:` href, or a single bounded click+wait per Q2 with no retry). On failure/guard/login, log `enrichment_unavailable: phone`. (contracts/enrichment-extraction.md)
- [X] T007 [P] [US2] Email extraction (or mark unavailable): mailto href / text RFC-5322-lite; if mechanism-gated, apply the same single bounded attempt; reject `helpdesk@tradeindia.com`; else log `enrichment_unavailable: email`.
- [X] T008 [P] [US2] Website extraction (or mark unavailable): capture the company website anchor on the detail page; reject `DIRECTORY_DOMAINS` websites; else log `enrichment_unavailable: website`.
- [X] T009 [US2] Guard + idempotency sweep: apply `KNOWN_SITE_WIDE_PHONES`/`KNOWN_SITE_WIDE_EMAILS` rejection; ensure a detail value only fills an EMPTY field (never overwrite) and a record already carrying phone+email produced no lines and no request (Constitution IV). Literal token `enrichment_unavailable: ` is the required prefix.

**Checkpoint**: US1 AND US2 both independent functional; SC-002/SC-007 met.

---

## Phase 5: User Story 3 — Per-Domain Rate-Limit & Fill-Rate Reporting (Priority: P3)

**Goal**: Extra detail requests cannot breach the per-domain Phase-1 daily cap; run summary reports TradeIndia fill rates.

**Independent target**: With `max_requests_per_day=2` and 3 needy records, TradeIndia detail requests ≤ 2; on exhaustion enrichment is skipped+logged; and a `phone=X/N email=Y/N website=Z/N` line is present for TradeIndia.

- [X] T010 [US3] Enforce per-domain cap for detail requests: ensure `on_close` passes `cap_guard = self._cap_guard_for("www.tradeindia.com", entry["daily_cap"])` for TradeIndia entries and the `is_robots_allowed` check precedes each detail fetch (Constitution I); when the guard denies, skip and log (existing message). (contracts/enrichment-rate-limiting.md)
- [X] T011 [US3] Fill-rate reporting in the run summary: recompute `_fill_rates` after enrichment in `on_close` (present), ensure the TradeIndia line prints `%s: %d records, phone=X/T, email=Y/T, website=Z/T` with `T` = TI record count; cover the 0-records case (report 0 values, not an error).

**Checkpoint**: All user stories independently functional; SC-003/SC-004.

---

## Phase 6: Polish & Cross-Cutting

**Purpose**: Regression safety, run validation.

- [X] T012 [P] Add inline tests for: detail-URL capture+urljoin, `enrichment_unavailable` literal, site-wide rejection, cap=0 / over-cap no-request, mailto email, filled-field non-overwrite — in `tests/test_targets.py` and `tests/test_spider.py`. (Tests required — no omission.)
- [X] T013 Run `python -m pytest -q` (whole suite) until green and run `quickstart.md` validation (inspect debug artifact exists; fill-rate + no-cap-breach observed).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: independent — can start immediately (T001-only).
- **Foundational (Phase 2)**: depends on Setup; BLOCKS all user stories.
- **US1 (T004-T005)**: depends on T002 (which states they only need it), NOT on inspection (T003) — cap/dispatch can be plumbed in parallel.
- **US2 (T006-T009)**: depends on T003 (mechanism report); T006-T008 parallel among themselves after the gate.
- **US3 (T010-T011)**: depends on T002+T004 cap wiring; can run alongside US2.
- **Polish**: after implementation.

### User Story Dependencies

- **US1**: chains off Foundational (T002); independent install-test.
- **US2**: requires inspection evidence (T003); independent test (mechanism-based).
- **US3**: requires US1's cap wiring + detail URLs (T002).

### Parallel Opportunities

- T001 (setup) parallel with a minimum of nothing else — it's fast.
- T002 (URL resolution) parallel with T003 (inspection) only if T003 can derive its own bootstrap URL; else T002→T003.
- T006, T007, T008 (US2 field tasks) parallel — distinct fields.
- US1 (T004/T005), US3 (T010/T011) can be staffed in parallel after T002.

## Implementation Strategy

### MVP First (User Story 1 + it's evidence)

1. Phase 1: T001.
2. Phase 2: T002; then run the inspection gate T003 and REPORT the mechanism (do not bolt extraction until a confirm if non-trivial).
3. Phase 3: US1 (cap + dispatch); VALIDATE independently (SC-001).
4. Phase 4: US2 extraction + unavailable logging (post-gate), independent check (SC-002).
5. Phase 5: US3 cap enforcement + fill-rate; VALIDATE (SC-003/004).

### Incremental Delivery

- Setup→Foundational (evidence) → US1 MVP → US2 → US3, each independently demonstrable.

---

## Notes

- Hard gate: T003 must report the mechanism (and for non-trivial, get confirmation) BEFORE T005/T006 extraction.
- Constraints honored: robots (I), idempotent (IV), fail loud (V), non-destructive skip, JS single-bounded (Q2).
- All paths live in `src/scraper/{targets,spider}.py`, `config/targets.yaml`, and tests; no new modules needed (plan.md).