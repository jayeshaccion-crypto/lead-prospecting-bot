# Contract: Entity Resolution

**Feature**: Neo4j Graph Schema & Entity Resolution
**Version**: 1.0 | **Date**: 2026-08-03
**Consumers**: `src/graphdb/client.py` (`upsert_company` / `write_companies`), `src/pipeline.py` (`_write_to_neo4j`).

## Input

A record dict with at least: `company_name`; optional `phone`, `email`, `website`, `address`, `industry_code`, `source_url`, `city_slug`, `category_slug`, `lead_score`, `lead_score_breakdown`.

## Algorithm (run before any graph write for the record)

1. **Deterministic phone pass** — if `phone` present and its digit-only form is ≥ 10 digits, match `Company` by `dedup_key = _dedup_key(name, phone)` (last-10-digits key). A hit ⇒ `match_type = "phone"`.
2. **Fuzzy name pass** — only when the phone pass found nothing. Scope candidates by `Company.normalized_name STARTS WITH prefix` (first 3 chars, or all if shorter). For each candidate compute `score = float(fuzz.token_sort_ratio(norm, candidate_norm))` and write a review-log line. Keep the best candidate with `score >= float(threshold)`; tie-break by higher score, then lexicographically smaller `company_name`. A winner ⇒ `match_type = "fuzzy"` with its `dedup_key`.
3. **Write** — MERGE the Company by the resolved `dedup_key` (matched node's key, or a freshly computed `_dedup_key(name, phone, website)` when no match ⇒ `match_type = None`, i.e. created), then MERGE LISTED_IN / LOCATED_IN / SOURCED_FROM per the graph-schema contract.
4. **Classify** — `created` when `match_type is None`; `merged_phone` / `merged_fuzzy` otherwise.

## Threshold

- Source: `src.config.get_fuzzy_match_threshold()` — top-level `fuzzy_match_threshold` from `config/targets.yaml`, default `90`.
- Comparison: `score >= float(threshold)` (float compare).
- The in-effect integer threshold is written to every review-log line.

## Determinism guarantees

- Same normalized input + same existing graph ⇒ same resolved `dedup_key`, same `match_type`, same merged properties.
- Tie-break is total: (score, candidate_name) — no first-match-order dependence.
- `first_seen` is never modified after creation; `sources` appended only if absent; relationship edges MERGEd on their key.

## Logging

- Every fuzzy comparison → review log file `debug_output/fuzzy_matches.log` (see [review-log-format.md](./review-log-format.md)), including below-threshold ones.
- Phone matches → INFO: `Entity resolution: phone match for '<incoming>' -> existing '<name>' (phone=<last10>)`.
- Run totals (INFO): created / merged_phone / merged_fuzzy / total graph size (node + relationship counts).

## Acceptance tests

- `tests/test_graphdb.py`: normalization table; `_dedup_key` determinism; threshold default/override; fuzzy selection + tie-break with stubbed candidates; review-log format.
- `tests/test_graphdb_idempotency.py`: two identical runs ⇒ identical counts (see [quickstart.md](../quickstart.md)).
