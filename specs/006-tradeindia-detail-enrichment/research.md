# Research: TradeIndia Detail-Page Enrichment

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

Grounds the plan in live evidence gathered at planning time. All decisions below are grounded in either (a) live network observation of TradeIndia or (b) the existing enrichment/cap code already in the repo — never in assumed markup.

## R0. Live observation (evidence)

- `https://www.tradeindia.com/robots.txt` returns `200` (2,090 B). Company/product/detail paths are NOT in the disallow list; disallowed paths (banner, login, inquiry basket, `/suppliers/`, `/search/`, `*?tilt=*`, etc.) must not be fetched. Detail-page enrichment targets company detail pages, which are not disallowed.
- `https://www.tradeindia.com/` returns `200`, ~1.3 MB, but the HTML is a client‑rendered Next.js shell (`_next/static/...`); the raw HTML contains NO listing cards, NO company detail hrefs, and NO contact fields. Listing and detail content loads via client-side JS/WASM/XHR after first render.
- Implication: a plain HTTP fetch (FetcherSession) cannot surface the detail URL or the phone/email markup. A rendered capture (StealthyFetcher headless browser) is REQUIRED to obtain the detail page's actual structure. This matches the KG and `src/scraper/targets.py` note that TradeIndia is "entirely JS API‑driven".

## Decision 1 — Exact detail-page URL resolution (spec FR‑001/FR‑003, req #1)

- **Question resolved**: does the existing CSS-extracted listing card already carry the detail URL, or is a new selector needed?
- **Decision**: The raw listing HTML does not carry a stable, parseable detail href at static fetch time (client‑rendered). In the RENDERED DOM the card's company name is an `<a>` located by the existing parsers (`.company-url`, `a[href]`, `h3.company-name` — see `_parse_ti_from_css` / `_parse_ti_via_similarity`); those parsers read only `name.text` and **drop the `href`**. Therefore a NEW extraction step IS needed: capture the `href` attribute of the existing company-anchor selector and resolve it against the listing URL before storing it as the per-record detail URL.
- **Rationale**: Uses the anchor UI the parsers already rely on; no second crawl pass to find links is needed. Keeps one request per record to the detail page.
- **Alternatives considered**:
  - Harvesting detail hrefs via a separate `/links` pass on the listing — rejected (extra listing requests, no benefit since the anchor is already in the card).
  - Using XHR/capture for a JSON API detail route — rejected for v1; the rendered-anchor approach is simpler and matches the existing pip-line.
- **Condition**: the exact anchor selector/attribute is confirmed against ONE rendered detail page during the inspection task (D2) and may be narrowed (`.company-url` vs `a[href]`) only on real evidence.

## Decision 2 — Exact per-field extraction approach (FR-006, SC-006, req #2)

- **Decision**: field extraction MUST be finalized from a real rendered capture, never from assumption, per clarification Q1 (report the mechanism first; do not guess-and-implement) and Q2 (single bounded interaction). The concrete selectors/regexes are therefore bound by the inspection report produced by the first task below. A decision matrix is fixed in advance:
  - mechanism == plain text / `tel:` / `mailto:` → auto-proceed (low risk): phone from `tel:`/plain text, email from `mailto:`/text, website from the company website anchor; reuse existing `_extract_phone_from_html`, `_extract_emails_from_text`, `_extract_websites_from_text` (respecting `KNOWN_SITE_WIDE_*`, `DIRECTORY_DOMAINS`).
  - mechanism == JS-reveal button → perform ONE bounded click+wait (Q2); if no DOM change, mark field unavailable.
  - mechanism == obfuscated encoding → de-obfuscate ONLY in ways literally evidenced in the inspected page; else unavailable.
  - mechanism == login-gate → report; mark contact fields unavailable.
  - **Hard rule**: no selector/regex is committed until the inspection report names the mechanism and quotes the evidence; the report is recorded in `research.md` with the capture saved to `debug_output/tradeindia_detail_inspection.html` and surfaced for the Q1 confirmation step.
- **Rationale**: honors the constitutional "fail loudly, never silently degrade" (V) and the clarified evidence-gate (Q1).
- **Alternatives considered**: reusing IndiaMART's httpx/plain-HTML parser verbatim — rejected because TradeIndia does not serve contact data in static HTML (R0).

## D3 — Exact enrichment_unavailable logging format (FR-5, req #3)

- **Format (one log line per field, per needy record)**, matching the literal string required:
  `enrichment_unavailable: <field>` — where `<field>` is lowercase `phone`, `email`, or `website`.
- Full line example (%@ precedent): `enrichment_unavailable: phone (record="Acme Textiles", url="<detail>")`.
- A record may emit up to 3 lines (one per unfillable field); a record with an already-matched phone+email is skipped entirely (no lines) — idempotent per constitution IV.
- **Rationale**: greppable, per-field, preserves the exact phrase; `error_type` for the domain counter is unaffected (these are per-FIELD unavailability, not scrape errors).

## D4 — Rate-limit integration with Phase-1 per-domain throttling (req #4)

- Verified in current code: `LeadSpider.on_close` (`src/scraper/spider.py:880`) already collects `needy` detail targets, applies `cap_guard = self._cap*for(domain, daily_cap)` (FR-008 daily per-domain hard cap), truncates to `needy[:max_detail]` (needs the config cap, default 20), and calls `_enrich_from_detail_pages(session=None, ..., cap_guard)`.
- `_enrich_from_detail_pages` (`src/scraper/targets.py:323`) consumes ONE capacity unit per detail-page request via `cap_guard()` and applies a 0.5s wait per fetch; it skips further detail pages once the guard denies (logs "Daily cap reached — skipping remaining detail-page enrichment").
- **Therefore additional detail-page requests already count against the same per-domain daily budget as pagination**: no growth in request volume beyond the cap. The only work this feature adds: (1) the per-record detail URL from D1, and (2) the field extraction from D2; both slot into the existing on_close enrichment step.
- Residual risk noted: the `needy[:max_detail]` cap is a per-run slot; the daily guard still caps across run. Both are to be matched by tests.

## Open items (deferred to a run-time report, not guess-able now)

- D2 exact selectors/regex for each field → those are the deliverable of the inspection-report gate (first implementation task), per home FR-003 / Q1/Q2. Confidence they exist: high, once a rendered page is captured; the bind rules are captured in this doc.
- The concrete phrase/class of the phone container (whether it needs the reveal click) → same gate.