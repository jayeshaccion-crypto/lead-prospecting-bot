# Feature Specification: Spider Migration — Crawl Orchestration

**Feature Branch**: `003-spider-migration`

**Created**: 2026-07-30

**Status**: Draft

**Input**: User description: "Migrate crawl orchestration onto scrapling.spiders.Spider. Requirements: 1. One Spider subclass replacing the current standalone per-site fetch loops. 2. Three sessions, routed by sid: justdial_session and indiamart_session use StealthySession (geoip=True, humanize=True, solve_cloudflare=True, proxy-enabled); tradeindia_session uses a plain FetcherSession — no proxy, no browser-only kwargs. 3. Per-domain throttling via the Scheduler, not hand-rolled sleep() calls: indiamart.com -> random 8-20s delay between requests, justdial.com -> random 5-10s, tradeindia.com -> no artificial delay. 4. Blocked-response detection: a response counts as blocked if status==429, OR status==200 with body length under 500 bytes. Wire this into max_blocked_retries=3 at the engine level. 5. Pause/resume checkpointing so a run killed mid-crawl resumes from checkpoint rather than restarting from zero. 6. CONFIRMED PRIOR BUG to guard against: browser-only kwargs (proxy, geoip, humanize, solve_cloudflare, wait, wait_selector) were previously assembled in a single shared kwargs dict passed to all three sessions, causing TypeError on the plain FetcherSession. Kwargs construction must be session-type-specific from the start, not filtered after the fact."

## Clarifications

### Session 2026-07-30

- **Q1: URL structure / start_requests() mapping** → A: URL generation maps cleanly — `LeadSpider.start_requests()` already yields `Request` objects with `sid`, `meta`, and session kwargs from config-driven URL templates and pagination helpers. No rebuild needed; the existing logic is relocated into the Spider subclass.
- **Q2: Blocked-response detection** → A: Relocate existing logic into Spider's `is_blocked()` hook. Current `is_blocked()` already detects status 429 and 200-with-body<500B (plus broader codes). `retry_blocked_request()` rotates proxy on retry. Only relocation and aligning to spec status codes is needed.
- **Q3: Checkpoint / state persistence** → A: Build on existing mechanism. `super().__init__(crawldir=".scrapling_checkpoints")` is already wired at spider.py:142 — Scrapling's `CrawlerEngine` handles periodic saves and resume. No custom persistence needed.
- **Q4: Global concurrency cap** → A: Default to max 2 concurrent requests globally (in addition to per-domain throttling). Matches existing behavior, conservative enough to avoid rate-limit cascades.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Correct Session Routing Per Site (Priority: P1)

A pipeline operator runs a full crawl across all three target directories. Requests to JustDial and IndiaMart use browser-emulating sessions (stealth, geo-aware, Cloudflare-solving, proxy-enabled). Requests to TradeIndia use a plain session without proxy or browser-only parameters. Every site completes its fetch without session-level errors.

**Why this priority**: Session misconfiguration is a hard failure — a plain session hitting Cloudflare-protected sites or a stealth session breaking a plain endpoint blocks the entire crawl. Correct routing is the minimum viable orchestration.

**Independent Test**: Run a crawl targeting all three directories. Confirm JustDial and IndiaMart requests succeed without Cloudflare challenges or proxy errors. Confirm TradeIndia requests succeed without receiving browser-specific parameters.

**Acceptance Scenarios**:

1. **Given** a crawl targeting all three directories, **When** the pipeline starts fetching JustDial and IndiaMart, **Then** requests use stealth session features (proxy, geo-hinting, Cloudflare solving).
2. **Given** a crawl targeting all three directories, **When** the pipeline starts fetching TradeIndia, **Then** requests use a plain session with no proxy and no browser-only parameters.
3. **Given** a prior bug where browser-only kwargs were passed to all sessions, **When** the orchestration starts, **Then** session-specific kwargs are constructed independently per session type — never assembled in a shared dict and filtered after the fact.

---

### User Story 2 - Blocked-Response Detection and Retry (Priority: P1)

A pipeline operator runs a crawl and some requests receive empty or blocked responses (HTTP 429, or 200 with body under 500 bytes). The orchestration detects these cases and retries the request up to 3 times before logging the failure.

**Why this priority**: Undetected blocked responses silently degrade data quality. Automatic retry with a limit prevents infinite loops while still recovering from transient blocks.

**Independent Test**: Simulate blocked responses (429 status, sub-500-byte body). Confirm the orchestration counts them as blocked and retries up to 3 times before recording the failure.

**Acceptance Scenarios**:

1. **Given** a request returns HTTP 429, **When** the orchestration evaluates the response, **Then** it is counted as blocked and retried (up to 3 attempts).
2. **Given** a request returns HTTP 200 with a body smaller than 500 bytes, **When** the orchestration evaluates the response, **Then** it is counted as blocked and retried (up to 3 attempts).
3. **Given** 3 consecutive blocked responses for the same request, **When** the retry limit is reached, **Then** the failure is logged and the pipeline continues with the next request.

---

### User Story 3 - Per-Domain Throttling via Scheduler (Priority: P2)

A pipeline operator runs a crawl targeting IndiaMart and JustDial simultaneously. The orchestrator spaces out requests to each domain at different rates — 8-20 seconds for IndiaMart, 5-10 seconds for JustDial — without using hand-rolled sleep calls. TradeIndia requests have no artificial delay.

**Why this priority**: Rate-limiting avoidance is essential for sustained crawling. Using a scheduler instead of sleep calls preserves the orchestrator's ability to pause/resume and checkpoint without losing timing state.

**Independent Test**: Run a crawl and measure the delay between consecutive requests for each domain. Confirm IndiaMart delay is 8-20s, JustDial delay is 5-10s, and TradeIndia has no added delay.

**Acceptance Scenarios**:

1. **Given** a crawl targeting IndiaMart, **When** multiple requests are sent, **Then** the delay between them is a random 8-20 seconds.
2. **Given** a crawl targeting JustDial, **When** multiple requests are sent, **Then** the delay between them is a random 5-10 seconds.
3. **Given** a crawl targeting TradeIndia, **When** multiple requests are sent, **Then** there is no artificial delay between them.

---

### User Story 4 - Mid-Run Checkpoint Resume (Priority: P2)

A pipeline operator starts a crawl that is killed mid-way (power loss, process crash, manual abort). When the operator restarts the pipeline, it resumes from the last checkpoint rather than restarting from the beginning.

**Why this priority**: Long-running crawls risk interruption. Checkpointing saves the operator's time and ensures complete data even after a failure.

**Independent Test**: Start a crawl, let it process some items, kill the process, restart. Confirm the second run picks up from where the first left off rather than from scratch.

**Acceptance Scenarios**:

1. **Given** a crawl is running and has processed some items, **When** the process is killed and restarted, **Then** the new run resumes from the last checkpoint, not from zero.
2. **Given** a crawl completes without interruption, **When** it finishes, **Then** checkpoint state reflects all items processed.

---

### Edge Cases

- What happens when all 3 retries are exhausted for a blocked request? The failure is logged and the orchestrator moves to the next item — one blocked item does not abort the entire crawl.
- What happens when the checkpoint file is corrupted or missing on resume? The orchestrator starts from the beginning with a warning logged.
- What happens when a session credentials are missing? The orchestrator fails explicitly at startup with a clear error message (per constitution Principle III).
- What happens when the Scheduler is configured with a domain that has no delay rule? No artificial delay is applied (safe default).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The orchestrator MUST provide a single entry point that replaces the current scatter of per-site fetch loops.
- **FR-002**: The orchestrator MUST route requests for each site identifier (sid) to the correct session type: stealth sessions for JustDial and IndiaMart, a plain session for TradeIndia.
- **FR-003**: Browser-only session parameters MUST be constructed independently per session type — never assembled in a shared dictionary and filtered after the fact.
- **FR-004**: The orchestrator MUST detect blocked responses as either HTTP 429 or HTTP 200 with a body under 500 bytes.
- **FR-005**: The orchestrator MUST retry blocked requests up to 3 times before logging the failure and moving on.
- **FR-006**: The orchestrator MUST throttle requests per domain: 8-20 second random delay for IndiaMart, 5-10 second random delay for JustDial, no delay for TradeIndia.
- **FR-007**: Throttling MUST use a scheduler interface rather than hand-rolled sleep calls to preserve pause/resume state.
- **FR-008**: The orchestrator MUST support pause/resume checkpointing so a killed run resumes from checkpoint, not from zero.
- **FR-009**: If a checkpoint file is missing or corrupted on resume, the orchestrator MUST start from the beginning and log a warning.
- **FR-010**: The orchestrator MUST cap global concurrency to a maximum of 2 concurrent requests across all sites, in addition to per-domain throttling.

### Key Entities *(include if feature involves data)*

- **Session**: A fetch context with specific configuration (stealth vs plain, proxy enabled/disabled, geo/humanize/Cloudflare settings). One session per site type.
- **Scheduler**: A rate-limiting mechanism that enforces per-domain delay rules and integrates with checkpointing to preserve timing state across pause/resume.
- **Checkpoint**: Persisted progress state that allows a killed run to resume from the last completed item rather than restarting.
- **Blocked Response**: A response categorized as blocked based on status code (429) or body size threshold (under 500 bytes), triggering retry logic.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three target directories complete their fetch routines without session-type errors (TypeError, missing parameter, or wrong session class).
- **SC-002**: Blocked responses are detected and retried within the 3-attempt limit. A run with simulated 429 responses completes with the expected number of logged failures (no more, no less).
- **SC-003**: Per-domain request intervals conform to specified ranges: IndiaMart 8-20s, JustDial 5-10s, TradeIndia no delay — verified by logged timestamps in a test run.
- **SC-004**: A crawl killed mid-run and restarted resumes the **pending request queue** from the last checkpoint — completed URLs are in the seen-set and never re-fetched (no duplicate processing). NOTE (reconciled): scraped items collected in memory before the crash are NOT persisted in the checkpoint and are dropped on resume; the resuming run re-fetches only still-pending requests. Full data equivalence with a single uninterrupted run is therefore not guaranteed for the pre-crash window — see plan.md Constitution IV (accepted completeness caveat, not an idempotency violation).
- **SC-005**: No regression in existing crawl output counts (tests pass at same volume as before migration).

## Assumptions

- The existing site identifier scheme (sid) remains unchanged — JustDial, IndiaMart, and TradeIndia are the only sids.
- The existing URL generation (`_build_source_url()`, `_build_page_url()`, config-driven templates) maps cleanly onto Scrapling's Request/Response objects and does not need to be rebuilt.
- Existing blocked-response detection logic (status 429 or 200 with body < 500 bytes, plus retry with proxy rotation) is relocated into the Spider's `is_blocked()` and `retry_blocked_request()` hooks — not replaced.
- Existing checkpoint persistence (`.scrapling_checkpoints` via `crawldir`) is already wired and reused — no custom checkpoint store is needed.
- Global concurrency capped at max 2 concurrent requests across all sites.
- Checkpoint storage is local to the run environment (no shared/distributed checkpoint store needed).
- Session credential provisioning (environment variables) follows the existing pattern — no new credential sources are introduced.
- TradeIndia does not use proxy or stealth features by design (per existing configuration).
