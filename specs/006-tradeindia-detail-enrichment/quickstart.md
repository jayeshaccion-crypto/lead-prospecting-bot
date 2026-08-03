# Quickstart: Validate TradeIndia Detail-Page Enrichment

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

This is a validation/run guide. For full specs, see [data-model.md](./data-model.md) and the [contracts](./contracts/).

## Prerequisites

- Python 3.12, repo deps installed (`pip install -e ".[dev]"`).
- TradeIndia enabled in `config/targets.yaml` with a `max_detail_pages` cap (default 20) — value already present (20).
- A browser engine available for `StealthyFetcher` (needed for the rendered capture).
- Proxy env (env-only credentials) as configured; no new secrets.

## 1. Inspection gate (must precede selector work — never skipped)

```bash
# after the D1 detail-URL resolution is implemented
python - <<'PY'
# render first TI detail page, save raw + report mechanism
PY
```

Steps (contract [detail-page-capture.md](./contracts/detail-page-capture.md)):
1. Resolve the first company detail URL from a rendered listing.
2. Render and save to `debug_output/tradeindia_detail_inspection.html`.
3. Record the mechanism (plain text / tel-mailto / js-reveal / obfuscated / login) with quoted evidence.
4. If not plain/tel-mailto → STOP, report, confirm the extraction approach (Q1) before any selector is written.

## 2. Unit tests (`pytest`)

```bash
python -m pytest tests/test_spider.py tests/test_targets.py -q
```

Cover (contracts):
- `detail-URL` captured from anchor `href` + resolved vs listing host; malformed → None.
- `enrichment_unavailable: phone|email|website` literal lines per field (contract [enrichment-extraction](./contracts/enrichment-extraction.md)).
- Skip records already having phone+email (idempotence).
- Site-wide values (`helpdesk@tradeindia.com`, `01146710423`) rejected.
- Non-destructive: filled fields never overwritten.
- JS-reveal: at most one click+wait, no retry (SC-007).
- Cap: with `max_requests_per_day` exhausted, no detail request is issued and it is logged (contract [enrichment-rate-limiting](./contracts/enrichment-rate-limiting.md)).

## 3. End-to-end / run summary

```bash
python -m src --pipeline --dry-run   # or run.py path used in CI
```

Expected outcome — `on_close` logs (already present, now fed by the new detail URLs):
```
TradeIndia: enriching N records via detail pages (max 20)
enrichment_unavailable: phone (record="...", url="...")
...
TradeIndia: N records, phone=X/N, email=Y/N, website=Z/N
Daily request budget used per domain: www.tradeindia.com=K
```
- No domain exceeds its daily cap (SC-003).
- Fill-rate line present for TradeIndia (SC-004).

## Definition of done (reminder)

- [X] debug output + mechanism report captured (gate).
- [X] `pytest` green for the new/updated suites.
- [X] Fill rates correct; no per-domain cap breach; `enrichment_unavailable` lines grep-clean.