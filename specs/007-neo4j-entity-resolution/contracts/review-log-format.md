# Contract: Fuzzy-Match Review Log Format

**Feature**: Neo4j Graph Schema & Entity Resolution
**Version**: 1.0 | **Date**: 2026-08-03
**Consumers**: `src/graphdb/client.py:_write_fuzzy_review` (writer), operators (manual spot-check), tests.

## Location

`debug_output/fuzzy_matches.log` (flat file, gitignored directory). Append-only; never truncated by the writer.

## Line format

One record per fuzzy comparison, **one line**, pipe-separated (`|`), UTF-8:

```
timestamp|action|incoming_name|incoming_normalized|candidate_name|candidate_normalized|score|threshold|verdict
```

A header line with the same field names is written when the file is first created.

## Field definitions

| Field | Type | Meaning |
|-------|------|---------|
| `timestamp` | ISO 8601 UTC | When the comparison was made |
| `action` | `FUZZY_MATCH` | Always this value (every comparison is logged) |
| `incoming_name` | string | Display name of the incoming record |
| `incoming_normalized` | string | `normalize_company_name(incoming_name)` |
| `candidate_name` | string | Display name of the existing graph candidate |
| `candidate_normalized` | string | `normalize_company_name(candidate_name)` |
| `score` | float, 1 decimal | `token_sort_ratio`, 0.0–100.0 |
| `threshold` | int | In-effect `fuzzy_match_threshold` for this run |
| `verdict` | `matched` | score ≥ threshold |
|         | `not_matched` | score < threshold |

## Rules

- **Every** fuzzy comparison is written — above and below threshold (below-threshold comparisons must not vanish without trace, Constitution §Entity Resolution Transparency).
- Phone-keyed merges are **not** written to this file (they are logged at INFO level instead).
- Names are written verbatim; the fields are pipe-separated, so a name containing `|` is escaped as `\|`.

## Example

```
timestamp|action|incoming_name|incoming_normalized|candidate_name|candidate_normalized|score|threshold|verdict
2026-08-03T12:00:00.000Z|FUZZY_MATCH|Codetrex Infotech Pvt. Ltd.|codetrex infotech|Codetrex Infotech|codetrex infotech|100.0|90|matched
2026-08-03T12:00:00.100Z|FUZZY_MATCH|Basudeb It Solution|basudeb it solution|Hub It Infotech|hub it infotech|40.0|90|not_matched
```

## Acceptance tests

- `tests/test_graphdb.py`: writer produces exactly this format; below-threshold comparisons appear with `verdict=not_matched`; append (no truncation) across calls.
