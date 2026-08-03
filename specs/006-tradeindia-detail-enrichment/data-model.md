# Data Model: TradeIndia Detail-Page Enrichment

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

## Entities

### RawRecord (TradeIndia) — extended, no schema change
Represents a scraped TradeIndia company. Enrichment mutates the existing in-memory record; no persistent column is added.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| company_name | str | listing parser | existing |
| website / email / phone | str? | listing + detail enrichment | enrichment fills ONLY when missing (BR non-destructive) |
| address / industry_code | str? | listing | existing |
| source_url | str | listing URL | preserved — detail enrichment MUST NOT overwrite it (targets.py:330) |
| **detail_url** | str? | detail-page resolution (D1) | NEW per-record attribute: resolved `href` of the company anchor on the rendered listing |

**Detail URL derivation**: `urljoin(source_url, <anchor href>)` captured from the existing company-anchor selector in `_parse_ti_from_css` / `_parse_ti_via_similarity`. Records whose card carries no resolvable anchor get no `detail_url` (no detail request; field logged unavailable).

### TradeIndia Detail Page (fetched)
Transient entity; not persisted (inspectable copy saved to `debug_output/tradeindia_detail_inspection.html`).

| Attribute | Notes |
|-----------|-------|
| detail_url | request target (per record, max cap / daily guard) |
| phone_raw | text/`tel:`/revealed value; reject `KNOWN_SITE_WIDE_PHONES` ({"01146710423"}) |
| email_raw | text/`mailto:` value; reject `KNOWN_SITE_WIDE_EMAILS` ({"helpdesk@tradeindia.com"}) |
| website_raw | company site anchor; must pass `DIRECTORY_DOMAINS` exclusion |

### Per-Domain Cap State (existing, unchanged)
The Phase-1 daily per-domain budget (e.g. `www.tradeindia.com`). Detail-page requests consume one unit via `cap_guard()`; truncation `needy[:max_detail]` bounds per-run slots (default 20).

### Fill-Rate Report (existing, recomputed in `on_close`)
`per-domain {total, phone, email, website}`; emitted as `phone=X/N, email=Y/N, website=Z/N`.

## Validation Rules (from requirements)

- Non-destructive: a detail value is applied ONLY if the record's field is currently empty (`rec.phone or rec.email` skip).
- A recorded `website` must not be a directory/social domain (`DIRECTORY_DOMAINS`).
- Known site-wide contact values must be rejected for phones/emails.
- A field that cannot be extracted → emitted as a `enrichment_unavailable: <field>` log line, never a silent blank (FR-005).
- `detail_url` resolution must not replace the source (listing) URL.

## State Transitions

Per needy record through detail enrichment:

```text
listing (no detail_url)  -> [detail_url captured when anchor present]
  -> fetch detail page (cap_guard allows, robots allowed)
       -> per field: extract -> set (previously empty) | unavailable (log) | reject (site-wide)
       -> if phone AND email both present on listing -> SKIP (no detail request)
```

Note: `_enrich_from_detail_pages` already skips a record when both `phone` and `email` are already present; the D1 detail-URL capture must produce the same `needy` semantics used in `on_close`.