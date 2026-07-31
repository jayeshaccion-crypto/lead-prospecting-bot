# Contract: JustDial ASN Confirmation Test (FR-003, FR-004, FR-009, FR-010)

**Purpose**: Define the bounded, once-daily X/10 probe that runs in datacenter mode — the entire JustDial activity for the day.

## Entry conditions

The test runs if and only if **all** of these hold:

1. `_determine_jd_mode() == "datacenter"` (residential var unset, Webshare pool present)
2. The persisted flag `counts.__jd_asn_test` is **absent** for today (never re-runs within the same calendar day — FR-009)
3. The probe URL passes `is_robots_allowed()` (reuses the gate at spider.py:307)

## Execution flow

1. **Build candidates** (≤ 10 distinct Webshare proxy IPs):
   - Distinct entries already in `_PROXY_POOL` (deduplicated by credential-free `host:port`) are preferred — no API call when 2+ distinct IPs are present.
   - Only when the pool is a single rotating endpoint (`WEBSHARE_PROXY_URL`, ≤1 distinct IP) **and** `WEBSHARE_API_KEY` is set → `_fetch_proxies_from_api(api_key)` (engine.py:15-36) for the full list. If that fetch fails, fall back to the pool's own rotating endpoint (a single X=1 probe) instead of aborting the test.
   - Cap at 10 distinct IPs. If the pool has fewer, X reflects the actual count.
2. **Construct rotator**: `ProxyRotator(candidates)` (from `scrapling.fetchers`, cyclic rotation).
3. **Probe**: for each attempt (up to 10):
   - `proxy = rotator.get_proxy()`
   - Issue a **single** request to the probe URL with `proxy=` set (per-request override), reusing the existing `justdial_session` (AsyncStealthySession) — no parallel fetch stack. A politeness `wait` (≥ 2000ms, from the target's `page_delay`) spaces consecutive probes.
   - Classify (see tally) using the existing `is_blocked()` semantics so the Y tally matches crawl blocking.
4. **Persist flag**: only after the probe loop completes, write `counts.__jd_asn_test = 1` to `data/request_counts.json` via `DomainRequestCounter._save()`. Skip/no-op paths (empty candidates, no probe URL, robots-disallowed, aborted loop, API fetch failure) do **not** write the flag, so a later run the same day can retry.
5. **Log** (FR-005 and, conditionally, FR-006) — see summary-lines.md.

The test must be wrapped in try/except — a failure inside `_run_asn_test()` never crashes the run.

## Tally

| Count | Meaning | Classification |
|-------|---------|----------------|
| `X` | Distinct proxy IPs attempted | Every `rotator.get_proxy()` call that issues a request; `X == min(10, distinct candidates)`; `X <= 10` |
| `Y` | Blocked | Classified by the existing `is_blocked()` semantics: status in `BLOCKED_STATUS_CODES`, OR response body < 500B, OR request error (connection refused / timeout / no usable body) |
| `Z` | Succeeded | Usable response with body ≥ 500B |

**Invariant**: `X == Y + Z`.

**Note on Z**: literal complement of the spec's blocked definition (body ≥ 500B). A stricter "≥ 1 real listing selector match" variant was considered during clarify (Q2, recommended) but the user proceeded to plan without selecting it — flagged as deferred in research.md (R5).

## Robots.txt

The probe URL MUST pass `is_robots_allowed()` before any request is issued. If disallowed, the probe is skipped with a `RobotsDisallowed` error logged (consistent with crawl behavior).

## Idempotency (FR-009)

- Once `__jd_asn_test` is written for a date, no second run on that date may run the probe or crawl JustDial.
- Date rollover clears the flag automatically (`DomainRequestCounter._load()` discards stale counts).
- The flag write and the verdict log happen in the same run; re-running does not change verdict counts (the test simply does not run again).
- The flag is written **only after a completed probe**. Skipped or aborted probes (see failure handling) leave the flag absent so a later run on the same day can retry.

## Failure handling

| Failure | Behavior |
|---------|----------|
| Webshare API call fails | Pool empty → mode `no_proxy`; JustDial skipped with warning; no probe |
| `_fetch_proxies_from_api` fails during candidate building (rotating endpoint + API key) | Falls back to the pool's own rotating endpoint (X=1); flag written only if that probe completes |
| `ProxyRotator` empty | Guard: if candidates list empty, skip probe with warning; flag NOT written (a later run may retry) |
| A probe request errors | Counted as blocked (Y); tally continues |
| Exception in probe loop | Caught; run continues; existing JustDial disposition logged; flag NOT written |
