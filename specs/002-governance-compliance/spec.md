# Feature Specification: Governance Compliance

**Feature Branch**: `002-governance-compliance`

**Created**: 2026-07-30

**Status**: Draft

**Input**: Six constitutional rules for the lead prospecting pipeline that
must be enforced in code: fail loudly on every target, log all entity-
resolution merges, keep scoring deterministic and auditable, isolate
lead_score from user-facing renders, never commit credentials to git,
and guarantee idempotency across all phases.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Operator Sees Every Target's Disposition (Priority: P1)

As a pipeline operator, I want every crawl target's disposition logged
explicitly (which targets were tried, which were skipped and why, which
succeeded with how many records) so I can understand a run's results
without reading source code or guessing why a target contributed 0.

**Why this priority**: Without explicit disposition logs, silent failures
or skipped targets produce misleading 0-record contributions that erode
trust in the pipeline's output. This is the most critical constitutional
rule.

**Independent Test**: Run the pipeline with no proxies configured. The
output must contain three explicit log entries: one stating JustDial was
skipped (with reason "ProxyNotConfigured"), one stating IndiaMART was
skipped (with reason "ProxyNotConfigured"), and one stating TradeIndia
was attempted. Re-run with a proxy and verify the disposition changes.

**Acceptance Scenarios**:

1. **Given** no proxy env vars set, **When** the pipeline runs, **Then**
   the log contains "Justdial skipped: ProxyNotConfigured", "IndiaMART
   skipped: ProxyNotConfigured", and "TradeIndia: N records scraped".

2. **Given** a Webshare proxy is configured, **When** the pipeline runs,
   **Then** IndiaMART disposition shows attempts and record count.

3. **Given** Neo4j credentials are configured but the database is
   unreachable, **When** the pipeline runs, **Then** the run summary
   includes `"neo4j_failed": true` — not just `neo4j_created: 0`.

4. **Given** a target's daily cap is reached mid-run, **When** the
   pipeline stops issuing requests to that domain, **Then** a log entry
   states "Daily cap reached for <domain> — stopping".

---

### User Story 2 — Reviewer Audits Entity-Resolution Merges (Priority: P1)

As a reviewer, I want every entity-resolution merge logged to a
dedicated review file with both company names and similarity scores so I
can spot-check fuzzy matches and undo any wrong merges before they
permanently corrupt the knowledge graph.

**Why this priority**: Wrong merges are nearly impossible to unwind once
committed to Neo4j. The constitution requires all merges to be auditable.

**Independent Test**: Scrape a small batch, verify the
`debug_output/fuzzy_matches.log` file exists with timestamped entries,
and confirm each fuzzy match entry includes both company names, the
rapidfuzz similarity score, and the threshold used.

**Acceptance Scenarios**:

1. **Given** a fuzzy match is made between two company nodes, **When**
   the merge is committed, **Then** an entry is appended to
   `debug_output/fuzzy_matches.log` with `[score=92] CompanyA -> CompanyB`
   format.

2. **Given** no fuzzy match is made, **When** the pipeline runs, **Then**
   `debug_output/fuzzy_matches.log` is empty or absent.

3. **Given** a candidate falls below the 90-threshold, **When** the merge
   is skipped, **Then** a DEBUG-level log entry records the candidate
   name and score — never silently discarded.

4. **Given** a phone-match is found, **When** the merge succeeds, **Then**
   an INFO-level log entry states both company names and the phone used.

---

### User Story 3 — Data Steward Verifies Score Isolation (Priority: P2)

As a data steward, I want to verify that `lead_score` and
`lead_score_breakdown` appear in the database and Neo4j but NEVER in the
dashboard HTML, so the constitution's data-layer-only rule is enforced.

**Why this priority**: Score isolation is a hard constitutional
constraint. A violation means scores leak to users who could game them.

**Independent Test**: Grep the generated `dashboard.html` file for
`lead_score` — the search MUST return zero matches. Query the SQLite
database and Neo4j to confirm the data IS stored there.

**Acceptance Scenarios**:

1. **Given** a pipeline run has completed, **When** the dashboard is
   built, **Then** `grep -c "lead_score" dashboard.html` returns 0.

2. **Given** a pipeline run has completed, **When** the SQLite Leads
   table is queried, **Then** the `lead_score` and
   `lead_score_breakdown` columns contain values.

3. **Given** a pipeline run has completed, **When** Neo4j is queried,
   **Then** Company nodes have `lead_score` and
   `lead_score_breakdown` properties.

---

### User Story 4 — Security Auditor Validates No Committed Credentials (Priority: P2)

As a security auditor, I want to prove that no credential-equivalent
strings exist anywhere in the git-tracked codebase — not in source code,
config files under version control, comments, or test fixtures — so no
credential leak can occur through version control.

**Why this priority**: Committed credentials are the most common source
of data breaches. The constitution explicitly forbids this.

**Independent Test**: Run `git grep -i "password\|secret\|proxy.*http\|neo4j.*://"` across
all tracked files excluding `.gitignore`-pattern matches and known false
positives. Results must contain zero credential-bearing lines.

**Acceptance Scenarios**:

1. **Given** the repository checkout, **When** a grep for
   `WEBSHARE_PROXY_URL|RESIDENTIAL_PROXY|NEO4J_URI|NEO4J_PASSWORD` is run
   against tracked files, **Then** only `.env.example`, CI workflow files,
   and documentation references match — never real credentials.

2. **Given** a `.env` file exists in the working directory, **When**
   `git status` is run, **Then** `.env` is not listed (must be in
   `.gitignore`).

---

### User Story 5 — Operator Proves Idempotency (Priority: P3)

As a pipeline operator, I want to re-run the same day's data and see
identical record and node counts on the second run, so I can trust the
pipeline does not silently duplicate data across phases.

**Why this priority**: Without idempotency guarantees, re-runs after
failures or for verification produce inflated counts, making data
untrustworthy.

**Independent Test**: Run the pipeline against a small TradeIndia batch.
Record the counts. Run it again with the same data. Assert Neo4j node
counts, relationship counts, and SQLite row counts are identical.

**Acceptance Scenarios**:

1. **Given** a pipeline run has completed, **When** the same run is
   executed again immediately, **Then** Neo4j Company node count must be
   unchanged; LISTED_IN, LOCATED_IN, SOURCED_FROM relationship counts
   must be unchanged; SQLite Leads row count must be unchanged.

2. **Given** a record appears on two different source sites, **When**
   both are scraped and merged by entity resolution, **Then** re-running
   must not create a duplicate Company node or duplicate relationship.

3. **Given** the pipeline crashes mid-phase (e.g., network loss), **When**
   it is restarted, **Then** it must resume from checkpoint (if
   available) or produce the same final state as if the crash never
   occurred.

---

### Edge Cases

- What happens when Neo4j is reachable but schema constraints are
  missing? The pipeline should log a clear error and flag
  `neo4j_failed: true`, not silently skip.
- What happens when the fuzzy-matches log file is locked by another
  process? The pipeline should fall back to console-only logging for that
  run without crashing.
- What happens when the pipeline runs on two different machines against
  the same Neo4j database? Idempotency must hold cross-process — MERGE
  on dedup_key handles this at the database level.
- What happens when no fuzzy matches occur in a run? The review log file
  may be absent or empty — neither is a violation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every target's disposition (attempted/skipped/succeeded)
  MUST be logged at INFO or WARNING level with a clear one-line reason
  for skips. The run summary MUST list all targets and their outcomes.
- **FR-002**: Neo4j write failures MUST produce a `"neo4j_failed": true`
  flag in the pipeline summary dict. The summary MUST NOT report
  `neo4j_created: 0` for a failed write.
- **FR-003**: Fuzzy name matches (rapidfuzz token_sort_ratio >= 90) MUST
  be appended to `debug_output/fuzzy_matches.log` with timestamp, both
  company names, score, and threshold. Phone matches MUST be logged at
  INFO level with both names and the phone used.
- **FR-004**: Candidates below the fuzzy threshold (score < 90) MUST be
  logged at DEBUG level with candidate name and score.
- **FR-005**: `lead_score` and `lead_score_breakdown` MUST appear in the
  SQLite Leads table columns and as Neo4j Company node properties.
- **FR-006**: `lead_score` and `lead_score_breakdown` MUST NOT appear in
  `dashboard.html`, its embedded JSON, JavaScript, CSS, or any user-
  facing render.
- **FR-007**: `.env` MUST be in `.gitignore`. Real credential values MUST
  NOT appear in any file tracked by git. Only environment variable names
  (e.g., `$WEBSHARE_PROXY_URL`) may appear in configuration docs and CI
  workflow files.
- **FR-008**: Re-running the same scraped data MUST produce identical
  Neo4j node counts, relationship counts, and SQLite row counts.
- **FR-009**: The Spider MUST pass `crawldir` to its parent class
  constructor so checkpoint save/resume is enabled.
- **FR-010**: Checkpoint files MUST be listed in `.gitignore`.

### Key Entities

- **ScrapeTarget**: A configuration entry in `targets.yml` representing
  one business directory to scrape (Justdial, IndiaMART, TradeIndia).
  Has a disposition state per run.
- **EntityResolutionLog**: A record of a merge decision — either phone-
  match or fuzzy name-match. Includes the two company identities, the
  match type, similarity score, and timestamp.
- **PipelineSummary**: The dict returned by `main_pipeline()`. Must
  contain `neo4j_failed` and per-target disposition fields.
- **ReviewLog**: A file at `debug_output/fuzzy_matches.log` that
  accumulates fuzzy-match records across runs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Pipeline operator can determine every target's outcome
  (reason for skip, record count if attempted) from log output alone in
  under 30 seconds — no source code reading required.
- **SC-002**: Fuzzy-match review file is parseable by a human reviewer —
  each line contains both company names, the score, and a clear indicator
  of whether the merge was committed.
- **SC-003**: `grep -r "lead_score" dashboard.html` returns zero matches
  after every build step. CI fails if a match is found.
- **SC-004**: `git grep` for credential patterns (`proxy.*http`,
  `neo4j.*://`, `password`) across tracked files returns zero false
  positives (only env-var references and safe patterns).
- **SC-005**: Re-running the same batch twice yields identical node,
  relationship, and row counts with zero exceptions.

## Assumptions

- The pipeline is the sole writer to Neo4j and the SQLite database.
  Concurrent writes from another process are not expected during a run.
- The `debug_output/` directory is gitignored and may be deleted between
  runs without affecting correctness.
- Reviewers perform fuzzy-match spot-checks manually; no automated
  approval gate is required.
- The existing `.gitignore` already excludes `.env`, `debug_output/`, and
  checkpoint directories. Only verification is needed, not creation.
- Credential scanning assumes standard patterns (`password=`,
  `NEO4J_URI=`, `http://user:pass@`) — non-standard encodings or
  obfuscation are outside scope.
