# Data Model: JustDial Three-Mode Proxy Routing

**Date**: 2026-07-31 | **Context**: Phase 1 design artifact

## Entities

### 1. JustDial Proxy Mode

The resolved mode for a run, computed from env state by `LeadSpider._determine_jd_mode()` (src/scraper/spider.py:214-222).

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `_jd_mode` | string | `residential` \| `datacenter` \| `no_proxy` | Internal mode value on `LeadSpider` (defaults `"unknown"` until resolved) |
| display label | string | `residential` \| `datacenter-ASN-test` \| `no_proxy` | Label used in the end-of-run summary (FR-008) |

**Derivation rule** (precedence, first match wins):
1. `RESIDENTIAL_PROXY_URL_JUSTDIAL` non-empty after `strip()` → `residential`
2. `_PROXY_POOL` non-empty → `datacenter`
3. else → `no_proxy`

**Validation**: A whitespace-only residential value MUST be treated as unset. Residential wins when both residential and pool are present.

**State transitions**:
- `unknown` → resolved once at spider start (`on_start`/`start_requests`) → one of the three values.
- Mode is fixed for the duration of a run; it does not change mid-crawl.

### 2. ASN Test State

Per-calendar-day record that the JustDial ASN confirmation test already ran. Persisted in the existing `data/request_counts.json` file (managed by `DomainRequestCounter`, src/scraper/spider.py:110-153).

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `date` | string | `YYYY-MM-DD` | Existing top-level key; `_load()` discards `counts` when `date` != today |
| `counts.__jd_asn_test` | int | Marker that the ASN test ran today | Present `== 1` on days the test ran; absent otherwise |
| `counts.<domain>` | int | Existing per-domain daily request caps | Unchanged |

**File schema**:

```json
{
  "date": "2026-07-31",
  "counts": {
    "justdial.com": 3,
    "indiamart.com": 7,
    "__jd_asn_test": 1
  }
}
```

**Validation rules**:
- ASN test allowed iff `counts.get("__jd_asn_test")` is absent (never re-run within the same calendar day, FR-009).
- Writing the flag and saving MUST happen immediately after the test completes (same `_save()` path as `allowed()`).
- Date change automatically resets the flag (existing `_load()` behavior) — no cleanup step needed.

**State transitions**:
- `not-tested-today` → (test runs) → `tested-today`; persists across pipeline runs on the same day.
- `tested-today` → `not-tested-tomorrow` automatically on date rollover via `_load()`.

### 3. ASN Test Result (transient)

Per-run tally of the probe, held in memory on the spider (not persisted — the flag is the only durable state).

| Field | Type | Description |
|-------|------|-------------|
| `X` | int | Distinct proxy IPs attempted (≤ 10) |
| `Y` | int | Blocked: body < 500B or request error |
| `Z` | int | Succeeded: usable response with body ≥ 500B |
| `blocked_ips` | set | Distinct proxy hosts that hit block pages (existing `_jd_stats["blocked_ips"]`, redacted host-only) |

**Invariant**: `X == Y + Z` (every attempt is exactly one verdict); `X <= 10`.

## Relationships

- **JustDial Proxy Mode** selects the run behavior: residential → full crawl; datacenter → ASN test only (no crawl); no_proxy → skip.
- **ASN Test State** gates **ASN Test Result** generation: only one result per calendar day.
- **ASN Test Result** drives the verdict + CONCLUSION log lines (FR-005/FR-006).
