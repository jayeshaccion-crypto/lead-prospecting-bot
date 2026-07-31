---

description: "Task list for JustDial Three-Mode Proxy Routing"
---

# Tasks: JustDial Three-Mode Proxy Routing

**Input**: Design documents from `specs/004-justdial-proxy-modes/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (all complete)

**Organization**: Four sequential phases matching the requested breakdown — (1) env-var reading + mode selection, (2) the X/10 rotation test, (3) the "ran today" gate, (4) summary log lines for all three modes. Each phase is independently verifiable before the next begins.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other [P] tasks
- **[Story]**: Which user story this task belongs to (US1 residential crawl, US2 ASN test, US3 skip)
- Include exact file paths in descriptions

## Task Dependency Graph

```text
T001 ──→ T002 ──→ T003 ──→ T004 ──→ T005 ──→ T006 ──→ T007 ──→ T008
(mode selection)  (probe method)  (flag storage)  (probe wiring)  (no_proxy)  (summary lines)  (tests)  (regression)
```

Phases 1–4 are sequential — they touch the same files (`src/scraper/spider.py`, `tests/test_spider.py`). T001 is a **foundational prerequisite**: mode selection gates every other behavior.

---

## Phase 1: T001 — Env-Var Reading + Mode Selection Logic

**Goal**: The `_determine_jd_mode()` precedence — residential / datacenter / no_proxy — is correct and independently testable for every env-var combination. Residential wins when both residential var and Webshare pool are set. A whitespace-only residential value is treated as unset.

**User Stories**: US1, US3 (foundation for both)

**Files touched**: `src/scraper/spider.py`, `tests/test_spider.py`

**Reference**: `contracts/jd-mode.md`

### Implementation Tasks

- [X] T001 Verify `_determine_jd_mode()` (src/scraper/spider.py:214-222) reads `RESIDENTIAL_PROXY_URL_JUSTDIAL` with `.strip()` before truthiness — residential check MUST precede the `_PROXY_POOL` check
- [X] T002 Verify `_determine_jd_mode()` calls `_engine_mod._init_proxy_pool()` first so `_PROXY_POOL` is populated before the datacenter check
- [X] T003 Confirm no `PROXY_URL_JUSTDIAL` variable exists anywhere (grep `src/`, `.github/workflows/`) — the contract forbids introducing it; if found, flag and remove
- [X] T004 Confirm mode is resolved once per run and stored on `self._jd_mode` (spider.py:184, resolved in `on_start`/`start_requests`) — must not be recomputed mid-run

**Verification gate** (run before T002 begins) — new tests in `tests/test_spider.py`:

```bash
pytest tests/test_spider.py -v -k "jd_mode"
```

**Expected**: tests assert all env combinations — residential only → `residential`; both set → `residential`; pool only → `datacenter`; neither → `no_proxy`; whitespace residential → falls through to pool/no_proxy. Existing `test_spider.py` JD-mode tests (lines ~161-332) continue to pass.

---

## Phase 2: T002 — X/10 Rotation Test via ProxyRotator

**Goal**: Implement `LeadSpider._run_asn_test()` — a bounded probe that builds ≤10 distinct Webshare IPs, rotates through them via `scrapling.fetchers.ProxyRotator`, issues a single request per IP to a robots-allowed JustDial category page, and tallies X (attempted), Y (blocked), Z (succeeded) with `X == Y + Z`.

**User Stories**: US2

**Files touched**: `src/scraper/spider.py`, `src/scraper/engine.py` (if helper needed), `tests/test_spider.py`

**Reference**: `contracts/asn-test.md`, `research.md` R3, R5

### Implementation Tasks

- [X] T005 Add `_run_asn_test(self)` to `LeadSpider` in src/scraper/spider.py — builds candidate proxy list (≤10 distinct IPs): read distinct entries already in `_PROXY_POOL` (deduped) FIRST; call `_fetch_proxies_from_api(WEBSHARE_API_KEY)` ONLY when the pool is a single rotating endpoint (`WEBSHARE_PROXY_URL`) with no distinct IPs (avoids a duplicate Webshare API call — `_init_proxy_pool` may already have fetched from the API)
- [X] T006 Construct `ProxyRotator(candidates)` from `scrapling.fetchers` with cyclic rotation; guard empty candidates with a warning + no probe
- [X] T007 Probe loop: `proxy = rotator.get_proxy()`; issue a **single** request per IP to the FR-010 probe URL with `proxy=` override **via the existing `justdial_session` (AsyncStealthySession)** — reuse the Phase 1 session infra, never build a parallel fetch stack; classify each response **using the existing `is_blocked()` semantics** (`BLOCKED_STATUS_CODES` superset + body < 500B) so the Y tally matches crawl blocking, per research R5
- [X] T008 Ensure the probe URL passes `is_robots_allowed()` before any request (reuse gate at spider.py:307); log `RobotsDisallowed` error if not
- [X] T009 Wrap the probe loop in try/except — a failure inside `_run_asn_test()` never crashes the run; existing JustDial disposition is logged instead
- [X] T010 Tally invariant: `X == Y + Z`, `X <= 10`; store on the spider for the summary phase (reuse/extend `_jd_stats`)

**Verification gate** (run before T003 begins) — new tests in `tests/test_spider.py`:

```bash
pytest tests/test_spider.py -v -k "asn"
```

**Expected**: tests stub the Webshare API response and probe responses (monkeypatched), assert X/Y/Z counts, `X == Y + Z`, the robots gate is honored, and a probe exception is swallowed without crashing the run.

---

## Phase 3: T003 — The "Ran Today" Gate (per clarification Q4)

**Goal**: The ASN test runs at most once per calendar day, enforced by a **persisted date-stamped flag in the existing `data/request_counts.json`** (reserved `__jd_asn_test` key). Holds across manual re-runs/retries on the same day; auto-resets on date rollover via the existing `_load()` semantics.

**User Stories**: US2

**Files touched**: `src/scraper/spider.py`, `data/request_counts.json`, `tests/test_spider.py`

**Reference**: `contracts/asn-test.md`, `data-model.md` (ASN Test State), `research.md` R2

### Implementation Tasks

- [X] T011 Extend `DomainRequestCounter` (src/scraper/spider.py:110-153) with `asn_tested()` → bool (checks `counts.get("__jd_asn_test")`) and `mark_asn_tested()` (sets key to `1`, calls `_save()`)
- [X] T012 Wire the gate in `start_requests()` (spider.py:245-364): in datacenter mode, if `not self._req_counter.asn_tested()` → yield probe via `_run_asn_test()` and call `mark_asn_tested()` immediately after completion; if already tested → skip probe entirely
- [X] T013 Ensure datacenter mode yields **zero** category/city crawl requests — the existing `_jd_tested` in-memory flag and the one-category probe loop at spider.py:298/362-364 are replaced by the persisted-gate flow
- [X] T014 Verify `__jd_asn_test` is written with today's date context (the `_load()`/`_save()` `date` field) so date rollover auto-clears it — no manual cleanup

**Verification gate** (run before T004 begins) — new tests in `tests/test_spider.py`:

```bash
pytest tests/test_spider.py -v -k "asn"
```

**Expected**: two `LeadSpider` instances created on the same date run the probe once total; the second instance sees the persisted flag and yields no probe and no crawl requests. `data/request_counts.json` contains `"__jd_asn_test": 1` for today's date after the first run.

---

## Phase 4: T004 — Summary Log Lines for All Three Modes

**Goal**: Exact end-of-run summary strings per `contracts/summary-lines.md` — the ASN verdict (FR-005), the CONCLUSION line when Y == X (FR-006), the mode summary for all three modes (FR-008), and the no-proxy warning + `ScrapeError` (FR-007). Wording matches the spec precisely.

**User Stories**: US1, US2, US3

**Files touched**: `src/scraper/spider.py` (on_close), `tests/test_spider.py`

**Reference**: `contracts/summary-lines.md`

### Implementation Tasks

- [X] T015 In `on_close()` (spider.py:569-586), emit `JustDial: X/10 distinct proxy IPs attempted, Y blocked (body<500B), Z succeeded.` exactly per FR-005 after a datacenter-mode probe
- [X] T016 Append the CONCLUSION line exactly per FR-006 (`CONCLUSION: JustDial block is ASN-level — datacenter proxies cannot bypass regardless of specific IP. Residential proxy required.`) **only** when `Y == X`; never when `Z > 0`. Note: replaces the old wording "Residential proxy tier required." at spider.py:581-583
- [X] T017 Emit `JustDial mode: residential` / `JustDial mode: datacenter-ASN-test` / `JustDial mode: no_proxy` in the run summary for every run (FR-008); map internal `datacenter` → display `datacenter-ASN-test`
- [X] T018 no_proxy mode: emit the explicit warning naming the missing env var(s) per `contracts/summary-lines.md` + `ScrapeError("ProxyNotConfigured")` (existing spider.py:272-279) and ensure the mode summary line still appears
- [X] T019 Credential redaction: any proxy host logged (blocked-IP sets, retry logs) uses `str(proxy).partition("@")[-1]` (spider.py:480) — never the full URL with embedded `user:pass` (constitution III)

**Verification gate** (run before T005 begins) — new tests in `tests/test_spider.py`:

```bash
pytest tests/test_spider.py -v -k "justdial_summary"
```

**Expected**: tests capture log output (caplog) for all three modes and assert the exact strings above — verdict + CONCLUSION only when Y==X, mode summary for every run, and no credentials in any logged proxy string.

---

## Phase 5: T005 — Full-Suite Regression

**Purpose**: Verify everything works end-to-end and no regressions; quickstart scenarios pass.

**User Stories**: US1, US2, US3

- [X] T020 Run `pytest tests/ -q --tb=short` — confirm 385 existing + new tests all pass (no regression)
- [X] T021 Run `python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()"` in each of the three mode configs (residential / datacenter / no_proxy) and confirm the summary lines match `contracts/summary-lines.md`
- [X] T022 Validate `specs/004-justdial-proxy-modes/quickstart.md` scenarios 1–6 pass
- [X] T023 Add a residential-mode depth assertion to `tests/test_spider.py` (FR-002/SC-001): with `RESIDENTIAL_PROXY_URL_JUSTDIAL` + `SCRAPE_FULL_PAGES=true`, the emitted JustDial request count per category equals IndiaMart/TradeIndia's — proves full depth is restored, not capped to page 1

---

## Dependencies & Execution Order

### Phase Dependencies

- **T001 (Mode Selection)**: No dependencies — starting point; BLOCKS all other phases (mode gates every behavior)
- **T002 (Probe)**: Depends on T001 — probe only runs in datacenter mode
- **T003 (Ran-Today Gate)**: Depends on T002 — gates the probe method; can be implemented after the probe loop exists
- **T004 (Summary Lines)**: Depends on T002, T003 — verdict + CONCLUSION need the probe tally; mode summary needs all three modes resolved
- **T005 (Regression)**: Depends on all prior phases (T020-T023)

### Sequential Requirement

Phases 1–4 are strictly sequential — all touch `src/scraper/spider.py` and must be verified independently before the next begins.

### Parallel Opportunities

None within this feature — single file (`spider.py`) plus `tests/test_spider.py`; single-developer scope. The `DomainRequestCounter` extension (T011) and the probe method (T005) could in principle be developed independently, but both land in the same file, so keep sequential.

---

## Implementation Strategy

### MVP: T001 + T002 + T003

The minimum that demonstrates value: correct mode selection, a bounded X/10 probe, and once-daily idempotency. This delivers the datacenter-mode ASN test end-to-end (US2).

### Incremental Delivery

1. **T001 complete**: Env-var combinations select the right mode (testable in isolation)
2. **T002 complete**: X/10 probe tallies correctly via ProxyRotator
3. **T003 complete**: Probe runs once per calendar day (persisted flag)
4. **T004 complete**: Exact summary lines for all three modes
5. **T005 complete**: Full suite green, quickstart scenarios valid

## Notes

- Tests are included per the feature specification (spec.md mandates independently testable user stories; quickstart references the pytest gates).
- The stricter "Z requires listing selector match" variant (clarify Q2, recommended Option A) was NOT selected by the user — tasks use the literal definition Z = body ≥ 500B (research.md R5). Flagged as deferred; revisit if live probes show large non-listing block pages.
