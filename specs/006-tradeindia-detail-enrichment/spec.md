# Feature Specification: TradeIndia Detail-Page Enrichment

**Feature Branch**: `006-tradeindia-detail-enrichment`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "Enable TradeIndia detail-page enrichment, currently hardcoded to 'max 0' (disabled). Set a real configurable cap, default 20 per run. Before writing any selector or regex, fetch and save one real TradeIndia detail page to debug_output and inspect its actual HTML structure — do not assume plain-text phone/email like IndiaMART; expect JS-reveal buttons, obfuscated markup, tel:/mailto: links, or login-gating. Extract phone, email, and website from the detail page. Where a field cannot be extracted, log 'enrichment_unavailable: <field>' per record rather than leaving it silently blank. Respect the same per-domain rate-limiting established in Phase 1 for these additional detail-page requests. Report fill rates (phone=X/13, email=Y/13, website=Z/13) in the run summary."

## Clarifications

### Session 2026-07-31

- Q1: After the real-page inspection report, must a human confirm the extraction approach before implementation proceeds? → A: Hybrid — the mechanism present is always reported first; extraction proceeds automatically only for plain-text and `tel:`/`mailto:` structures (low-risk, obvious extraction); for JS-reveal buttons, obfuscated encoding, or login gates, implementation stops and confirms the approach before proceeding.
- Q2: If a JS-reveal button is found, should the reveal interaction be attempted or the field marked permanently unavailable? → A: Single bounded attempt — exactly one click with a finite wait for a DOM change and no retry; if nothing is revealed within the window, the affected fields revert to unavailable with no further browser interaction for that record (avoids triggering anti-bot detection).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enable TradeIndia Detail-Page Enrichment (Priority: P1)

An operator running the pipeline sees TradeIndia records that carry a company name and listing data but often lack phone, email, and website. After this feature, the pipeline fetches up to a configurable number of TradeIndia company detail pages per run (default 20) and pulls phone, email, and website from each page, so a much higher share of TradeIndia records is ready for outreach.

**Why this priority**: Contact details are the core value of a lead. TradeIndia is currently the weakest source on this dimension (browser detail enrichment effectively disabled), so closing this gap directly raises the usable-lead yield from the highest-volume directory in the pipeline.

**Independent Test**: Point the pipeline at a small TradeIndia crawl (few records), enable detail enrichment, and confirm that records missing contact fields receive phone/email/website values from their detail pages — while records that already carry both phone and email are left untouched and no more than 20 detail pages are requested.

**Acceptance Scenarios**:

1. **Given** a TradeIndia record with a missing phone, email, or website, **When** the run performs detail-page enrichment, **Then** the missing field(s) are populated from the record's detail page where extractable.
2. **Given** a TradeIndia record that already has both phone and email, **When** detail-page enrichment runs, **Then** the record is not re-fetched and its existing values are preserved unchanged.
3. **Given** more TradeIndia records need enrichment than the configured cap, **When** the cap is reached, **Then** the remaining records are left as-is and the run records that the cap was reached for TradeIndia.

---

### User Story 2 - Evidence-Based Extraction with Unavailable-Field Logging (Priority: P2)

A maintainer wants the enrichment logic grounded in the real page, not guesses. The implementation first fetches and saves at least one real TradeIndia detail page to `debug_output` and derives the extraction rules from its actual HTML — which may hide contact data behind JS-reveal buttons, obfuscated markup, `tel:`/`mailto:` links, or login gates. Where a field genuinely cannot be extracted from a record's detail page, the run logs `enrichment_unavailable: <field>` for that record instead of leaving the field silently blank.

**Why this priority**: TradeIndia contact data is JS-API-driven and does not render as plain text like IndiaMART; an assumption-driven parser would silently produce zero fill. Making extraction evidence-based and logging every miss prevents a "working-looking" feature that actually captures nothing.

**Independent Test**: Inspect `debug_output` for the saved real TradeIndia detail page, and run enrichment over records whose pages lack one or more fields; confirm each missing field produces a distinct `enrichment_unavailable: <field>` log line.

**Acceptance Scenarios**:

1. **Given** a real TradeIndia detail page has been fetched during implementation, **When** it is saved to `debug_output`, **Then** it is inspectable and the extraction rules in use are consistent with that page's actual structure.
2. **Given** a TradeIndia record whose detail page does not expose a phone, **When** enrichment runs, **Then** the run logs `enrichment_unavailable: phone` for that record and does not claim a phone value.
3. **Given** a TradeIndia record whose detail page exposes an email only through a `mailto:` link, **When** enrichment runs, **Then** the email is captured from that link.

---

### User Story 3 - Rate-Limit-Safe Enrichment and Fill-Rate Reporting (Priority: P3)

An operator wants the new detail-page requests to obey the same per-domain daily request budget established for the rest of the crawl (a hard daily cap, counting every request to the domain), so enabling enrichment cannot blow through the daily budget. The operator also wants the run summary to state how well enrichment filled each field — `phone=X/N`, `email=Y/N`, `website=Z/N` for the TradeIndia records.

**Why this priority**: Safety and observability. Detail enrichment multiplies request volume by a per-record factor, so it must be bounded by the existing per-domain budget; and without explicit fill-rate reporting the feature's real value is invisible to the operator.

**Independent Test**: Set a small daily cap for the TradeIndia domain, run enrichment with a large needy-record list, and confirm total TradeIndia requests never exceed the cap and the summary line reports `phone=X/N`, `email=Y/N`, `website=Z/N`.

**Acceptance Scenarios**:

1. **Given** the TradeIndia domain's daily cap is exhausted mid-run, **When** remaining detail pages would be requested, **Then** enrichment stops for that domain, the stop is logged, and no further requests are issued to the domain that day.
2. **Given** a run that enriched N TradeIndia records, **When** the summary is produced, **Then** it reports `phone=X/N`, `email=Y/N`, and `website=Z/N` for TradeIndia where X, Y, Z are the counts of records with each field populated.
3. **Given** the same calendar day's budget was already consumed by an earlier run, **When** a later run starts, **Then** it accounts for the consumed budget and does not exceed the cap.

---

### Edge Cases

- What happens when a TradeIndia detail page is login-gated and shows no contact data? → Extraction finds nothing; each missing field is logged as `enrichment_unavailable: <field>` for that record.
- What happens when the inspected detail page reveals a JS-reveal, obfuscated, or login-gated mechanism? → The mechanism is reported and implementation stops to confirm the extraction approach before proceeding, rather than guessing and implementing in the same step (per clarification Q1).
- What happens when contact data is only revealed by a JS-reveal button? → A single bounded click+wait is attempted (one click, finite wait, no retry); if no DOM change reveals the data within the window, the affected fields are marked unavailable and logged with no further browser interaction for that record (per clarification Q2).
- What happens when phone numbers or emails are obfuscated (encoded, split, CSS/JS-rendered)? → Only de-obfuscation consistent with the inspected real page structure is applied; unextractable fields are logged as unavailable.
- What happens when the detail page returns a blocked, captcha, or error body instead of content? → The fetch is treated as a failed/empty enrichment attempt, logged, and counted against the cap if a request was made; the record is left as-is.
- What happens when a detail page is a 404 or the detail URL is missing? → The record is skipped with the failure logged; no fabricated values.
- What happens when a contact value matches a known site-wide value (e.g., helpdesk@tradeindia.com)? → It is rejected per existing rules and the field remains unpopulated (logged as unavailable).
- What happens when the daily cap is reached halfway through enrichment? → Remaining detail pages are not requested; the run logs that enrichment was cap-stopped for the domain.
- What happens when a record already has phone and email from the listing page? → It is skipped — no detail-page request is spent on it (idempotent, budget-preserving).
- What happens when the configured cap is set below the number of needy records? → Only the first capped number of detail pages are requested; the rest remain un-enriched and the run reports the cap was reached.
- What happens if the TradeIndia parser yields no records? → No detail pages are requested for TradeIndia and the summary reports fill rates of `0/0` (or equivalent), not an error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST enable TradeIndia detail-page enrichment behind a configurable per-run cap, with a default of 20 detail pages per run.
- **FR-002**: The enrichment cap MUST be configurable in the targets configuration (alongside the existing per-target settings) and MUST NOT require a code change to adjust.
- **FR-003**: Before any extraction selector or pattern is written, at least one real TradeIndia detail page MUST be fetched and saved to `debug_output`, and the extraction rules MUST be derived from that page's actual HTML structure rather than assumed plain-text markup. The actual protection mechanism present (plain text, `tel:`/`mailto:` links, JS-reveal button, obfuscated encoding, or login gate) MUST be reported before an extraction approach is proposed. Extraction proceeds automatically only for plain-text and `tel:`/`mailto:` structures; for JS-reveal, obfuscated, or login-gated structures, implementation MUST stop and confirm the approach before proceeding (per clarification Q1).
- **FR-004**: System MUST attempt to extract phone, email, and website from each fetched TradeIndia detail page.
- **FR-005**: For every record that goes through TradeIndia detail enrichment, System MUST account for each of phone, email, and website: either a captured value or a per-record `enrichment_unavailable: <field>` log line for each field that could not be extracted. No field may be left silently blank without a logged disposition.
- **FR-006**: System MUST support extracting contact data from the structures actually found on TradeIndia detail pages, including (as found) `tel:` links, `mailto:` links, and plain text. Where a JS-reveal button is found, System MUST make a single bounded interaction attempt: exactly one click, a finite wait for a DOM change, and no retry; if nothing is revealed within the wait window, the affected fields revert to unavailable for that record and no further browser interaction is attempted (avoids triggering anti-bot detection, per clarification Q2). Obfuscated encoding is handled only in ways consistent with the inspected page; login-gated pages expose no data and fields are logged unavailable.
- **FR-007**: TradeIndia detail-page requests MUST count against the same per-domain daily request cap as all other requests to the TradeIndia domain (established in the volume-expansion feature). When the cap is exhausted, no further TradeIndia detail pages are requested and the cap-stop is logged.
- **FR-008**: Enrichment MUST be non-destructive: it MUST fill only missing fields and MUST NOT overwrite an existing populated value, including values already present on the listing page.
- **FR-009**: System MUST reject known site-wide contact values and directory-domain websites during detail enrichment, consistent with existing enrichment rules.
- **FR-010**: The run summary MUST report TradeIndia detail-enrichment fill rates as `phone=X/N`, `email=Y/N`, `website=Z/N`, where N is the number of TradeIndia records and X, Y, Z are the counts of records with phone, email, and website populated after the run.

### Key Entities *(include if feature involves data)*

- **TradeIndia Detail Page**: A company profile page on the TradeIndia directory referenced by a detail URL; the source of phone, email, and website values. Its structure is not plain-text — contact data may be JS-revealed, obfuscated, link-based, or login-gated.
- **RawRecord (TradeIndia)**: The scraped company record being enriched; fields phone, email, website are filled from the detail page only when missing.
- **Enrichment Cap**: The configurable per-run limit (default 20) on how many TradeIndia detail pages are requested during a single run.
- **Per-Domain Daily Cap State**: The persisted per-domain request budget shared with the rest of the crawl; detail-page enrichment consumes from it.
- **Run Summary Fill-Rate Report**: The per-domain reporting line `phone=X/N`, `email=Y/N`, `website=Z/N` emitted in the run summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the default cap, no run requests more than 20 TradeIndia detail pages regardless of how many TradeIndia records lack contact data.
- **SC-002**: 100% of TradeIndia records that go through detail enrichment have an explicit logged disposition for phone, email, and website (value captured or `enrichment_unavailable: <field>`); zero silent blanks.
- **SC-003**: TradeIndia detail-page requests never cause the domain to exceed its configured daily request cap; when the cap is reached, enrichment stops and is logged.
- **SC-004**: The run summary includes a TradeIndia fill-rate line reporting `phone=X/N`, `email=Y/N`, `website=Z/N` with N equal to the TradeIndia record count.
- **SC-005**: No pre-existing non-empty phone, email, or website value on a TradeIndia record is changed by detail enrichment, and no known site-wide value or directory-domain website is accepted as a company value.
- **SC-006**: A real TradeIndia detail page saved to `debug_output` exists from the implementation process, the protection mechanism present was reported before extraction rules were finalized, and the extraction rules demonstrably match its inspected structure.
- **SC-007**: Where a JS-reveal button is encountered, enrichment makes at most one click-and-wait attempt per record; records whose reveal fails within the wait window are logged as unavailable and no further interaction is attempted for them.

## Assumptions

- "Per run" means per pipeline invocation: the default cap of 20 bounds the number of TradeIndia detail pages requested in a single run; those requests additionally count against the per-domain daily cap from the volume-expansion feature.
- The current-state discrepancy between the user's report ("hardcoded to max 0 / disabled") and the existing config (`max_detail_pages` present for TradeIndia) is reconciled during planning; the requirement in this spec is that TradeIndia detail enrichment is genuinely enabled and effective, with a real configurable cap defaulting to 20.
- TradeIndia contact data is JS-API-driven and not plain-text like IndiaMART; the concrete extraction mechanism (browser interaction, HTML parsing, or a combination) is decided during planning only after a real detail page is captured to `debug_output`.
- Detail-page capture for inspection is a one-time implementation-time research step, not a per-run behavior; the saved HTML persists in `debug_output` for audit/reference.
- Enrichment remains non-destructive and idempotent per the project constitution (Principle IV): re-running must not alter existing populated values or duplicate requests for records that already have phone and email.
- Robots.txt compliance (Principle I) continues to apply to TradeIndia detail-page requests exactly as it does to listing pages.
- The fill-rate denominator N is the number of TradeIndia records produced by the run (the user's example used 13); if the record count is zero, the fill-rate line reports 0/0 rather than being omitted or erroring.
