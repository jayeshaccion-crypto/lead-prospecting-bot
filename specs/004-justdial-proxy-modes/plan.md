# Implementation Plan: JustDial Three-Mode Proxy Routing

**Branch**: `004-justdial-proxy-modes` | **Date**: 2026-07-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-justdial-proxy-modes/spec.md`

## Summary

Give JustDial exactly three proxy modes with a strict precedence, enforced by env state and existing infrastructure (no new env var):

1. **residential** — `RESIDENTIAL_PROXY_URL_JUSTDIAL` is set (non-empty after strip): JustDial is crawled at full configured page depth, every request routed through the residential proxy. Already implemented in Phase 1 (`_determine_jd_mode`, `_proxy_for`, `retry_blocked_request`); must be preserved and covered by the end-of-run mode report.
2. **datacenter** — residential var unset but the Webshare datacenter pool is present (`_PROXY_POOL` non-empty). The pipeline does **no** JustDial crawling. Instead it runs the **ASN confirmation test at most once per calendar day** (persisted flag in `data/request_counts.json`): it enumerates the distinct Webshare proxy IPs, rotates through them via `ProxyRotator` for a single request each (cap 10), and logs a verdict line. If every attempt is blocked (Y == X), it appends the ASN-level CONCLUSION line. The test is the *entire* JustDial activity for the day.
3. **no_proxy** — neither residential var nor Webshare pool. JustDial is skipped with an explicit warning naming the missing env vars and a `ScrapeError(ProxyNotConfigured)`.

The end-of-run summary MUST state which mode JustDial ran in, for all three modes.

## Technical Context

**Language/Version**: Python 3.12 (`pyproject.toml:5` requires-python >=3.12; GitHub Actions `python-version: "3.12"`)

**Primary Dependencies**: scrapling (vendored submodule) — `Spider`, `AsyncStealthySession`, `Request`, `Response`, `scrapling.fetchers.ProxyRotator`; stdlib `httpx` (already used by `_fetch_proxies_from_api` in `src/scraper/engine.py:15`)

**Storage**: `data/request_counts.json` — existing per-day file-based state (`DomainRequestCounter`, `src/scraper/spider.py:110-153`), reset on date change. The ASN-test "already ran today" flag reuses this file (per clarification Q4).

**Testing**: pytest (existing 385 tests) + new unit tests for mode selection precedence, ASN-test verdict counting, flag idempotency, and summary lines.

**Target Platform**: Windows Server / Linux (GitHub Actions worker)

**Project Type**: CLI pipeline (scrape → enrichment → scoring → persistence)

**Performance Goals**: No hard latency target; ASN test is bounded to ≤10 single requests; crawl completes within the daily cron window.

**Constraints**: `_determine_jd_mode()` precedence MUST stay residential > datacenter > no_proxy. Robots.txt compliance MUST apply to the ASN probe URL before the probe is issued. No new env var (`PROXY_URL_JUSTDIAL` is NOT introduced). No JustDial crawling in datacenter mode.

**Scale/Scope**: ≤10 distinct Webshare IPs probed once per calendar day in datacenter mode; full crawl in residential mode.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Relevance | Verdict |
|-----------|-----------|---------|
| **I. Robots.txt Compliance** | The ASN probe URL and any residential crawl URLs MUST pass `is_robots_allowed()` before fetching (existing check in `start_requests`, spider.py:307) | **Pass** — probe reuses the existing robots gate |
| **II. No LinkedIn Scraping** | Not affected — JustDial only | **Pass** |
| **III. Credential Security** | Proxy credentials come only from env vars (`RESIDENTIAL_PROXY_URL_JUSTDIAL`, `WEBSHARE_*`). The ASN test must not log the full proxy URL with embedded credentials — reuse the existing `log_proxy = str(proxy).partition("@")[-1]` redaction (spider.py:480). The date flag file stores no credentials | **Pass** — existing redaction pattern reused |
| **IV. Idempotent Operations** | The ASN test MUST run at most once per calendar day via the persisted flag (FR-009). Re-running the pipeline on the same day MUST NOT repeat the test or alter counts | **Pass** — persisted date-stamped flag guarantees idempotency |
| **V. Resilient Scraping — Fail Loudly** | no_proxy mode logs an explicit warning + `ScrapeError("ProxyNotConfigured")` (already present, spider.py:272-279). Datacenter mode's verdict + CONCLUSION lines are the loud, explicit disposition. A failed Webshare API fetch degrades to no_proxy with a warning — never a silent 0-record JustDial contribution | **Pass** — existing fail-loud pattern extended to the probe |
| **VI. CodeGraph-First Retrieval** | Plan written from CodeGraph exploration of `_determine_jd_mode`, `_proxy_for`, `start_requests`, `on_close`, `DomainRequestCounter`, `_fetch_proxies_from_api`, `ProxyRotator` | **Pass** |
| **VII. CONTEXT USED Declaration** | See **CONTEXT USED** block at top of this plan | **Pass** |
| **VIII. Scope-Fidelity Enforcement** | Scope is JustDial mode routing + ASN test only. Parsers, enrichment, IndiaMart/TradeIndia flows, graph DB, scoring untouched | **Pass** |
| **IX. Knowledge Graph Authoritative** | No new entities beyond `ASN Test State` (documented in data-model.md); reuses `DomainRequestCounter` | **Pass** |
| **X. Reproducibility Statement** | All decisions documented with rationale in research.md | **Pass** |

**Gate verdict**: ✅ ALL GATES PASS — no violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/004-justdial-proxy-modes/
├── plan.md              # This file
├── research.md          # Phase 0 — resolved unknowns
├── data-model.md        # Phase 1 — entities & state schema
├── quickstart.md        # Phase 1 — validation guide
├── contracts/           # Phase 1 — jd-mode contract, asn-test contract, summary contract
└── tasks.md             # (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/
└── scraper/
    ├── spider.py          # LeadSpider — mode selection, ASN probe, flag persistence, summaries
    │                      #   - DomainRequestCounter: + asn test flag methods (extend)
    │                      #   - _determine_jd_mode(): unchanged (precedence already correct)
    │                      #   - start_requests(): datacenter branch yields probe only
    │                      #   - _run_asn_test(): NEW — bounded X/10 probe via ProxyRotator
    │                      #   - is_blocked()/retry_blocked_request(): unchanged
    │                      #   - on_close(): JD mode + verdict + CONCLUSION + summary lines
    ├── engine.py          # _fetch_proxies_from_api (exists), expose _PROXY_POOL distinct-IP helper if needed
    └── targets.py         # untouched

tests/
└── test_spider.py         # NEW tests: mode precedence, probe verdict counts, flag idempotency, summaries

data/
└── request_counts.json    # existing per-day state file; gains a JustDial ASN-test date flag key
```

**Structure Decision**: Single-project layout already in place. All changes land in `src/scraper/spider.py` (mode + probe + summaries) with at most a small helper in `src/scraper/engine.py` to expose distinct IPs from the Webshare pool. No new modules.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations — all gates pass. Nothing to justify.

## Phase 0 — Research (see research.md)

Unknowns resolved:
1. Where does the "already ran today" flag live? → `data/request_counts.json` via extended `DomainRequestCounter` (date-stamped, resets on date change).
2. How to drive the X/10 probe? → `ProxyRotator` from `scrapling.fetchers`, fed by distinct Webshare IPs (prefer Webshare API enumeration via `_fetch_proxies_from_api` when `WEBSHARE_API_KEY` is set, else fall back to distinct entries of `_PROXY_POOL`).
3. What is the probe URL? → A single representative JustDial category-listing page (FR-010), resolved at tasks time; robots-checked before fetching.
4. What counts as Z ("succeeded")? → Literal complement of the spec's blocked definition (Assumptions): a usable response with body ≥ 500 bytes; a request error or body < 500B counts as blocked. A stricter listing-selector match was considered (clarify Q2, recommended Option A) but the user proceeded to plan without selecting it; the literal definition is used to stay faithful to the written spec, and the stricter variant is flagged in research.md as a deferred decision.

## Phase 1 — Design (see data-model.md, contracts/)

Design artifacts delivered:
- **data-model.md** — `JustDial Proxy Mode` and `ASN Test State` entities; the `request_counts.json` schema extension.
- **contracts/jd-mode.md** — exact env-var reading + precedence (FR-001).
- **contracts/asn-test.md** — probe behavior, verdict tally, flag idempotency (FR-003, FR-004, FR-009, FR-010).
- **contracts/summary-lines.md** — exact end-of-run summary strings for all three modes (FR-005, FR-006, FR-008).
- **quickstart.md** — validation scenarios for all three modes.

**Constitution Check re-evaluation (post-design)**: Unchanged — all gates still pass. The probe reuses the robots gate (I), credential redaction (III), and fail-loud summary lines (V). No new persistence system (IV). No scope expansion (VIII).
