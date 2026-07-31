# Requirements Quality Checklist: Spider Migration Contracts

**Purpose**: Validate that spider migration requirements/contracts are complete, clear, and consistent before implementation begins
**Created**: 2026-07-30
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Is the structural mechanism that prevents browser-only kwargs from reaching FetcherSession explicitly specified (dict-of-factories lookup, not runtime if/elif or shared dict filtering)? [Completeness, contract/session-kwargs-factory.md]
- [ ] CHK002 Are the browser-only kwargs — proxy, geoip, humanize, solve_cloudflare, wait, wait_selector — explicitly enumerated as the set that the stealth factory returns and the plain factory excludes? [Completeness, contract/session-kwargs-factory.md §Stealth Factory]
- [ ] CHK003 Is the throttling scoping rule explicitly stated as "one delay entry per domain (sid), not per individual target URL"? [Completeness, contract/scheduler-config.md]
- [ ] CHK004 Is the rationale for domain-scoped throttling (Phase 3 will add many URLs per domain; URL-scoped delays would permit request bursts) documented in the contract? [Completeness, Gap — contract/scheduler-config.md]
- [ ] CHK005 Are distinct log message specifications provided for JustDial's 39-byte-stub pattern versus a generic slow-load timeout scenario? [Completeness, Gap — contract/blocked-response.md]
- [ ] CHK006 Is the slow-load timeout scenario defined as a separate blocked-response sub-type with its own detection criteria in the requirements? [Completeness, Gap — contract/blocked-response.md]
- [ ] CHK007 Is the fail-fast behavior for unknown session types specified (KeyError when sid not found in factory map)? [Completeness, contract/session-kwargs-factory.md §Invariant]

## Requirement Clarity

- [ ] CHK008 Is "structurally impossible to leak" expressed with a specific mechanism (dict-keyed lookup, separate factory per sid, no shared kwargs dict), not just intent? [Clarity, contract/session-kwargs-factory.md]
- [ ] CHK009 Is "per-domain throttling" unambiguously defined as "the delay key corresponds 1:1 to the sid (domain), not to each generated URL in the crawl iteration"? [Clarity, contract/scheduler-config.md]
- [ ] CHK010 Is the blocked-response classifier body-size threshold 0 < body_size < 500 unambiguous about the exclusive bounds (body_size == 0 and body_size >= 500 are NOT blocked)? [Clarity, contract/blocked-response.md §Classifier]
- [ ] CHK011 Are the log message templates for each blocked-response pattern (429, 200-with-small-body, specific per-pattern) explicitly specified — not just "log the block" but what exact message/level/fields? [Clarity, contract/blocked-response.md §4]
- [ ] CHK012 Is the timeout scenario distinguished from the 39-byte-stub scenario by explicit criteria, e.g., "body_size < 50 AND status == 200 is stub; status == 0 OR duration > timeout is timeout"? [Clarity, Gap — contract/blocked-response.md]

## Requirement Consistency

- [ ] CHK013 Do all contract documents agree that kwargs construction uses dict-keyed factories (not if/elif branching, not shared dict)? [Consistency, contract/session-kwargs-factory.md §Invariant vs plan.md §2]
- [ ] CHK014 Do the throttling requirements agree across contracts and plan that the delay applies inside start_requests() via anyio.sleep(random.uniform(...)), not via a scheduler plugin or middleware? [Consistency, contract/scheduler-config.md vs plan.md §3]
- [ ] CHK015 Do the blocked-response retry semantics agree across contracts and plan that max_blocked_retries = 3 and CrawlerEngine manages the retry count? [Consistency, contract/blocked-response.md §Max Retries vs plan.md §4]

## Coverage

- [ ] CHK016 Are the requirements specified for ALL three session types (justdial, indiamart, tradeindia) in the kwargs factory map? [Coverage, contract/session-kwargs-factory.md §Factory Map]
- [ ] CHK017 Are requirements defined for how non-429, non-200 status codes (403, 503, etc.) are classified — explicitly NOT blocked, or another category? [Coverage, Gap — contract/blocked-response.md §Classifier]
- [ ] CHK018 Are requirements defined for what happens when blocked-response retries are exhausted (3 failures) — skip request, log, continue? [Coverage, contract/blocked-response.md §Max Retries]
- [ ] CHK019 Are requirements defined for the scenario where a new sid is added without a corresponding factory entry? [Coverage, contract/session-kwargs-factory.md §Invariant]
- [ ] CHK020 Are requirements defined for proxy exhaustion scenarios (no proxy available for retry) per session type? [Coverage, contract/blocked-response.md §Error paths]

## Edge Case Coverage

- [ ] CHK021 Is the JustDial 39-byte-stub pattern explicitly called out as a distinct sub-case requiring its own log message (not lumped with generic sub-500B blocks)? [Edge Case, Gap — contract/blocked-response.md]
- [ ] CHK022 Are boundary conditions for body_size defined: body_size == 0 (not blocked), body_size == 500 (not blocked), body_size in [1, 499] (blocked)? [Edge Case, contract/blocked-response.md §Classifier]
- [ ] CHK023 Are requirements defined for the case where proxy is required (stealth sessions) but proxy list is exhausted — does the retry proceed without proxy or fail? [Edge Case, contract/blocked-response.md §Error paths]
- [ ] CHK024 Is the edge case where all per-domain delays are zero (TradeIndia) explicitly specified as "no anyio.sleep() call, yield immediately"? [Edge Case, contract/scheduler-config.md]

## Acceptance Criteria Quality

- [ ] CHK025 Can US-1 acceptance scenario 3 ("session-specific kwargs are constructed independently per session type — never assembled in a shared dict") be objectively verified by code review without running the system? [Measurability, spec.md US1]
- [ ] CHK026 Can US-2 acceptance scenario 3 ("3 consecutive blocked responses → failure logged and pipeline continues") be objectively verified by unit test without running a full crawl? [Measurability, spec.md US2]
- [ ] CHK027 Can US-3 acceptance scenario 3 ("TradeIndia no artificial delay") be objectively verified? Is "no delay" defined as "yields immediately without anyio.sleep()"? [Measurability, spec.md US3]
- [ ] CHK028 Can US-4 acceptance scenario 1 ("resume from last checkpoint, not from zero") be objectively verified? Is the verification method (e.g., compare record sets between interrupted and uninterrupted runs) specified? [Measurability, spec.md US4]

## Dependencies & Assumptions

- [ ] CHK029 Is the assumption that Scrapling's checkpoint mechanism prevents double-processing (but allows data loss of in-flight items) explicitly documented? [Assumption, Gap — plan.md §Constitution Check VI]
- [ ] CHK030 Is the dependency on Scrapling's CrawlerEngine for checkpoint semantics (pending queue only, not completed items) documented as a design constraint? [Dependency, Gap — plan.md §5]
- [ ] CHK031 Is the dependency on Scrapling's Scheduler.snapshot() for checkpoint serialization (excludes _inflight requests) documented? [Dependency, Gap — plan.md §5]
- [ ] CHK032 Is the assumption that historical response-size data (smallest-known-good per site) is available to calibrate the 500-byte threshold documented as unverified? [Assumption, Gap — contract/blocked-response.md]

## Requirement Ambiguities & Conflicts

- [ ] CHK033 Does plan.md §1:155-163 (showing `session_kwargs = {}` with `if site_key in (...):` conditional assignment) conflict with plan.md §2:182-198 (dict-of-factories pattern)? Is there an explicit note that §1 is pseudocode and §2 is binding? [Conflict, plan.md §1 vs §2]
- [ ] CHK034 Does the constitution claim that "checkpointing via crawldir is inherently idempotent" conflict with the actual behavior (no double-processing, but data loss of in-flight items)? [Conflict, constitution §IV vs plan.md §Constitution Check]
- [ ] CHK035 Is the term "scheduler interface" (FR-007) defined unambiguously — does it mean Scrapling's download_delay class attribute, or anyio.sleep() in start_requests(), or CrawlerEngine's internal scheduler? [Ambiguity, spec.md FR-007 vs plan.md §3]

## Non-Functional Requirements

- [ ] CHK036 Are performance requirements quantified for the crawl completion window (e.g., max time to complete all targets)? [Gap, spec.md Success Criteria]
- [ ] CHK037 Are reliability requirements specified for the checkpoint mechanism (e.g., max acceptable data loss on crash)? [Gap, spec.md Edge Cases: only says "start from beginning with warning"]
- [ ] CHK038 Is the global concurrency cap (max 2) specified as a hard limit that prevents resource exhaustion on the host? [Completeness, spec.md FR-010]

## Traceability

- [ ] CHK039 Does every Functional Requirement (FR-001 through FR-010) trace to at least one implementation task and one verification test? [Traceability, spec.md vs tasks.md]
- [ ] CHK040 Does every User Story (US1-US4) trace to at least one acceptance test scenario that is independently executable? [Traceability, spec.md User Scenarios vs tasks.md verification gates]
