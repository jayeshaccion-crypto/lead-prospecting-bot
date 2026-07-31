# Implementation Plan: Spider Migration — Crawl Orchestration

**Branch**: `003-spider-migration` | **Date**: 2026-07-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-spider-migration/spec.md`

## Summary

Replace the current scatter of per-site fetch loops with a single `LeadSpider` subclass of `scrapling.spiders.Spider`. Three session instances are routed by `sid`: `AsyncStealthySession` for JustDial/IndiaMart (proxy, geoip, Cloudflare-solving), `FetcherSession` for TradeIndia (plain, no proxy). Per-domain throttling is configured via Scrapling's Scheduler (`download_delay`). Blocked-response detection (429 or 200-with-body<500B) lives in `is_blocked()`/`retry_blocked_request()` hooks. Checkpointing uses Scrapling's built-in file-based mechanism (`.scrapling_checkpoints/`). Global concurrency capped at 2.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**: scrapling (Spider, SessionManager, AsyncStealthySession, FetcherSession, CrawlerEngine, Request, Response)

**Storage**: Checkpoint — file-based, `.scrapling_checkpoints/` directory, managed by Scrapling's `CrawlerEngine` (periodic JSON snapshots of request queue + scheduler state)

**Testing**: pytest (existing 352 tests), plus new unit tests for `is_blocked()` and session-routing edge cases

**Target Platform**: Windows Server / Linux (GitHub Actions worker)

**Project Type**: CLI pipeline (scrape → enrichment → scoring → persistence)

**Performance Goals**: No hard latency target; crawl completes within daily window defined by cron schedule

**Constraints**: Max 2 concurrent requests globally; per-domain throttle delays: IndiaMart 8-20s, JustDial 5-10s, TradeIndia 0s

**Scale/Scope**: 10 categories × 10 cities across 3 sites with daily request caps from config

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Relevance | Verdict |
|-----------|-----------|---------|
| **I. Robots.txt Compliance** | Scrapling Spider already integrates `StealthyFetcher`; existing `is_robots_allowed()` check in `start_requests()` must be preserved | **Pass** — migration preserves robots check |
| **II. No LinkedIn Scraping** | Not affected — only directory sites | **Pass** — no LinkedIn code path |
| **III. Credential Security** | Proxy URLs + session credentials from env vars; `FetcherSession` has no proxy (TradeIndia) so no credential needed; `AsyncStealthySession` proxy passed via env. No credentials in code or logs | **Pass** — same pattern as existing |
| **IV. Idempotent Operations** | Checkpointing via `crawldir` prevents duplicate processing (pending queue only; completed requests never re-executed on resume). **Note**: it is idempotent for duplicates, NOT lossless — items collected before a crash are dropped (`_items.clear()` on resume). This is a completeness gap, not an idempotency violation. | **Pass with caveat** — no duplicate records possible; document the loss window |
| **V. Resilient Scraping — Fail Loudly** | Each site wrapped in Spider's error handling; blocked responses retried up to 3x; JD stats logged on close | **Pass** — Spider hooks handle this |
| **VI. CodeGraph-First Retrieval** | Not applicable to runtime code | N/A |
| **VII. CONTEXT USED Declaration** | Plan written with CodeGraph exploration of spider.py, engine.py, targets.py, Scrapling Spider base class | **Pass** |
| **VIII. Scope-Fidelity Enforcement** | Scope is crawl orchestration only — parsers, enrichment, graph DB, scoring untouched | **Pass** |
| **IX. Knowledge Graph Authoritative** | No new entities needed; existing session/scheduler/checkpoint entities sufficient | **Pass** |
| **X. Reproducibility Statement** | Plan decisions documented with rationale | **Pass** |

**Gate verdict**: ✅ ALL GATES PASS — no violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/003-spider-migration/
├── plan.md              # This file
├── research.md          # Phase 0 — resolved unknowns
├── data-model.md        # Phase 1 — session/scheduler/checkpoint contracts
├── quickstart.md        # Phase 1 — validation guide
├── contracts/           # Phase 1 — session-kwargs factory, blocked-response, scheduler config
└── tasks.md             # (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/
└── scraper/
    ├── spider.py          # LeadSpider subclass — this feature's primary deliverable
    ├── engine.py          # scrape_all_targets() entry point (updated to match)
    └── targets.py         # PARSER_REGISTRY, _build_page_url(), detail enrichment — UNCHANGED

tests/
├── test_engine.py         # Existing tests (verify no regression)
├── test_spider.py         # New tests for is_blocked(), session routing
└── conftest.py            # Shared fixtures (unchanged)
```

## Complexity Tracking

*(Left blank — no Constitution violations to justify.)*

---

# Phase 0: Outline & Research

## Research Tasks

No unresolved NEEDS CLARIFICATION items exist. The clarifications session and codebase exploration resolved all unknowns:

| Unknown | Resolution | Source |
|---------|-----------|--------|
| URL generation / `start_requests()` | Maps cleanly — existing `_build_source_url()` + `_build_page_url()` yield `Request` objects | Code analysis |
| Blocked-response detection | Relocate existing `is_blocked()` / `retry_blocked_request()` into Spider hooks | Code analysis |
| Checkpoint mechanism | Reuse existing `.scrapling_checkpoints` via `crawldir` — Scrapling's native JSON file-based checkpointing | Code analysis |
| Global concurrency | Max 2 concurrent requests, confirmed in spec clarifications | Spec clarification |

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Session kwargs construction | Dict-of-factories keyed by `sid` | Structurally impossible for stealth kwargs to reach `FetcherSession` — each factory builds only its allowed kwargs. No shared dict, no post-hoc filtering. |
| Scheduler config | Scrapling `download_delay` map per domain via `CrawlerEngine` options | Built into Scrapling; no custom timer logic. Integrates with checkpointing. |
| Blocked-response hook | Override `Spider.is_blocked()` and `Spider.retry_blocked_request()` | Native Spider hooks — max_blocked_retries set on class attribute. |
| Checkpoint storage | File-based JSON via `crawldir=".scrapling_checkpoints"` | Already wired; requires no new infrastructure. Scrapling manages format internally. |

---

# Phase 1: Design & Contracts

## 1. Spider Subclass Structure

### Class: `LeadSpider(scrapling.spiders.Spider)`

```python
class LeadSpider(Spider):
    name = "lead_spider"
    concurrent_requests = 2          # Global cap — FR-010
    max_blocked_retries = 3           # FR-005

    def __init__(self, targets_config: list[dict]):
        ...
        super().__init__(crawldir=".scrapling_checkpoints")

    def configure_sessions(self, manager: SessionManager) -> None:
        # FR-002: TradeIndia — plain FetcherSession, no proxy
        manager.add("tradeindia_session", FetcherSession())

        # FR-002: JustDial — stealth, proxy, geoip, Cloudflare-solving
        stealth_kw = {...}
        manager.add("justdial_session",
            AsyncStealthySession(capture_xhr=r".*", **stealth_kw), lazy=True)

        # FR-002: IndiaMart — stealth, proxy (no capture_xhr)
        manager.add("indiamart_session",
            AsyncStealthySession(**stealth_kw), lazy=True)
```

### `start_requests()` — sid assignment per request

Each yielded `Request` carries its `sid` so the `SessionManager` routes it to the correct session. Logic:

```text
for each target in targets_config:
    site_key = target["name"].lower()
    sid = SID_BY_NAME[site_key]  →  "justdial_session" / "indiamart_session" / "tradeindia_session"
    parser = target["parser"]
    pages = target["pages"]

    for each category × city combination:
        source_url = _build_source_url(site_key, category_slug, city_slug)
        for page_num in pages:
            page_url = _build_page_url(parser, source_url, page_num)

            # FR-003: session-specific kwargs — see §2 below.
            # The dict-of-factories pattern is BINDING, not this pseudocode.
            # The `if site_key in (...)` conditional pattern shown here is
            # illustrative ONLY and must NOT be implemented (it can leak).
            session_kwargs = _make_session_kwargs(sid, fetch_kwargs, proxy)

            yield Request(page_url, sid=sid, meta={...}, **session_kwargs)
```

### `parse()` callback signature

```python
async def parse(self, response: Response) -> AsyncGenerator[dict | None, None]:
    meta = response.meta
    parser_name = meta["parser"]
    records = PARSER_REGISTRY[parser_name](response, source_url=meta["source_url"])
    ...
    for rec in records:
        yield { ... }   # scraped item dict
```

## 2. Session-Specific Kwargs Construction (FR-003 — Bug Guard)

**Mechanism**: Per-site kwarg construction dict, keyed by `sid`. Each entry is a factory function that returns only the kwargs valid for that session type.

```python
_SESSION_KWARG_FACTORIES: dict[str, Callable[[dict], dict]] = {
    SID_JUSTDIAL: _make_stealth_kwargs,     # returns proxy, wait, wait_selector
    SID_INDIAMART: _make_stealth_kwargs,    # returns proxy, wait, wait_selector
    SID_TRADEINDIA: lambda _: {},            # returns empty dict — no browser-only kwargs
}
```

Call site in `start_requests()`:

```python
factory = _SESSION_KWARG_FACTORIES[sid]    # ← dict lookup, not if/elif
session_kwargs = factory(fetch_kwargs)
yield Request(url, sid=sid, **session_kwargs)
```

A new sid added in the future MUST add an entry to `_SESSION_KWARG_FACTORIES` or the dict lookup fails loudly (`KeyError`). There is no shared kwargs dict, no `if sid == X` branching, no post-hoc filtering.

## 3. Scheduler Configuration

Configured via class attributes on `LeadSpider`:

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `concurrent_requests` | `2` | Global max concurrent requests across all sites |
| `download_delay` | `0.0` | Not used — per-domain via Scheduler config |
| `autothrottle_enabled` | `False` | Manual throttle only |

Per-domain delay is enforced by `start_requests()` yielding `Request` objects with `sid` routing to sessions that have domain-level delay configured. Scrapling's `CrawlerEngine` applies `download_delay` as a minimum interval between requests from the same session. Since each sid maps to a single domain, the delay applies per domain:

| sid | Delay Range | Implementation |
|-----|------------|----------------|
| `justdial_session` | 5-10s random | `DOMAIN_DELAYS[SID_JUSTDIAL]` → `anyio.sleep(random.uniform(5.0, 10.0))` before next yield |
| `indiamart_session` | 8-20s random | `DOMAIN_DELAYS[SID_INDIAMART]` → `anyio.sleep(random.uniform(8.0, 20.0))` |
| `tradeindia_session` | 0s | No delay |

*(The delay is applied by `CrawlerEngine` at fetch time via the spider's `download_delays` range map (per-request `random.uniform`, serialized per domain by `concurrent_requests_per_domain = 1`). This throttles actual network requests and re-applies a fresh random delay on resume — see `contracts/scheduler-config.md`. Delay logic does NOT live in `start_requests()`.)*

## 4. Blocked-Response Detection

### Hook: `is_blocked()`

```python
async def is_blocked(self, response: Response) -> bool:
    """FR-004: 429 or 200-with-body<500B counts as blocked."""
    if response.status == 429:
        return True
    if response.status == 200:
        body = response.body
        body_size = len(body) if isinstance(body, bytes) else len(str(body).encode("utf-8"))
        if 0 < body_size < 500:
            return True
    return False
```

### Hook: `retry_blocked_request()`

```python
async def retry_blocked_request(self, request: Request, response: Response) -> Request:
    """Rotate proxy on retry for stealth sessions; log the block."""
    from src.scraper.engine import _get_next_proxy
    proxy = _get_next_proxy()
    if proxy:
        request._session_kwargs["proxy"] = proxy
    else:
        request._session_kwargs.pop("proxy", None)

    sid = request.sid
    if sid in (SID_JUSTDIAL, SID_INDIAMART):
        log_proxy = str(proxy).partition("@")[-1] if proxy else "none"
        self.logger.warning("Blocked %s via %s — retrying with next proxy", sid, log_proxy)

    return request
```

These hooks are registered automatically by Scrapling's Spider base class — overriding them in the subclass is sufficient. `max_blocked_retries = 3` is read by `CrawlerEngine`.

### JustDial ASN stats tracking

The existing `_jd_stats` dict and summary logging in `on_close()`) is preserved unchanged (lines 491-508 of current spider.py).

### JustDial proxy wiring (residential mode)

`RESIDENTIAL_PROXY_URL_JUSTDIAL` selects the `residential` JD mode. In that mode
`LeadSpider._proxy_for(SID_JUSTDIAL)` (and `retry_blocked_request()` on retry)
use the residential rotating endpoint directly; datacenter rotation via
`_get_next_proxy()` is NOT applied to JD in residential mode. All other stealth
sids (IndiaMART, JD datacenter mode) use the shared WEBSHARE pool. If the mode is
`no_proxy` the target is skipped with a `ProxyNotConfigured` error (never silent).

## 5. Checkpoint Storage Mechanism

| Property | Value |
|----------|-------|
| **Mechanism** | File-based JSON snapshots |
| **Directory** | `.scrapling_checkpoints/` (relative to CWD) |
| **Managed by** | Scrapling's `CrawlerEngine` |
| **Triggered by** | Periodic interval (default 300s) + SIGINT / graceful shutdown |
| **Format** | Internal Scrapling format — opaque to this feature |
| **Contents** | Serialized request queue (pending requests), scheduler state (delay timers), completed item set |
| **Resume** | `Spider.start()` with existing `crawldir` detects checkpoint file and resumes from last saved state |
| **Schema** | Scrapling-managed — no custom schema defined |

`.scrapling_checkpoints/` is already in `.gitignore` (per T003).

> **Security note**: `.scrapling_checkpoints/checkpoint.pkl` pickles pending
> `Request` objects including their `_session_kwargs`, which contain proxy URLs
> (`http://user:pass@host:port`) — plaintext credentials at rest. The directory is
> gitignored and local to the run environment; do not copy it off the host.
>
> **Completeness caveat (SC-004)**: the checkpoint persists only the pending
> request queue + seen-set — NOT scraped items. On resume the in-memory
> `all_records` from before the crash are lost; only still-pending URLs are
> re-fetched. See spec.md SC-004 (reconciled).

## 6. Project Structure — Source Tree

The migration touches only `src/scraper/spider.py` and `src/scraper/engine.py`. No new files in source tree.

```text
src/scraper/
├── __init__.py
├── spider.py        # MODIFIED — LeadSpider refactored to clean Spider subclass
├── engine.py        # MODIFIED — scrape_all_targets() updated for new constructor/results
├── targets.py       # UNCHANGED — parsers, detail enrichment, pagination helpers
└── utils.py         # UNCHANGED — is_robots_allowed()
```

## Source Code (repository root) — Existing test structure

```text
tests/
├── test_engine.py   # UNCHANGED — existing tests must pass at same volume
├── test_spider.py   # NEW — unit tests for is_blocked(), session routing, kwarg factories
└── conftest.py      # UNCHANGED
```
