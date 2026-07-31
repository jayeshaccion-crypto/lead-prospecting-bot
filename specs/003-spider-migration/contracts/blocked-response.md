# Contract: Blocked-Response Detection (FR-004, FR-005)

**Purpose**: Define the blocked-response hook signatures and behavior.

## Hook: `is_blocked`

```python
async def is_blocked(self, response) -> bool:
```

**Classifier**:

| Condition | Result |
|-----------|--------|
| `response.status` in `{401, 403, 407, 429, 444, 500, 502, 503, 504}` | `True` (rate-limited / WAF block / transient server error) |
| `response.status == 200` AND `body_size < 500` bytes (empty bodies included) | `True` (empty page — likely block page) |
| Everything else | `False` |

**Body size heuristic**:
- `body` sourced from `response.body` (bytes)
- Size computed as `len(body)` for bytes, `len(str(body).encode("utf-8"))` for non-bytes
- Empty bodies (`body_size == 0`) count as blocked under the 200 rule — a blank page is a block-page signature, not a valid lead listing.

> **Note**: FR-004 mandates the `429` + `200`/`<500B` classifier. The implementation
> restores the pre-migration `BLOCKED_STATUS_CODES` superset
> (`{401, 403, 407, 429, 444, 500, 502, 503, 504}`, `src/scraper/spider.py`) so
> Cloudflare/WAF challenges (403) and transient server errors (5xx) are also
> retried up to `max_blocked_retries` instead of silently parsing a block page.

## Threshold Calibration (500B)

The 500-byte threshold is inherited from the pre-migration `is_blocked()` logic
and has served without issue. Calibration data:

| Site | Known smallest response | Verdict |
|------|------------------------|---------|
| justdial | 39-byte block stub (status 200) | SAFE — well under 500B, correctly blocked |
| indiamart | Legitimate listing HTML, several KB+ | SAFE — real listings exceed 500B |
| tradeindia | Legitimate catalog HTML, several KB+ | SAFE — real catalogs exceed 500B |

**Known gap**: No historical log files are retained on disk to empirically
verify the smallest-known-good response per site. If a site ever returns a
legitimate sub-500B page (e.g., a "no results" page), it will be misclassified
as blocked and retried. Mitigation: log body_size on every block (already done
in `retry_blocked_request`), enabling threshold re-calibration from logs if
false-positive blocks are observed.

## Hook: `retry_blocked_request`

```python
async def retry_blocked_request(self, request, response) -> Request:
```

**Behavior**:
1. Rotate proxy: `proxy = _get_next_proxy()`
2. If proxy available: `request._session_kwargs["proxy"] = proxy`
3. If no proxy: `request._session_kwargs.pop("proxy", None)`
4. Log block event at WARNING level with sid and proxy host
5. Return modified request for re-queue

**Error paths**:
- If no proxy available and sid requires one (`justdial_session`, `indiamart_session`): continue without proxy (block likely repeats, exhaustion handled by `max_blocked_retries`)

## Max Retries

Configured via class attribute:

```python
max_blocked_retries = 3
```

Scrapling's `CrawlerEngine` reads this and stops retrying after 3 consecutive blocks for the same request. The request is skipped and logged but does not abort the crawl.

## JustDial Stats Tracking

Inside `retry_blocked_request()`, when `sid == "justdial_session"`:

```python
self._jd_stats["blocked_ips"].add(log_proxy)
if body_size < 500:
    self._jd_stats["blocked"] += 1
```
