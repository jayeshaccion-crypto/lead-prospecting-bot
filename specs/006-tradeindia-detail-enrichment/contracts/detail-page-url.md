# Contract: TradeIndia Detail-Page URL Resolution

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](../spec.md)

## Problem (req #1)

"Does the existing CSS-extracted listing card already carry the detail URL, or does it need a new selector?"

## Answer (research D1)

In the RENDERED listing DOM, each company's name is an `<a>` anchor located by the existing TradeIndia parsers (`.company-url`, `a[href]`, `h3.company-name`) in `_parse_ti_from_css` / `_parse_ti_via_similarity`. Those parsers read only `name.text` for the company name and **drop the `href`**. The raw (unrendered) HTML carries no stable card markup (client-rendered). Therefore a new selector step IS required — new, but on an element the parser already resolves:

> Capture the `href` attribute of the existing company-anchor selector and resolve it against the listing URL.

## Contract

- For each company card, extract the anchor `href` and compute `detail_url = urljoin(listing_url, href)`.
- A card whose anchor has no resolvable `href` → `detail_url = None` (no detail request; contact fields logged unavailable).
- Store `detail_url` on the `RawRecord` (see [data-model.md](../data-model.md)) without altering `source_url` (the listing URL).
- The exact anchor selector/attribute is finalized from the inspection evidence (contract [detail-page-capture.md](./detail-page-capture.md)); `.company-url` is the current candidate, `a[href]` the fallback.

## Acceptance / test

- Given a synthetic rendered card with a company anchor `href`, the parser returns `detail_url` with scheme/host equal to the listing's.
- Given a card with no/relative/malformed href, `detail_url` is `None` (no crash, logged unavailable).