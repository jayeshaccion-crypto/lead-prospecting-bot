# Requirements Quality Checklist: JustDial Three-Mode Proxy Routing

**Purpose**: "Unit tests for English" — validate the quality, clarity, and completeness of the feature requirements (spec + plan + contracts), NOT the implementation.
**Created**: 2026-07-31
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md) | [contracts/](../contracts/)

**Focus areas**: Credential security, once-daily idempotency gate, fail-loud disposition, edge-case coverage, robots.txt compliance.
**Depth**: Standard review | **Audience**: Author + PR reviewer

## Requirement Completeness

- [x] CHK001 Are requirements defined for how distinct Webshare IPs are enumerated when only `WEBSHARE_PROXY_URL` (single rotating endpoint) is set and no `WEBSHARE_API_KEY` exists? [Gap, Spec §FR-004, research.md R3]
- [x] CHK002 Is the probe URL for the ASN test specified (or deterministically derivable from config) rather than left open at implementation time? [Clarity, Spec §FR-010]
- [ ] CHK003 Is a timeout requirement defined for each ASN probe request (max duration per attempt)? [Gap, NFR, Spec §FR-004]
- [x] CHK004 Are requirements defined for the exact behavior when the probe request itself errors mid-way (connection reset, timeout) vs. returns a body? [Completeness, Spec §Edge Cases, contracts/asn-test.md]
- [ ] CHK005 Are requirements defined for what happens when the persisted flag write (`__jd_asn_test`) itself fails (disk error)? [Gap, Exception Flow, Spec §FR-009]
- [x] CHK006 Does the spec require the three modes to be mutually exclusive and cover all env states (no undefined combination)? [Completeness, Spec §FR-001, contracts/jd-mode.md]

## Requirement Clarity

- [x] CHK007 Is the definition of Z ("succeeded") unambiguous in the spec — literal complement of blocked (body ≥ 500B) vs. requiring a real listing selector match? [Ambiguity, Spec §FR-005, research.md R5]
- [ ] CHK008 Is the "once per calendar day" boundary anchored to a specific timezone (UTC vs. local server time)? [Ambiguity, Spec §FR-009, data-model.md]
- [x] CHK009 Is "full page depth, same as IndiaMART/TradeIndia" precisely defined (which config setting drives it — `pages` / `SCRAPE_FULL_PAGES`)? [Clarity, Spec §FR-002]
- [x] CHK010 Is the term "distinct proxy IP" defined (dedup key — host, or server|username)? [Clarity, Spec §FR-004, research.md R3]
- [x] CHK011 Is the verdict log format specified as an exact string (not an approximation) including the `X/10` literal semantics when pool < 10? [Clarity, Spec §FR-005, contracts/summary-lines.md]

## Requirement Consistency

- [x] CHK012 Does the CONCLUSION line wording in the spec/contract match everywhere — including superseding the old "Residential proxy tier required." text? [Consistency, Spec §FR-006, contracts/summary-lines.md]
- [x] CHK013 Do the mode display labels (residential / datacenter-ASN-test / no-proxy) agree across FR-008, data-model.md, and contracts/summary-lines.md? [Consistency, Spec §FR-008]
- [x] CHK014 Do FR-003 (no crawl in datacenter mode), FR-009 (once-daily), and the existing in-memory `_jd_tested` flow (tasks.md T013) agree that no category/city expansion occurs in datacenter mode? [Consistency, Spec §FR-003, tasks.md]
- [x] CHK015 Is the "blocked" definition consistent between the existing `is_blocked()` contract (blocked-status superset + 200/<500B) and the ASN test's Y tally (body < 500B or error)? [Consistency, Spec §FR-005, contracts/blocked-response.md (003), contracts/asn-test.md]
- [x] CHK016 Are success criteria SC-002 and SC-003 consistent with each other and with FR-004/FR-009 (≤10 probe requests, at most once daily)? [Consistency, Spec §Success Criteria]

## Acceptance Criteria Quality

- [x] CHK017 Can SC-001 (full page depth) be objectively verified without implementation knowledge (page/request counts per category)? [Measurability, Spec §SC-001]
- [x] CHK018 Is SC-002 (≤10 ASN requests, zero crawl) quantifiable and checkable from run logs? [Measurability, Spec §SC-002]
- [x] CHK019 Is SC-003 (at-most-once across two same-day runs) verifiable end-to-end via the persisted flag? [Measurability, Spec §SC-003]
- [x] CHK020 Is every acceptance scenario in US1–US3 written as Given/When/Then with observable outcomes? [Acceptance Criteria, Spec §User Scenarios]
- [x] CHK021 Can "explicit warning" in no-proxy mode (FR-007) be verified as a distinct, observable log/error signal? [Measurability, Spec §FR-007]

## Scenario Coverage

- [x] CHK022 Are requirements defined for the alternate flow where the Webshare API call fails (network, bad key, rate limit) and the pool degrades to empty? [Coverage, Spec §Edge Cases, research.md R7]
- [x] CHK023 Are requirements defined for the recovery/next-day flow after the flag auto-clears on date rollover? [Coverage, Spec §Edge Cases, data-model.md]
- [x] CHK024 Are requirements defined for the combination where residential var is set AND the datacenter pool is present (residential wins, no test)? [Coverage, Spec §US1.2, contracts/jd-mode.md]
- [x] CHK025 Are requirements defined for manual re-runs / `workflow_dispatch` on the same day (flag honored, no repeat)? [Coverage, Spec §US2.2, tasks.md T003]
- [ ] CHK026 Are requirements defined for the scenario where the probe completes but the run is interrupted before the flag write persists? [Gap, Exception Flow, Spec §FR-009]
- [x] CHK027 Is the partial-failure scenario covered where SOME probes succeed (Z > 0) and the CONCLUSION line must NOT fire? [Coverage, Spec §US2.4]

## Edge Case Coverage

- [x] CHK028 Is the empty-pool case (datacenter pool present but zero distinct IPs) handled in requirements without crashing? [Edge Case, Spec §Edge Cases]
- [x] CHK029 Is the single-IP pool case specified (X=1, verdict line still emitted)? [Edge Case, Spec §Edge Cases]
- [x] CHK030 Is the day-boundary case (test at 23:59, next run 00:01) specified as a new day = new test? [Edge Case, Spec §Edge Cases]
- [x] CHK031 Is a whitespace-only `RESIDENTIAL_PROXY_URL_JUSTDIAL` explicitly defined as "treated as unset"? [Edge Case, Spec §US1.3, FR-001]
- [x] CHK032 Is the robots.txt-disallowed probe URL case defined (probe skipped, `RobotsDisallowed` logged)? [Edge Case, Spec §FR-010, contracts/asn-test.md]

## Non-Functional Requirements

- [x] CHK033 Are credential-security requirements for the ASN test explicit in the spec (proxy host redaction, no `user:pass` in logs/verdicts)? [Gap, Security, Spec §Assumptions, constitution III]
- [x] CHK034 Is the bounded-request budget (≤10/day) specified as an explicit operational constraint, not an implementation detail? [NFR, Spec §FR-004]
- [x] CHK035 Are reliability requirements defined for the probe (fail without crashing the run) at the requirements level? [NFR, Spec §Edge Cases, research.md R7]
- [x] CHK036 Are observability requirements defined so each mode's disposition is visible in run logs (not just the summary line)? [Gap, Observability, Spec §FR-007/FR-008]

## Dependencies & Assumptions

- [x] CHK037 Is the assumption that `_determine_jd_mode()` is the single source of truth for mode selection documented and validated? [Assumption, Spec §Assumptions, research.md R1]
- [x] CHK038 Is the dependency on the existing `data/request_counts.json` state file (and its date-reset semantics) documented? [Dependency, Spec §Assumptions, data-model.md]
- [x] CHK039 Is the dependency on `scrapling.fetchers.ProxyRotator` (vendored submodule) documented? [Dependency, research.md R3, contracts/asn-test.md]
- [x] CHK040 Is the assumption that no new env var (`PROXY_URL_JUSTDIAL`) is introduced explicitly stated and audited in requirements? [Assumption, Spec §Assumptions, contracts/jd-mode.md]

## Ambiguities & Conflicts

- [x] CHK041 Is the deferral of the stricter Z definition (listing-selector match, clarify Q2 Option A) explicitly recorded so reviewers don't treat it as an accidental omission? [Ambiguity, research.md R5, tasks.md Notes]
- [x] CHK042 Is there any conflict between spec FR-008 mode labels and the internal `_jd_mode` values (`datacenter` vs. `datacenter-ASN-test`) that must be resolved at implementation? [Conflict, Spec §FR-008, contracts/summary-lines.md]
- [x] CHK043 Are requirement IDs (FR-###, SC-###, US#) consistent and referenced across spec, plan, contracts, and tasks for full traceability? [Traceability, Spec §Requirements]
- [x] CHK044 Is the exact ASN verdict string (FR-005) verified to be byte-identical between spec, plan, contracts, and tasks to prevent drift? [Consistency, Spec §FR-005, contracts/summary-lines.md]

## Notes

- This checklist validates the REQUIREMENTS quality (completeness/clarity/consistency/coverage) — it is not an implementation test suite.
- Items marked [Gap] should trigger a spec or contract update before implementation begins.
- Resolved by re-audit (2026-07-31) after remediation: CHK007 (R5 explicit Z definition), CHK001 (asn-test.md/R3 enumeration), CHK033 (summary-lines.md redaction + constitution III), plus all consistency/coverage items.
- Remaining gaps (intentional, recorded for future amendment): CHK003 (per-probe timeout NFR), CHK005 (flag-write failure), CHK008 (timezone anchor for "calendar day"), CHK026 (interrupt before flag write persists).
- Feature already has a `requirements.md` spec-quality gate (from `/speckit.specify`); this checklist is the deeper requirements-quality audit.
