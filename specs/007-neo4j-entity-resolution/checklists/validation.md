# Completion Validation Checklist: Neo4j Graph Schema & Entity Resolution

**Purpose**: Validate that the requirements (spec/plan/tasks) make the three completion gates — review-log coverage, MERGE-only relationship writes, and a count-proven idempotency run — explicit, measurable, and traceable BEFORE implementation is considered complete.

**Created**: 2026-08-03

**Feature**: [spec.md](../spec.md)

**Input gates (user must-haves)**:
1. Every fuzzy match, above or below threshold, appears in the review log with both company names and the numeric score.
2. No relationship is ever created via `CREATE` — confirm every relationship write uses `MERGE` keyed appropriately.
3. The idempotency test was actually run twice against identical input and the resulting node/relationship counts are pasted into the report, not just asserted.

## Review Log Coverage & Clarity

- [ ] CHK001 Are requirements explicit that EVERY fuzzy comparison — matched or not — is written to the review log? [Completeness, Spec §FR-006]
- [ ] CHK002 Do the log-entry requirements specify both company names AND the numeric score on every line? [Completeness, Spec §FR-006]
- [ ] CHK003 Is the review-log line schema specified exactly (timestamp, action, names, score, threshold, verdict) so any entry is verifiable? [Clarity, plan §5 / contracts/review-log-format.md]
- [ ] CHK004 Is below-threshold logging specified with the same rigor as above-threshold logging — never silently discarded? [Consistency, Spec §FR-006 vs Constitution Entity Resolution Transparency]
- [ ] CHK005 Is it unambiguous that phone-matched records do NOT generate fuzzy log entries? [Clarity, Spec §FR-006 / US2 Scenario 3]
- [ ] CHK006 Is the review-log-write-failure fallback defined (app-level log + surfaced failure, never silent)? [Edge Case, Spec §Edge Cases]
- [ ] CHK007 Is the logged `score` defined as the same metric used for the merge decision (token_sort_ratio) so the log is auditable against the decision? [Consistency, plan §4 / contracts/entity-resolution.md]

## MERGE-Only Relationship Writes

- [ ] CHK008 Is it explicitly required that every relationship write uses `MERGE` keyed on company+partner, never `CREATE`? [Completeness, Spec §FR-007]
- [ ] CHK009 Is the merge key for each relationship type specified (company+category, company+city, company+source)? [Clarity, plan §3 Q4–Q6]
- [ ] CHK010 Does the spec cover the repeat-scrape scenario proving no duplicate relationship is created? [Scenario Coverage, Spec §US1 Scenario 3]
- [ ] CHK011 Is the "no `CREATE` for relationships" rule consistent across FR-007, FR-009, and Constitution IV? [Consistency]
- [ ] CHK012 Are the identity keys unambiguous — Company on `dedup_key`, Source/Category/City on `name` — so keyed MERGEs are well-defined? [Clarity, Spec §FR-001/FR-007]
- [ ] CHK013 Is it specified that legacy relationship types (HAS_PHONE/HAS_EMAIL/HAS_WEBSITE/BELONGS_TO) are excluded from new writes? [Coverage, Spec §FR-013]

## Idempotency Proof — Actual Counts in the Report

- [ ] CHK014 Is idempotency stated as a demonstrated re-run of identical input (twice), not a single write? [Completeness, Spec §FR-009 / Constitution IV]
- [ ] CHK015 Does the requirement demand recording and pasting ACTUAL Run-1 and Run-2 counts in the report, not merely asserting equality? [Measurability, Gap, plan §6]
- [ ] CHK016 Is the full set of counts to compare enumerated (Company/Category/City/Source + LISTED_IN/LOCATED_IN/SOURCED_FROM)? [Completeness, plan §6]
- [ ] CHK017 Is "identical input" defined unambiguously (fixed fixture, same day)? [Clarity, Gap]
- [ ] CHK018 Are the spot-check invariants specified (first_seen stable across runs; sources arrays deduplicated)? [Edge Case, plan §6]
- [ ] CHK019 Does run reporting (FR-010) align with the idempotency proof (SC-002 delta=0)? [Consistency]
- [ ] CHK020 Is the success criterion quantified — exactly zero change in each count? [Measurability, Spec §SC-002]

## Traceability & Gate Independence

- [ ] CHK021 Do the three completion gates map to explicit requirement/acceptance IDs so each gate is traceable to the spec? [Traceability, Gap]
- [ ] CHK022 Are the three gates defined at requirement level so a reviewer can gate on them independently of implementation? [Completeness, Gap]

## Notes

- This checklist validates the QUALITY of the completion criteria in the requirements, not the implementation itself.
- Check items off as completed: `[x]`. Add findings/evidence inline (e.g., pasted Run-1/Run-2 count tables for CHK015).
- Companion checklist: `requirements.md` (spec quality, 16/16 passing).
- Must-have 1 → CHK001–CHK007; must-have 2 → CHK008–CHK013; must-have 3 → CHK014–CHK020; cross-cutting → CHK021–CHK022.
