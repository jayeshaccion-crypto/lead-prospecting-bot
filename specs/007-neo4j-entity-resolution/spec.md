# Feature Specification: Neo4j Graph Schema & Entity Resolution

**Feature Branch**: `007-neo4j-entity-resolution`

**Created**: 2026-08-03

**Status**: Draft

**Input**: User description: "Design and implement the following Neo4j graph schema and entity resolution logic: Nodes (:Company {name, normalized_name, phone, email, website, first_seen, last_seen, sources}), (:Category {name}), (:City {name}), (:Source {name}). Relationships (:Company)-[:LISTED_IN]->(:Category), (:Company)-[:LOCATED_IN]->(:City), (:Company)-[:SOURCED_FROM {scraped_at, raw_record_id}]->(:Source). Entity resolution, applied before writing any scraped record: (1) deterministic pass — normalize name (lowercase, strip Pvt/Ltd/LLP/Private Limited/punctuation) + match on phone number if present (phone is the primary key when available); (2) fuzzy pass, only for records without a clean phone match — rapidfuzz token_sort_ratio against existing Company names, threshold >= 90, log every fuzzy match made (both names + score) to a review log file whether or not it crosses the threshold; (3) on match (either pass) — MERGE the existing Company node: update last_seen, append new source to sources if not already present, MERGE (not CREATE) the relevant relationships keyed on company+category / company+city so repeat scraping doesn't duplicate relationships; (4) on no match — CREATE a new Company node with first_seen = today. Verify idempotency: running the same day's raw data through this logic twice must not change node or relationship counts on the second run."

## Clarifications

### Session 2026-08-03

- **Q1 — Company identity & name property → A (Keep `company_name` + `dedup_key`).** The stored property remains `company_name`; `dedup_key` remains the immutable uniqueness key. The requested `name` attribute is the conceptual name of the company and maps to the stored `company_name` property. No data migration or index change.
- **Q2 — Scope vs the existing graph model → A (Requested schema is canonical).** The requested schema (Company/Category/City/Source; LISTED_IN/LOCATED_IN/SOURCED_FROM) becomes the canonical model for all new writes. Legacy node types (Phone, Email, Website, Location, Industry) and HAS_PHONE/HAS_EMAIL/HAS_WEBSITE/BELONGS_TO are no longer written; existing legacy nodes already in the graph remain in place and are left untouched (not deleted, not migrated).
- **Q: Company-name normalization suffix set → A: Keep the current extended set and add `OPC`.** Based on a 38-name sample of real scraped names (IndiaMART/Justdial/TradeIndia), the normalizer continues to strip `pvt|ltd|llp|private limited|inc|corp|corporation|llc|limited|co|company|technologies|solutions|services|systems|group|industries|enterprises` and additionally strips the Indian legal form `OPC` (One Person Company), seen in real data as `Nitai Technologies (OPC) Private Limited`. No other unhandled legal-form suffix appeared in the sample.
- **Q: Review-log format and location → A: Flat file only (`debug_output/fuzzy_matches.log`).** One line per fuzzy comparison (timestamp, both company names, score, threshold). No database table; the flat file satisfies the stated "review log file" requirement and the existing governance rule, and stays human-readable for manual spot-checking of merges.
- **Q: Fuzzy-match threshold configurability → A: Configurable, key `fuzzy_match_threshold`, default 90.** The threshold is read from the project config file under the key `fuzzy_match_threshold`, defaulting to `90` when unset; the in-effect value is written to the review log so tuning remains auditable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One Company, Many Sources Resolves to One Node (Priority: P1)

An operator scrapes the same company from multiple Indian directories (e.g., TradeIndia, IndiaMART, Justdial) on the same day or across days. Even though the raw records differ (different listing pages, slightly different names, one source missing a phone), the pipeline stores a single graph entry for that company. Repeat scraping of the same company does not create duplicate nodes or duplicate category/city relationships, and the `sources` list on that company grows to include every directory it was seen on.

**Why this priority**: This is the core value of entity resolution — without it the graph accumulates duplicate companies and every repeat crawl doubles the noise. Correct phone-keyed and name-keyed merging is the foundation the other stories rely on.

**Independent Test**: Feed the resolution logic two records for the same company (same phone, different names/sources), then re-feed the same pair a second time. Confirm exactly one Company node exists afterward, its `sources` lists both directories, and the second run changes no counts.

**Acceptance Scenarios**:

1. **Given** two records with the same phone number but different display names and sources, **When** both are resolved, **Then** exactly one Company node exists carrying both sources in its `sources` list.
2. **Given** the same raw records are resolved a second time on the same day, **When** the resolution runs again, **Then** node and relationship counts are unchanged from the first run.
3. **Given** a company already linked to a category and a city, **When** it is scraped again in the same category and city, **Then** no duplicate LISTED_IN or LOCATED_IN relationship is created.

---

### User Story 2 - Fuzzy Name Matching With a Full Review Trail (Priority: P2)

A record has no usable phone number, so the deterministic pass cannot find a match. The resolver compares the normalized name against existing company names with a similarity score, merging only when the score reaches the threshold (90). Every comparison — whether or not it merges — is written to a review log with both company names and the score, so an operator can spot-check that no wrong merge is committed to the graph (a wrong merge is permanent and hard to unwind).

**Why this priority**: Fuzzy matching is the riskiest part of entity resolution — false merges corrupt the graph irreversibly. Transparency of every scored candidate is a hard governance requirement, and merging only above a strict threshold keeps precision high.

**Independent Test**: Insert a company named "Tech Solutions Pvt Ltd" and then resolve a new record named "Tech Solutions Pvt. Ltd." without a phone. Confirm a merge occurs with score ≥ 90 and that the review log contains the entry. Then resolve a clearly different name and confirm it does not merge but IS still logged with its score.

**Acceptance Scenarios**:

1. **Given** an existing company and a new phone-less record whose normalized name is a near-identical variant, **When** resolution runs, **Then** the record merges into the existing company (score ≥ 90) and the review log records both names and the score.
2. **Given** a new phone-less record whose closest existing name scores below the threshold, **When** resolution runs, **Then** the record does NOT merge, and the review log still records the comparison with both names and the score.
3. **Given** a new record that carries a phone number, **When** resolution runs, **Then** the fuzzy pass is skipped entirely for that record (no fuzzy log entries generated for it).

---

### User Story 3 - Idempotent Graph Writes (Priority: P3)

An operator re-runs the same day's pipeline (as the schedule may do when a run is retried). The graph write phase must be idempotent: replaying the same raw records must not create additional nodes or relationships. Every run reports distinct audit counts — new companies created, companies matched by phone, companies matched by fuzzy name, and total graph size — so the operator can see that re-running changed nothing.

**Why this priority**: Re-run safety is a blocking governance rule. Without idempotency, schedule retries silently inflate the graph and erode data quality.

**Independent Test**: Capture node + relationship counts after a first resolution of a known dataset, then resolve the identical dataset again and capture counts again. Assert both counts are identical.

**Acceptance Scenarios**:

1. **Given** a dataset already resolved once, **When** the identical dataset is resolved again, **Then** Company node count is unchanged.
2. **Given** a dataset already resolved once, **When** the identical dataset is resolved again, **Then** LISTED_IN, LOCATED_IN, and SOURCED_FROM relationship counts are unchanged.
3. **Given** any run, **When** it completes, **Then** it logs distinct counts for created / phone-matched / fuzzy-matched / total graph size.

---

### Edge Cases

- What happens when a record has a phone number but it was seen before under a different formatting (spaces, dashes, country code)? — Phone matching ignores formatting and compares the last 10 digits so "07971 671113", "+91 7971 671113", and "7971671113" resolve to the same company.
- What happens when a company name matches fuzzy candidates for more than one existing company? — The single highest-scoring candidate at or above the threshold wins; ties resolve deterministically so the outcome is reproducible.
- What happens when a record has no phone, no email, no website? — Resolution still runs on the normalized name (deterministic normalizer, then fuzzy pass) since the record is identified by name alone.
- What happens when the same category or city name appears in multiple records? — Category and City nodes are merged by name; repeated references never duplicate the node or the relationship.
- What happens if the review log cannot be written? — The comparison is logged at the application level instead and the failure is surfaced (never silently dropped).
- What happens if the graph store is unavailable? — The run must not silently degrade: the write failure is logged and the run summary reports an explicit failed-graph-write flag.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The graph MUST contain the node types Company, Category, City, and Source. A Company node MUST carry: company_name (the conceptual `name` attribute), normalized_name, phone, email, website, first_seen, last_seen, and a sources list. The `dedup_key` property MUST remain the immutable uniqueness key for the Company node. (Q1: keep existing `company_name` + `dedup_key`.)
- **FR-002**: The graph MUST contain the relationship types LISTED_IN (Company→Category), LOCATED_IN (Company→City), and SOURCED_FROM (Company→Source). A SOURCED_FROM relationship MUST carry the scrape timestamp and the identifier of the originating raw record.
- **FR-003**: Every scraped record MUST pass through entity resolution before any graph write for that record is committed.
- **FR-004**: The deterministic pass MUST run first: the name is normalized (lowercased; legal suffixes removed — `Pvt/Ltd/LLP/Private Limited` plus the existing extended set `Inc/Corp/LLC/Limited/Co/Company/Technologies/Solutions/Services/Systems/Group/Industries/Enterprises` and the Indian legal form `OPC`; punctuation removed; whitespace collapsed), and if the record carries a phone number, matching MUST use the phone number as the primary key (formatting-insensitive, comparing the last 10 digits).
- **FR-005**: The fuzzy pass MUST run only for records that did not achieve a clean phone match. It MUST compare the normalized name against existing company names using a token-sorted similarity ratio and merge only when the score meets the configured threshold — `fuzzy_match_threshold`, default `90` (Clarification Session 2026-08-03).
- **FR-006**: Every fuzzy comparison MUST be written to the review log at `debug_output/fuzzy_matches.log` with both company names and the score — regardless of whether the score crosses the threshold. The review log MUST be a flat file (one line per comparison: timestamp, both names, score, threshold); no database table is used. Records that match by phone MUST NOT generate fuzzy log entries.
- **FR-007**: On a match (either pass), the existing Company node MUST be merged, not duplicated: last_seen is updated, a new source is appended to the sources list only if not already present, and the relevant LISTED_IN/LOCATED_IN/SOURCED_FROM relationships are merged (never created) keyed on company+category and company+city so repeat scraping cannot duplicate them.
- **FR-008**: On no match, a new Company node MUST be created with first_seen set to the run's date. first_seen MUST be set exactly once and never overwritten on later matches.
- **FR-009**: Replaying identical raw data MUST be idempotent: resolving the same day's data a second time MUST NOT change Company node, Category node, City node, Source node, or relationship counts.
- **FR-010**: Every run MUST report distinct counts: new Company nodes created, companies matched by phone, companies matched by fuzzy name, and total graph size (node + relationship counts).
- **FR-011**: Graph-write credentials MUST be supplied through environment configuration only, never embedded in source or committed files. [existing governance rule — a currently hardcoded credential is a defect to remove]
- **FR-012**: If the graph write phase fails, the run MUST log the failure and report an explicit graph-write-failed flag in the run summary (a 0-count result must never masquerade as success). [existing governance rule]
- **FR-013**: The requested schema MUST be the canonical model for all new graph writes. Legacy node types (Phone, Email, Website, Location, Industry) and their HAS_PHONE/HAS_EMAIL/HAS_WEBSITE/BELONGS_TO relationships MUST NOT be written by new code; any legacy nodes already present in the graph MUST be left untouched. (Q2: requested schema is canonical.)

### Key Entities *(include if feature involves data)*

- **Company**: A single resolved business entity. Attributes: name (stored as `company_name`), normalized_name, phone, email, website, first_seen, last_seen, sources (the directories it has been seen in). Its immutable identity is the `dedup_key`, set once at creation.
- **Category**: A business category a company is listed under (e.g., software solutions). Related to Company via LISTED_IN. Merged by name so re-scraping never duplicates it.
- **City**: A geographic location (e.g., Kolkata). Related to Company via LOCATED_IN. Merged by name.
- **Source**: A directory the company was scraped from (e.g., TradeIndia, IndiaMART, Justdial). Related to Company via SOURCED_FROM, whose edge carries the scrape timestamp and the originating raw record identifier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A company appearing under multiple sources or multiple listing pages resolves to exactly one Company node — zero duplicate Company nodes for the same phone number.
- **SC-002**: Re-running identical same-day input produces a delta of exactly 0 in both node count and relationship count on the second run.
- **SC-003**: 100% of fuzzy comparisons are recorded in the review log with both company names and the similarity score.
- **SC-004**: 100% of SOURCED_FROM edges carry the scrape timestamp and the originating raw record identifier.
- **SC-005**: Every run reports distinct created / phone-matched / fuzzy-matched counts plus total graph size.
- **SC-006**: A near-identical company-name variant (e.g., "Tech Solutions Pvt Ltd" vs "Tech Solutions Pvt. Ltd.") merges into a single node when scored at or above the configured threshold (default 90), while a dissimilar name does not merge.

## Assumptions

- The existing graph-store module is the starting point; this feature aligns its write path to the requested schema and fills the gaps (SOURCED_FROM.raw_record_id, full review-log coverage for below-threshold candidates, canonical Category/LISTED_IN model, idempotency verification).
- Company identity is the existing `dedup_key` (phone's last 10 digits when present, otherwise normalized name, plus website when available); the `company_name` property holds the display name (Q1).
- Legacy node types (Phone, Email, Website, Location, Industry) are not written and not migrated by this feature; they remain only where they already exist in the graph (Q2).
- "today" means the date of the pipeline run in the run's configured timezone (existing pipeline convention).
- Name normalization removes the legal suffixes named in the feature plus common corporate suffixes already handled by the current normalizer (Inc, LLC, Corporation, etc.), and adds the Indian legal form `OPC` found in real scraped names (Clarification Session 2026-08-03).
- Phone is the primary key when present; when absent, resolution falls back to the normalized name (deterministic normalizer, then fuzzy pass) — matching may still be attempted with no contact data present.
- The fuzzy-match threshold is configurable via the project config file under the key `fuzzy_match_threshold`, defaulting to `90` (Clarification Session 2026-08-03); the value in effect is written to the review log for auditability.
- The review log is a flat file at `debug_output/fuzzy_matches.log` (one line per comparison: timestamp, both company names, score, threshold); no database table (Clarification Session 2026-08-03).
- The Company node continues to carry the project-governance scoring properties (score and score breakdown) in addition to the properties named in this feature — those properties are internal to the data layer and remain out of any user-facing output (existing governance rule).
- The checked-in TradeIndia debug captures carry no phone/email (Phase 4 detail-page enrichment fields are absent from the captures at the time of writing). Cross-site phone matching is therefore proven in the fixture by a synthetic pair (a JustDial and an IndiaMART listing sharing a phone) plus a synthetic TradeIndia record carrying phone+email; the fixture script asserts at least one phone-last-10 group spans ≥2 distinct sites. Revisit if fresh TradeIndia captures later include enriched contact data.
- City values are stored by name only; geocoding, coordinates, and city-level normalization are out of scope for this feature.
