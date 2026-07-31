# Feature Specification: JustDial Three-Mode Proxy Routing

**Feature Branch**: `004-justdial-proxy-modes`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "Add two env vars for JustDial proxy: RESIDENTIAL_PROXY_URL_JUSTDIAL (new) and PROXY_URL_JUSTDIAL (existing, Webshare datacenter). 3-mode behavior: 1) Residential set -> full page depth crawl via that proxy. 2) Only datacenter var -> one-time-per-day ASN confirmation test (fetch all Webshare IPs via API, rotate through each one via ProxyRotator for a single request each, log 'JustDial: X/10 distinct proxy IPs attempted, Y blocked (body<500B), Z succeeded.', if Y==X log CONCLUSION ASN-level line, NO further JD crawling). 3) Neither set -> skip JD with explicit warning. End-of-run summary must state which mode JD ran in."

## Clarifications

### Session 2026-07-31

- **Q1: Datacenter-mode trigger env var** → A: **Reuse the existing WEBSHARE proxy pool — do NOT add a new `PROXY_URL_JUSTDIAL` variable.** Codegraph confirmed `RESIDENTIAL_PROXY_URL_JUSTDIAL` already exists (spider.py:218,233,466) and drives `_determine_jd_mode()`, while no `PROXY_URL_JUSTDIAL` exists anywhere; datacenter proxies already come from `WEBSHARE_PROXY_URL` / `WEBSHARE_PROXY_LIST` / `WEBSHARE_API_KEY` via `_init_proxy_pool()`. Datacenter mode is therefore triggered by the presence of that pool when the residential var is unset — which `_determine_jd_mode()` already computes today.
- **Q2: What changes vs. current behavior** → A: Today the datacenter mode still crawls JustDial through the Webshare pool (and gets body<500B blocks). Feature 004 changes datacenter mode to run ONLY a bounded, once-daily ASN confirmation test and to perform NO JustDial crawling. Residential and no_proxy modes already behave as specified and are preserved.
- **Q3: ProxyRotator availability** → A: `scrapling.fetchers.ProxyRotator` (cyclic rotation, thread-safe) exists in the vendored submodule — a valid implementation path. Per-request `proxy=` override also exists. Implementation detail; kept out of requirements.
- **Q4: ASN-test "already ran today" flag persistence** → A: Persisted date-stamped flag reused in the existing daily state file (`data/request_counts.json`), so once-per-calendar-day holds even across manual re-runs (workflow_dispatch) and retries on the same day — not merely "once per GitHub Actions scheduled run".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full Depth JustDial Crawl via Residential Proxy (Priority: P1)

A pipeline operator configures the residential proxy endpoint and runs a full crawl. JustDial requests go through the residential rotating endpoint, and JustDial is crawled at the same full page depth as the other directories (IndiaMart, TradeIndia) — every configured category/city page, not just the first page. Data completeness for JustDial is restored.

**Why this priority**: Residential proxies are the only path to full-depth JustDial data (datacenter IPs return blocked/empty bodies). Full crawling is the feature's core value; the other two modes are risk-management behaviors around it.

**Independent Test**: Set `RESIDENTIAL_PROXY_URL_JUSTDIAL`, enable `SCRAPE_FULL_PAGES=true`, run a crawl, and confirm JustDial requests emit the same full page depth as IndiaMart/TradeIndia and carry the residential proxy.

**Acceptance Scenarios**:

1. **Given** `RESIDENTIAL_PROXY_URL_JUSTDIAL` is set, **When** a crawl runs, **Then** every JustDial request uses the residential proxy URL, and JustDial is crawled at the configured full page depth (same as IndiaMart/TradeIndia).
2. **Given** both the residential var and a Webshare datacenter pool are configured, **When** a crawl runs, **Then** residential mode wins — JustDial is crawled in full via the residential proxy, and no ASN confirmation test runs.
3. **Given** the residential var is set to an empty or whitespace-only value, **When** a crawl runs, **Then** it is treated as unset and mode selection falls through to the next tier.

---

### User Story 2 - Once-Daily ASN Confirmation Test for Datacenter Only (Priority: P2)

A pipeline operator has only a Webshare datacenter pool configured. Instead of wasting the crawl's request budget on JustDial pages that get blocked with empty bodies, the pipeline runs a single, bounded probe per calendar day: it fetches the distinct Webshare IPs, rotates through them one request each, and logs a verdict summary. If every attempted IP is blocked, it logs a conclusion that JustDial's block is ASN-level and that a residential proxy is required. No further JustDial crawling occurs on that day.

**Why this priority**: This converts an expensive silent failure (full crawl, all bodies <500B) into a cheap, once-daily diagnostic that either confirms the block is ASN-level or detects that datacenter access has been unblocked. It protects the run budget and keeps the operator informed without any JustDial crawl activity.

**Independent Test**: Configure only `WEBSHARE_API_KEY` (no residential var) and run the crawl twice on the same day. Confirm the first run logs the verdict summary lines and performs no JustDial crawling, and the second run performs neither the test nor any crawling.

**Acceptance Scenarios**:

1. **Given** only a Webshare datacenter pool is configured and no ASN test has run today, **When** a crawl runs, **Then** the pipeline fetches all valid Webshare proxy IPs, rotates through them for a single request each (capped at 10 distinct IPs), and logs exactly `JustDial: X/10 distinct proxy IPs attempted, Y blocked (body<500B), Z succeeded.`
2. **Given** the ASN test already ran earlier today, **When** a crawl runs again, **Then** neither the test nor any JustDial crawling runs again (once per calendar day).
3. **Given** all attempted proxy IPs are blocked (Y == X), **When** the test completes, **Then** the pipeline additionally logs the CONCLUSION line that JustDial's block is ASN-level and a residential proxy is required.
4. **Given** at least one attempted proxy IP succeeds (Z > 0), **When** the test completes, **Then** the pipeline does NOT log the ASN-level conclusion line.
5. **Given** the datacenter pool contains fewer than 10 distinct IPs, **When** the test runs, **Then** every distinct IP is attempted once and X reflects the actual count of attempted IPs.
6. **Given** the ASN test runs, **When** the test finishes, **Then** JustDial performs no further crawling for the rest of the run.

---

### User Story 3 - Skip JustDial with Explicit Warning (Priority: P3)

A pipeline operator runs a crawl with no JustDial proxy configured at all — no residential var, no Webshare pool. The pipeline skips JustDial entirely and logs an explicit warning so the operator can tell a silent omission from a deliberate skip in the run summary.

**Why this priority**: This is the safest default (no crawl attempts on an unbounded path) and guards against silent loss of the JustDial directory. It is a visibility/safety net rather than a data-delivery path, hence lowest priority.

**Independent Test**: Run a crawl with neither the residential var nor any Webshare proxy configured. Confirm JustDial is skipped with an explicit warning and zero JustDial requests are issued.

**Acceptance Scenarios**:

1. **Given** neither `RESIDENTIAL_PROXY_URL_JUSTDIAL` nor a Webshare pool is configured, **When** a crawl runs, **Then** JustDial is skipped with an explicit warning log and zero JustDial requests are issued.
2. **Given** JustDial was skipped, **When** the run finishes, **Then** the end-of-run summary states that JustDial ran in no-proxy/skipped mode.

---

### Edge Cases

- What happens when the Webshare API call fails (network error, bad key, rate limit)? → The pool is empty, so mode selection falls through to `no_proxy`; JustDial is skipped with the explicit warning. A failed test must never crash the run.
- What happens when the datacenter pool has exactly one IP? → X=1: a single request is attempted; verdict lines still emitted with the correct counts.
- What happens when a proxy request errors (connection refused / timeout) rather than returning an HTTP response? → Counted as blocked (no usable body), consistent with the Y tally.
- What happens across a day boundary (test ran at 23:59, next crawl at 00:01)? → A new calendar day starts a new ASN test round (once-per-calendar-day, not once-per-run).
- What happens if `RESIDENTIAL_PROXY_URL_JUSTDIAL` is set to an empty string? → Treated as unset; selection falls through (see US1.3).
- What happens when both residential and datacenter are present? → Residential wins; no ASN test, full crawl (see US1.2).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST select the JustDial mode by env-var precedence: residential (`RESIDENTIAL_PROXY_URL_JUSTDIAL` set) → datacenter (only Webshare pool present) → no-proxy (neither). A whitespace-only residential value MUST be treated as unset.
- **FR-002**: In residential mode, System MUST crawl JustDial at the full configured page depth — identical depth to IndiaMart and TradeIndia — with every JustDial request routed through the residential proxy.
- **FR-003**: In datacenter mode, System MUST NOT perform any JustDial crawling. It MUST instead run the ASN confirmation test at most once per calendar day.
- **FR-004**: The ASN test MUST fetch all valid distinct Webshare proxy IPs (via the existing Webshare API integration), attempt a single request through each (capped at 10 distinct IPs), and MUST reuse the existing Webshare pool configuration with no new env var.
- **FR-005**: The ASN test MUST log a verdict summary in the exact format `JustDial: X/10 distinct proxy IPs attempted, Y blocked (body<500B), Z succeeded.` where X = distinct IPs attempted (≤10), Y = blocked (body < 500B), Z = succeeded.
- **FR-006**: When Y == X, System MUST additionally log the conclusion that JustDial's block is ASN-level and that a residential proxy is required to crawl JustDial.
- **FR-007**: In no-proxy mode, System MUST skip JustDial with an explicit warning log that names the missing env var(s) — `RESIDENTIAL_PROXY_URL_JUSTDIAL` and/or the Webshare datacenter vars (`WEBSHARE_PROXY_URL` / `WEBSHARE_PROXY_LIST` / `WEBSHARE_API_KEY`) — and issue zero JustDial requests.
- **FR-008**: The end-of-run summary MUST state which JustDial mode (residential / datacenter-ASN-test / no-proxy) was active during the run.
- **FR-009**: The ASN test MUST be idempotent per calendar day via a **persisted date-stamped flag stored in the existing daily state file** (`data/request_counts.json`): once it has completed on a given date, subsequent runs on that date — including manual re-runs and retries — MUST NOT re-run the test nor crawl JustDial.

- **FR-010**: The ASN test MUST probe a single representative JustDial category listing page (exact URL chosen during planning); the probe is for block detection, not data collection.

### Key Entities *(include if feature involves data)*

- **JustDial Proxy Mode**: The resolved mode for a run — `residential`, `datacenter`, or `no_proxy` — computed from env state by `_determine_jd_mode()`. Determines whether JustDial is crawled in full, probed once daily, or skipped.
- **ASN Test State**: Record of the last calendar day on which the ASN confirmation test ran, stored as a date-stamped flag in the existing daily state file (`data/request_counts.json`). Enables the once-per-calendar-day guarantee (FR-009) across all runs on the same day.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With `RESIDENTIAL_PROXY_URL_JUSTDIAL` set, a JustDial crawl emits the same number of requests/pages per category as IndiaMart and TradeIndia at full page depth — i.e., full depth restored, not capped to page 1.
- **SC-002**: In datacenter-only configuration, a run issues at most 10 ASN-test requests to JustDial and zero JustDial crawl requests.
- **SC-003**: Running the pipeline twice on the same calendar day in datacenter-only configuration issues ASN-test requests at most once total.
- **SC-004**: Every run's end-of-run summary explicitly states the JustDial mode that was active, regardless of which mode it was.
- **SC-005**: In no-proxy configuration, zero JustDial requests are issued and a warning is logged.

## Assumptions

- `RESIDENTIAL_PROXY_URL_JUSTDIAL` already exists and remains the sole residential-mode trigger (confirmed by codegraph; no new residential variable).
- No `PROXY_URL_JUSTDIAL` variable is introduced; datacenter mode reuses the existing `WEBSHARE_PROXY_URL` / `WEBSHARE_PROXY_LIST` / `WEBSHARE_API_KEY` pool (per clarification Q1).
- "10" in the verdict line is a cap on distinct IPs attempted, not a quota that must be filled; X = min(10, distinct valid IPs available).
- The ASN test probes a single representative JustDial URL (a category listing page) — the exact URL is an implementation detail resolved during planning; the test's purpose is block detection, not data collection.
- "Once per calendar day" is enforced by a persisted date-stamped flag stored in the existing daily state file (`data/request_counts.json`) — the same store backing the daily request-count cap; no new persistence system or schema change is introduced (per clarification Q4).
- "Full page depth" means the same depth configuration applied to IndiaMart and TradeIndia — driven by the existing `pages`/`SCRAPE_FULL_PAGES` settings, unchanged by this feature.
- The ASN test counts a request as blocked when the response body is under 500 bytes (matching the existing blocked-detection definition) OR the request errors before producing a usable body.
- A failed Webshare API fetch degrades to no-proxy mode (skip JustDial with warning); it must never crash the run.
