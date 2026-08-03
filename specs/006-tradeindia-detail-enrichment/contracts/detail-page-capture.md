# Contract: TradeIndia Detail-Page Capture (inspection report gate)

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](../spec.md)

## Purpose (evidence gate)

A one-time, implementation-time evidence step that resolves FR-003 / clarification Q1: before any extraction selector or regex is committed, a real TradeIndia detail page MUST be captured with a rendered browser, saved to disk, and its protection mechanism reported. Selectors/regexes are written only from the report's evidence, never guessed (research D2).

## Preconditions

- The detail page must pass `is_robots_allowed` (Constitution I). Research R0 shows detail pages are not robots-disallowed, but each URL is still checked.
- No new credentials: reuse the existing env-only proxy / StealthyFetcher config.

## Contract (first implementation task)

1. Take the first company detail URL resolved by the detail-page-URL contract ([/contracts/detail-page-url.md](./contracts/detail-page-url.md)).
2. Render it with `StealthyFetcher` (headless, `solve_cloudflare=True`, `load_dom=True`, `network_idle=True`), and let the client-rendered content settle — the page is a Next.js client-rendered app (research R0).
3. Save the rendered DOM HTML to `debug_output/tradeindia_detail_inspection.html`.
4. Report the mechanism as exactly one of: `plain text` | `tel:`/`mailto:` links | `js-reveal-button` | `obfuscated-encoding` | `login-gate`, quoting the actual markup observed for phone, email, and website.

## Outcomes

| Mechanism | Next action |
|-----------|-------------|
| plain text or `tel:` / `mailto:` links | auto-proceed — bind selectors from the captured evidence (research D2) |
| js-reveal-button / obfuscated-encoding / login-gate | STOP → report the mechanism to the user and confirm the extraction approach before writing selectors (clarification Q1 hybrid) |

## Done / gate

- [X] `debug_output/tradeindia_detail_inspection.html` exists and is non-empty.
- [X] Mechanism reported with quoted evidence for each field.
- [X] For non-trivial mechanisms, the user confirmed the approach before selectors were written.