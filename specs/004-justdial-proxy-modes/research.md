# Research: JustDial Three-Mode Proxy Routing

**Date**: 2026-07-31 | **Context**: Phase 0 research for `specs/004-justdial-proxy-modes`

## R1. Env var reading logic and precedence

**Decision**: Reuse the existing `_determine_jd_mode()` (src/scraper/spider.py:214-222) unchanged. Precedence, evaluated in order:

1. `os.environ.get("RESIDENTIAL_PROXY_URL_JUSTDIAL", "").strip()` non-empty → `residential`
2. `_engine_mod._PROXY_POOL` non-empty (populated by `_init_proxy_pool()` from `WEBSHARE_PROXY_URL`, `WEBSHARE_PROXY_LIST`, or `WEBSHARE_API_KEY`) → `datacenter`
3. otherwise → `no_proxy`

Residential takes priority if both are set (the first check wins). A whitespace-only residential value is treated as unset (`strip()`). **No new `PROXY_URL_JUSTDIAL` variable is introduced** — verified by codegraph that it does not exist anywhere, and the user confirmed reusing the WEBSHARE pool.

**Rationale**: Code already implements the exact requested precedence; changing it would risk regressions in Phase 1 wiring (`_proxy_for`, `retry_blocked_request`).

**Alternatives considered**:
- Add a new `PROXY_URL_JUSTDIAL` datacenter selector → rejected (per clarification Q1; WEBSHARE pool already is the datacenter source).

## R2. "Already ran today" flag storage

**Decision**: Extend `DomainRequestCounter` (src/scraper/spider.py:110-153) with ASN-test flag methods writing to the **same** `data/request_counts.json` file, reusing its existing date-reset semantics.

The file schema is `{"date": "YYYY-MM-DD", "counts": {domain: n}}` and `_load()` discards `counts` when `date` != today, giving free per-calendar-day expiry. The flag is stored as a reserved key in `counts`:

```json
{"date": "2026-07-31", "counts": {"justdial.com": 3, "__jd_asn_test": 1}}
```

A reserved `__jd_asn_test` key (or a dedicated `asn_test_date` field) set to `1` marks "tested today". Presence check: `counts.get("__jd_asn_test")` (only present when date == today, because `_load` discards stale counts). This satisfies FR-009 / Q4: once-per-calendar-day holds even across manual re-runs (workflow_dispatch) and retries.

**Rationale**: Zero new files, zero new persistence mechanisms, matches the "reuse existing state storage" assumption in spec.md and clarification Q4.

**Alternatives considered**:
- Separate `data/justdial_asn_test.json` file → rejected in Q4 (user picked Option A: reuse existing daily state file).
- In-memory-only flag → fails SC-003 (second same-day run must not re-run).

## R3. ProxyRotator integration for the X/10 test

**Decision**: Use `scrapling.fetchers.ProxyRotator` (exists in vendored submodule, `scrapling/engines/toolbelt/proxy_rotation.py`, cyclic rotation, thread-safe) to drive the probe.

Flow inside a new `LeadSpider._run_asn_test()`:

1. Build the distinct-IP candidate list:
   - Prefer distinct entries already in `_PROXY_POOL` (deduped by `server|username` key semantics) — `_init_proxy_pool()` may already have populated it from the Webshare API, so this avoids a duplicate API call.
   - Only if the pool is a single rotating endpoint (`WEBSHARE_PROXY_URL`, no distinct IPs) → call `_fetch_proxies_from_api(api_key)` (engine.py:15-36) for the full distinct IP list.
   - Cap candidates at 10 distinct IPs.
2. Construct `ProxyRotator(candidates)` (cyclic rotation).
3. For each of up to 10 attempts: `proxy = rotator.get_proxy()`; issue a single request to the probe URL with `proxy=` set (per-request proxy override — supported by Scrapling sessions and already used in `retry_blocked_request` via `request._session_kwargs["proxy"]`).
4. Tally: X = distinct IPs attempted; Y = blocked (body < 500B or request error); Z = succeeded (body ≥ 500B). Log verdict (FR-005); if Y == X log CONCLUSION (FR-006).

**Rationale**: ProxyRotator is the canonical rotation mechanism the user specified, exists in the project's vendored dependency, and its cyclic strategy guarantees each distinct IP gets its single request without manual index bookkeeping.

**Alternatives considered**:
- Manual `_get_next_proxy()` rotation → functionally similar but duplicates what ProxyRotator provides and diverges from the user's explicit request.
- Static per-IP loop without rotator → rejected; user explicitly asked "rotate through each one via ProxyRotator".

## R4. ASN probe URL

**Decision**: A single representative JustDial category-listing page (FR-010). The exact URL is chosen at tasks time from the existing `url_templates` config (`justdial` template + a configured category/city). It must pass `is_robots_allowed()` before fetching (reuses the gate at spider.py:307).

**Rationale**: The probe is for block detection, not data collection. One real category-listing URL is representative of the crawl's actual requests.

**Alternatives considered**: Homepage probe → rejected (less representative of block behavior on listing pages); multiple URLs → rejected (test must stay ≤10 requests and minimal).

## R5. Definition of Z ("succeeded")

**Decision**: Succeeded = a usable response with body ≥ 500 bytes (literal complement of the spec's blocked definition: body < 500B or request error = blocked). No selector/content check in this feature.

**Rationale**: The spec (Assumptions) defines blocked as body < 500B or error; Z is its complement. The user proceeded from clarify to plan without selecting the stricter "listing selector match" option (Q2, recommended Option A), so the literal written definition is used to avoid unrequested scope.

**Deferred**: The stricter variant (Z requires ≥1 real listing selector match on the probe page; a large non-listing body counts as blocked and feeds CONCLUSION) was the clarify recommendation and is flagged as a follow-up candidate. If real crawls show large non-listing block pages, revisit under a future feature or amendment.

**Alternatives considered**: Option B (body ≥ 500B only — adopted), Option C (HTTP 200 with body ≥ 500B; any other status counts failed — the blocked-status superset in `is_blocked()` already treats 4xx/5xx as blocked, making this behaviorally close to C for status codes).

## R6. End-of-run summary strings

**Decision**: Exact strings for all three modes (see contracts/summary-lines.md for the full contract). Mode reported in the run summary as `JustDial mode: residential | datacenter-ASN-test | no_proxy`, matching FR-008's labels. The current `on_close()` already logs `JustDial mode: %s` (spider.py:586) but reports the internal value; the contract maps the display label for datacenter to `datacenter-ASN-test` so the summary is unambiguous.

**Rationale**: FR-008 requires the summary to state the mode explicitly and the user's plan input demands "matching the wording in the spec precisely".

**Alternatives considered**: Keep internal `datacenter` label in summary → rejected; FR-008's stated labels are `residential / datacenter-ASN-test / no-proxy`.

## R7. Webshare API failure handling

**Decision**: If the Webshare API call fails (network, bad key, rate limit), treat the pool as empty → mode degrades to `no_proxy`; JustDial skipped with explicit warning + `ScrapeError("ProxyNotConfigured")`. The probe itself never crashes the run (try/except around `_run_asn_test`).

**Rationale**: Matches spec Edge Cases ("A failed test must never crash the run") and constitution V (fail loudly, never silently degrade).

**Alternatives considered**: Retry the API fetch → adds complexity; `_init_proxy_pool` already warns on API failure and the daily cadence retries naturally next run.
