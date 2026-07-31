# Contract: Scheduler Configuration (FR-006, FR-007, FR-010)

**Purpose**: Define global concurrency and per-domain delay settings.

## Global Concurrency

```python
concurrent_requests = 2   # FR-010
```

Maximum 2 concurrent fetches across all three sites. Configurable via class attribute on `LeadSpider`.

## Per-Domain Random Delay

Applied by `CrawlerEngine` at **fetch time** — before each request to a domain is
downloaded — so the spacing actually throttles network requests (delays inside
`start_requests()` would only pace request *generation*, which Scrapling fully
consumes before fetching).

| sid | Domain | Min Delay | Max Delay |
|-----|--------|-----------|-----------|
| `justdial_session` | justdial.com | 5.0s | 10.0s |
| `indiamart_session` | indiamart.com | 8.0s | 20.0s |
| `tradeindia_session` | tradeindia.com | 0.0s | 0.0s |

**Implementation**:

```python
DOMAIN_DELAYS: dict[str, tuple[float, float]] = {
    SID_JUSTDIAL:    (5.0, 10.0),
    SID_INDIAMART:   (8.0, 20.0),
    SID_TRADEINDIA:  (0.0, 0.0),
}
```

`LeadSpider` exposes these ranges to the engine:

```python
class LeadSpider(Spider):
    download_delays = DOMAIN_DELAYS          # keyed by sid (1:1 with domain)
    concurrent_requests_per_domain = 1       # serialize same-domain fetches
    concurrent_requests = 2                  # FR-010 global cap
```

`CrawlerEngine._get_domain_delay()` reads `spider.download_delays` (keyed by
domain netloc or sid), draws `random.uniform(min, max)` **per request**, and the
fetch path sleeps that duration inside the per-domain concurrency limiter — so
consecutive requests to the same domain are spaced by the random delay while the
global `concurrent_requests` cap still applies across domains.

## Interaction with Checkpointing

The delay is applied per-request in the engine's fetch path (`_process_request`),
which runs for both initial and checkpoint-restored requests. Timing state is not
persisted — on resume each request simply draws a fresh random delay, which is
the intended behavior for randomized rate-limiting.

## Vendored Engine Note

`Scrapling/scrapling/spiders/engine.py` is a vendored submodule that has been
**modified** to support per-domain random delay ranges via `spider.download_delays`
(this is not upstream Scrapling behavior):

- `CrawlerEngine._get_domain_delay()` — priority 1 lookup of
  `spider.download_delays[request.domain] or spider.download_delays[request.sid]`,
  drawing `random.uniform(min, max)` per request (engine.py:107-121).
- `CrawlerEngine._process_request()` — `floor = await self._get_domain_delay(request)`
  then `anyio.sleep(delay)` **inside** `async with self._rate_limiter(request.domain)`
  (engine.py:205, 221-226).

On a submodule update this patch MUST be re-applied.
`tests/test_spider.py::TestThrottlingConfig::test_engine_applies_per_domain_delay`
guards it and will fail if the patch is lost.

## Class Attributes (Spider base class)

```python
download_delay = 0.0          # Not used (per-domain random ranges via download_delays)
autothrottle_enabled = False  # Manual throttle only
```
