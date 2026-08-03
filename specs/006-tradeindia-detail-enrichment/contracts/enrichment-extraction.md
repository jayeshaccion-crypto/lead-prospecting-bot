# Contract: TradeIndia Field Extraction & `enrichment_unavailable` Logging

**Feature**: `006-tradeindia-detail-enrichment` | **Date**: 2026-07-31 | **Spec**: [spec.md](../spec.md)

## Mechanism-decision matrix (research D2)

After the rendered capture reports the mechanism, extraction targets are:

| Mechanism | Phone | Email | Website |
|-----------|-------|-------|---------|
| plain text | `(?:\+?91[-\s]?)?[6-9]\d{9}` | RFC-5322-lite email regex | company-site anchor (non-directory) |
| `tel:` link | from `tel:` href | — | — |
| `mailto:` link | — | from `mailto:` href | — |
| js-reveal-button | single bounded click+wait (Q2) | if co-revealed; else unavailable | from content body |
| obfuscated-encoding | de-obfuscate only per literal rendering | same | same |
| login-gate | unavailable | unavailable | unavailable |

Guards applied in every case (non-negotiable):
- Reject `KNOWN_SITE_WIDE_PHONES` / `KNOWN_SITE_WIDE_EMAILS` (`targets.py:43-44`).
- Reject websites in `DIRECTORY_DOMAINS`.
- Non-destructive: a detail value fills a field only when that field is empty.
- Per-field binding selectors/regexes are finalized from the inspection-report evidence (contract [detail-page-capture.md](./detail-page-capture.md)) — never from assumption.

## JS-reveal single bounded attempt (clarification Q2 / SC-007)

- Exactly **one** click on the reveal control plus a **finite** wait for a DOM change.
- If nothing is revealed within the window, mark the affected field(s) `unavailable` and do **not** interact again for that record.
- No retries; interaction bounded to one per record to avoid triggering anti-bot detection.

## `enrichment_unavailable` log format (FR-005 / req #3)

Exactly one log line per field that could not be filled, per record that went through detail enrichment:

```
enrichment_unavailable: <field>
```

`<field>` is lowercase `phone`, `email`, or `website`. Body carries record/URL context (the required literal phrase is the first token):

```
enrichment_unavailable: phone (record="Acme Textiles", url="<detail>")
enrichment_unavailable: email (record="Acme Textiles", url="<detail>")
enrichment_unavailable: website (record="Acme Textiles", url="<detail>")
```

Rules:
- A record may print up to 3 lines (one per unfillable field).
- A record already carrying both phone and email is skipped entirely — no lines, no detail request (idempotence, Constitution IV).
- A rejected site-wide value (e.g. `helpdesk@tradeindia.com`) logs unavailable; it is never kept as company-specific data.

## Acceptance / tests

- Given a detail page exposing only a phone, cardinality is enforced: email+website log unavailable (2 lines), phone is set.
- Given a detail page with a `mailto:` only, email is set; phone and website log unavailable.
- Given a record already bearing phone+email, no detail request is issued and no `enrichment_unavailable` lines are produced.
- The literal `enrichment_unavailable: <field>` token is asserted in tests (grep-able formatting contract).