# Contract: Entity Resolution

**Feature**: Neo4j Graph Schema & Entity Resolution
**Version**: 1.1 | **Date**: 2026-08-03
**Consumers**: `src/graphdb/client.py` (`upsert_company` / `write_companies`), `src/pipeline.py` (`_write_to_neo4j`).

## Input

A record dict with at least: `company_name`; optional `phone`, `email`, `website`, `address`, `industry_code`, `source_url`, `city_slug`, `category_slug`, `lead_score`, `lead_score_breakdown`.

## Normalization

Two functions — they MUST NOT be conflated (H1):

- `normalize_company_name(name)` — **display/dedup-key normalization**: lowercase, strip punctuation, remove legal suffixes AND business descriptors (`technologies`, `solutions`, `services`, `systems`, `group`, `industries`, `enterprise(s)`), collapse whitespace. Used for the stored `Company.normalized_name`, the fuzzy-prefix scan, and name-based `_dedup_key`.
- `fuzzy_normalize_company_name(name)` — **fuzzy-scoring normalization**: lowercase, strip punctuation, remove ONLY legal suffixes (`pvt`, `ltd`, `llp`, `private limited`, `opc`, `inc`, `corp`, `corporation`, `llc`, `limited`, `co`, `company`). Descriptor words are KEPT so distinct companies differing only by a descriptor (e.g. "Pinnacle It Solutions" vs "Pinnacle It Services") score below threshold and never fuse.

## Algorithm (run before any graph write for the record)

1. **Deterministic phone pass** — if `phone` present and its digit-only form is ≥ 10 digits, match `Company` by `dedup_key = _dedup_key(name, phone)` (last-10-digits key). A hit ⇒ `match_type = "phone"`.
2. **Fuzzy name pass** — only when the phone pass found nothing. Scope candidates by `Company.normalized_name STARTS WITH prefix` (first 3 chars, or all if shorter). For each candidate compute `score = float(fuzz.token_sort_ratio(fuzzy_normalize_company_name(incoming), fuzzy_normalize_company_name(candidate)))` — **not** the display normalization — and write a review-log line. Keep the best candidate with `score >= float(threshold)`; tie-break by higher score, then lexicographically smaller `company_name`. A winner ⇒ `match_type = "fuzzy"` with its `dedup_key`.
3. **Write** — MERGE the Company by the resolved `dedup_key` (matched node's key, or a freshly computed `_dedup_key(name, phone, website)` when no match ⇒ `match_type = None`, i.e. created), then MERGE LISTED_IN / LOCATED_IN / SOURCED_FROM per the graph-schema contract.
4. **Classify** — `created` when `match_type is None`; `merged_phone` / `merged_fuzzy` otherwise.

## Threshold

- Source: `src.config.get_fuzzy_match_threshold()` — top-level `fuzzy_match_threshold` from `config/targets.yaml`, default `90`.
- Comparison: `score >= float(threshold)` (float compare).
- The in-effect integer threshold is written to every review-log line.

## Determinism guarantees

- Same normalized input + same existing graph ⇒ same resolved `dedup_key`, same `match_type`, same merged properties.
- Tie-break is total: (score, candidate_name) — no first-match-order dependence.
- `first_seen`, `company_name`, `normalized_name` are never modified after creation (ON CREATE only — M1); `last_seen`/`lead_score` updated on every match; `sources` appended only if absent; relationship edges MERGEd on their key.
- Unknown `source_url` ⇒ `source_name = None`; an unknown source is never appended to `sources` and never creates a `SOURCED_FROM` edge (M6).

## Logging

- Every fuzzy comparison → review log file `debug_output/fuzzy_matches.log` (see [review-log-format.md](./review-log-format.md)), including below-threshold ones. `|` inside a field is escaped as `\|` (L3).
- Phone matches → INFO: `Entity resolution: phone match for '<incoming>' -> existing '<name>' (phone=<last10>)`.
- Run totals (INFO): created / merged_phone / merged_fuzzy / total graph size (node + relationship counts).

## Acceptance tests

- `tests/test_graphdb.py`: normalization table; legal-suffix-only fuzzy normalization (H1) — descriptor pairs < 90, legal variants = 100; `_dedup_key` determinism; threshold default/override; fuzzy selection + tie-break with stubbed candidates; review-log format + escaping.
- `tests/test_graphdb_idempotency.py`: two identical runs ⇒ identical counts (see [quickstart.md](../quickstart.md)).
