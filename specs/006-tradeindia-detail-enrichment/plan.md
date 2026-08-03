# Implementation Plan: TradeIndia Detail-Page Enrichment

**Branch**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-tradeindia-detail-enrichment/spec.md`

## Summary

Enable TradeIndia detail-page enrichment (currently effectively disabled) with a configurable per-run cap defaulting to 20. The plan grounds the extraction in a real rendered TradeIndia detail page (evidence-gate per FR-003), extracts phone/email/website, logs `enrichment_unavailable: <field>` per unfillable field (FR-005/SC-002), and reuses the existing Phase-1 per-domain daily-cap enforcement so the extra requests cannot blow the daily budget (FR-007/SC-003). Fill rates are reported per domain (FR-010/SC-004). Research evidence in [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12 (repo std), Scrapling 0.4.12 (StealthyFetcher headless browser for the rendered capture)

**Primary Dependencies**: Scrapling (`StealthyFetcher`, `FetcherSession`), existing `src/scraper/targets.py` extraction/`RawRecord`, `src/scraper/spider.py` on_close enrichment + `_cap_guard_for` daily-cap, `httpx` (only fallback; not primary for TI)

**Storage**: no new storage — enrichment mutates `RawRecord` in memory; `_fill_rates` already recomputed in `on_close`

**Testing**: pytest (repo standard). Existing suites: `tests/test_spider.py`, `tests/test_targets.py`. New: detail-URL capture, log-format, cap-guard, fill-rate tests.

**Target Platform**: Linux runner (CI) + Windows local dev

**Project Type**: scraper service (existing `src/scraper` pipeline)

**Performance Goals**: bounded per-run detail requests (default 20); 0.5s pacing between detail fetches (existing); never exceed per-domain daily cap

**Constraints**: constitution — Robots.txt compliance (I), idempotent (IV), fail loudly (V), non-destructive enrichment (never overwrite), JS-reveal single bounded attempt (FR-006/Q2), never guess-and-implement selectors (FR-003/Q1).

**Scale/Scope**: 20 detail pages per TradeIndia run (default), counted against `www.tradeindia.com` daily cap

## Constitution Check

*GATE must pass before research; re-check after design.*

| Gate | Result | Evidence |
|------|--------|----------|
| I. Robots.txt compliance | PASS | research R0 confirms detail pages not disallowed; plan will reuse `is_robots_allowed` before any detail fetch |
| II. No LinkedIn | PASS (N/A) | no LinkedIn path involved |
| III. Credential security | PASS | no new credentials; existing env-only proxy |
| IV. Idempotent operations | PASS | detail enrichment only fills missing fields; skips records already phone+email; re-run stable (§D3) |
| V. Resilient / fail loud | PASS | `enrichment_unavailable:<field>` per unfillable field; per-site try/except; detail cap/guard noise logged |
| VI. Observability | PASS | fill-rate line + enrichment_unavailable + (existing) per-domain cap summary |
| VII. Scope fidelity | PASS | only TradeIndia detail enrichment; JD/IM untouched (their `max_detail_pages` stays 0) |

No violations; no complexity tradeoff table needed.

## Project Structure

### Documentation (this feature)

```text
specs/006-tradeindia-detail-enrichment/
├── plan.md              # this file
├── research.md          # Phase 0 output (live evidence + decisions)
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (NOT created by plan)
```

### Source Code (repository root)

```text
src/scraper/
├── targets.py           # TradeIndia parsers: capture detail href (D1); extraction (D2); enrichment_unavailable (D3)
├── spider.py            # on_close already stages detail enrichment; only wire D1 hrefs + (if needed) per-field logging
└── engine.py            # robots fetch (unchanged)
config/targets.yaml      # TradeIndia max_detail_pages: 20 (cap key), already present
tests/
├── test_spider.py       # detail-URL capture, cap-guard integration, fill-rate
├── test_targets.py      # extraction, log-saturation gating, unavailable logging
└── test_workflows.py    # (no workflow change expected)
debug_output/            # inspection capture: tradeindia_detail_inspection.html
```

**Structure Decision**: single-project layout already used by the repo; changes confined to `src/scraper/{targets,spider}.py`, `config/targets.yaml`, and tests.

## Project Phases

### Phase 0 — Research (done)

[research.md](./research.md) — live-observed: robots OK; page is client-rendered; detail anchor href currently dropped (req #1 resolved); field selectors gated on a rendered capture (D2); log format defined (D3); cap integration confirmed existing (D4).

### Phase 1 — Design (this command)

Outputs: [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).

### Phase 2 — Implementation

See `/speckit.tasks` (NOT produced here). The first implementation task MUST be the inspection-report gate: capture one rendered TradeIndia detail page (see [contracts/detail-page-capture.md](./contracts/detail-page-capture.md)), save to `debug_output/tradeindia_detail_inspection.html`, report the mechanism, then and only then commit the exact field selectors into `targets.py` per the matrix in research D2 / [contracts/enrichment-extraction.md](./contracts/enrichment-extraction.md).

## Complexity Tracking

(No constitution violations to justify — table omitted.)