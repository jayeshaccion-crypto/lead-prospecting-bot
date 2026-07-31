# Research: Spider Migration — Crawl Orchestration

**Date**: 2026-07-30 | **Context**: Phase 0 of implementation plan

## Resolved Unknowns

All unknowns were resolved through codebase exploration and specification clarifications. No NEEDS CLARIFICATION markers remain.

### 1. URL Generation / `start_requests()` Mapping

- **Decision**: Clean mapping — existing URL generation reused without rebuild
- **Rationale**: `LeadSpider.start_requests()` (spider.py:179) already yields `Request` objects with `sid`, `meta`, and session kwargs. URL templates live in `SITE_URL_TEMPLATES` and config-driven `_url_templates`. Pagination uses `_build_page_url()` from targets.py. The existing loop structure maps directly onto Scrapling's Request/Response pattern.
- **Alternatives considered**: Rebuilding URL generation was rejected because the existing code already produces compatible `Request` objects.

### 2. Blocked-Response Detection

- **Decision**: Relocate existing logic into Spider's `is_blocked()` and `retry_blocked_request()` hooks
- **Rationale**: Existing `is_blocked()` (spider.py:393-400) already detects 429 + sub-500-byte 200 bodies. Existing `retry_blocked_request()` (spider.py:402-426) rotates proxy and logs. These are exact matches for Scrapling's hook signatures. Only status-code narrowing is needed (spec asks for 429 only, current code has broader list — user confirmed to relocate as-is).
- **Alternatives considered**: Rewriting from scratch rejected — existing logic is correct and tested.

### 3. Checkpoint Mechanism

- **Decision**: Reuse existing `.scrapling_checkpoints` via `crawldir`
- **Rationale**: `super().__init__(crawldir=".scrapling_checkpoints")` is already wired at spider.py:142. Scrapling's `CrawlerEngine` manages periodic JSON snapshots of request queue + scheduler state. Already gitignored.
- **Alternatives considered**: Custom DB-based checkpointing rejected — adds infrastructure with no benefit for local runs.

### 4. Global Concurrency Cap

- **Decision**: Max 2 concurrent requests globally, in addition to per-domain throttling
- **Rationale**: Matches existing `concurrent_requests = 2` at spider.py:116. Conservative enough to avoid rate-limit cascades across sites.
- **Alternatives considered**: No cap (rely solely on per-domain delays) rejected — could overwhelm remote servers when multiple sites yield simultaneously.

## Architecture Decisions

### Session Kwargs Construction

- **Decision**: `_SESSION_KWARG_FACTORIES` dict keyed by sid, each entry a factory function returning only valid kwargs for that session type
- **Rationale**: Structurally impossible for stealth kwargs to reach `FetcherSession`. No shared dict, no if/elif branching, no post-hoc filtering. New sids MUST add a factory or fail with `KeyError`.
- **Alternatives considered**: Single kwargs dict with filter function (rejected — bug-prone, the prior defect), separate `if sid == X` branches (rejected — easy to miss a branch when adding new sites).

### Per-Domain Throttling

- **Decision**: Random-range delay applied in `start_requests()` between page yields, integrated with Spider's pause/checkpoint flow
- **Rationale**: Scrapling's `download_delay` attribute supports a fixed delay; spec requires random ranges (8-20s, 5-10s). Explicit `anyio.sleep(random.uniform(...))` in `start_requests()` preserves the Spider's co-operative multitasking and integrates with `CrawlerEngine`'s pause mechanism.
- **Alternatives considered**: Custom scheduler plugin (rejected — over-engineering for three domains), fixed delay via `download_delay` (rejected — doesn't satisfy random-range requirement).
