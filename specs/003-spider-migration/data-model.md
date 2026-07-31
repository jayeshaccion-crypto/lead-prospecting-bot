# Data Model: Spider Migration — Crawl Orchestration

**Date**: 2026-07-30 | **Context**: Phase 1 design artifact

## Entities

### 1. Session

A pre-configured fetch context assigned to one site. Managed by `SessionManager`.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `id` | string | Session identifier (sid) | One of `justdial_session`, `indiamart_session`, `tradeindia_session` |
| `type` | enum | Session class | `Stealthy` (JD/IM) or `Plain` (TI) |
| `proxy_enabled` | bool | Whether proxy is configured | `true` for stealth, `false` for plain |
| `geoip` | bool | Geo-hinting enabled | `true` for stealth, N/A for plain |
| `humanize` | bool | Human-like behavior | `true` for stealth, N/A for plain |
| `solve_cloudflare` | bool | Cloudflare challenge solving | `true` for stealth, N/A for plain |
| `lazy_start` | bool | Defer session start until first use | `true` for stealth (lazy), `false` for plain |

**Relationships**:
- One Session per sid (justdial, indiamart, tradeindia)
- Session receives Request objects tagged with matching sid
- Session is started by `SessionManager.start()` (or lazily on first fetch)

### 2. Request

A single URL fetch instruction. Scrapling's native `Request` object.

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Target URL |
| `sid` | string | Session routing identifier |
| `meta` | dict | Arbitrary metadata (parser name, source_url, category, city, page, etc.) |
| `_session_kwargs` | dict | Session-specific kwargs (proxy, wait, wait_selector — only for stealth sessions) |

**Validation**:
- `sid` MUST match a registered session name
- `_session_kwargs` MUST NOT contain browser-only kwargs when `sid` is `tradeindia_session` (enforced by factory dict, not by validation)

### 3. Response

Scrapling's native `Response` object, returned from `SessionManager.fetch()`.

| Field | Type | Description |
|-------|------|-------------|
| `status` | int | HTTP status code |
| `body` | bytes | Response body |
| `html_content` | bytes\|None | Parsed HTML, if available |
| `text` | str | Decoded body text |
| `captured_xhr` | list\|None | Captured XHR responses (JustDial only) |
| `meta` | dict | Merged metadata from request + response |
| `request` | Request | The originating Request object |

### 4. Scheduler

Rate-limiting mechanism. Configured via class attributes on `LeadSpider`.

| Property | Type | Description |
|----------|------|-------------|
| `concurrent_requests` | int | Global max concurrent requests (default: 2) |
| `max_blocked_retries` | int | Max retries for blocked responses (default: 3) |
| `download_delay` | float | Not used — per-domain random delay applied in `start_requests()` |

**Domain delay map** (applied in `start_requests()`, not a formal entity):

| Domain | Delay Range |
|--------|-------------|
| justdial.com | 5-10s random |
| indiamart.com | 8-20s random |
| tradeindia.com | 0s (no delay) |

### 5. Checkpoint

File-based persistable state, managed by Scrapling's `CrawlerEngine`.

| Property | Description |
|----------|-------------|
| **Storage** | `.scrapling_checkpoints/` directory |
| **Format** | JSON (Scrapling internal) |
| **Contents** | Serialized request queue, scheduler state, completed-item set |
| **Interval** | Every 300s (default) + on graceful shutdown |
| **Resume** | `Spider.start()` detects existing crawldir and resumes |

### 6. Blocked Response

A response classified as blocked, triggering retry logic.

| Classification | Condition |
|----------------|-----------|
| Status blocked | `response.status == 429` |
| Empty-body blocked | `response.status == 200` AND `0 < body_size < 500` bytes |
| Not blocked | Everything else |

**State transitions**:
```
Request → fetch → Response
                     ├── not blocked → parse()
                     └── blocked → retry_count++
                                    ├── retry_count ≤ 3 → retry with new proxy
                                    └── retry_count > 3 → log failure, skip
```

## Entity Relationships

```
LeadSpider
  ├── SessionManager
  │     ├── Session ("justdial_session")     ── routes ──> justdial.com requests
  │     ├── Session ("indiamart_session")    ── routes ──> indiamart.com requests
  │     └── Session ("tradeindia_session")   ── routes ──> tradeindia.com requests
  │
  ├── start_requests() → yields Request(url, sid, meta, **session_kwargs)
  │     └── _SESSION_KWARG_FACTORIES[sid](fetch_kwargs)  ← per-type kwargs
  │
  ├── parse(response) → yields scraped items (dict)
  │
  ├── is_blocked(response) → bool          ← hook overridden
  ├── retry_blocked_request(request, response) → request  ← hook overridden
  │
  └── on_close()                           ← summary logging (JD stats, fill rates)
        └── CrawlerEngine (via crawldir)   ← checkpoint management
```
