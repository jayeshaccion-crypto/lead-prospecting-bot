# Quickstart: Spider Migration — Crawl Orchestration

**Date**: 2026-07-30 | **Context**: Phase 1 validation guide

## Prerequisites

- Python 3.14+ with `pip install -e "."`
- Neo4j driver: `pip install neo4j==5.20.0` (if running full pipeline)
- Environment variables for proxy: `WEBSHARE_PROXY_URL`, `WEBSHARE_PROXY_LIST`, or `WEBSHARE_API_KEY`

## Validation Scenarios

### 1. Session Routing (FR-002)

```bash
# Run crawl targeting all three directories
python -c "from src.scraper.engine import scrape_all_targets; records, errors = scrape_all_targets()"
```

**Expected**: No `TypeError` about unexpected kwargs. JustDial/IndiaMart requests use stealth sessions (proxy, Cloudflare-solving). TradeIndia requests use plain session. All three sites produce records.

**Failure mode**: If tradeindia receives browser-only kwargs, a `TypeError: unexpected keyword argument 'proxy'` or similar appears.

### 2. Blocked-Response Detection (FR-004, FR-005)

```bash
# Run tests
pytest tests/test_spider.py -v -k blocked
```

**Expected**: Tests verify that HTTP 429 and 200-with-body<500B are classified as blocked, and that retry count reaches 3 before logging failure.

### 3. Per-Domain Throttling (FR-006)

```bash
# Run crawl with debug logging
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()" 2>&1 | grep -i "delay\|throttle"
```

**Expected**: Logged timestamps between requests show 8-20s gaps for IndiaMart, 5-10s for JustDial, no added delay for TradeIndia.

### 4. Checkpoint Resume (FR-008)

```bash
# Start crawl, kill mid-way (Ctrl+C), restart
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()"
# ^C after ~30 seconds
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()"
```

**Expected**: Second run resumes from checkpoint (logged "Resuming spider from checkpoint"). Total fetched records equal a single uninterrupted run.

### 5. Global Concurrency (FR-010)

```bash
python -c "from src.scraper.spider import LeadSpider; print(LeadSpider.concurrent_requests)"
```

**Expected**: Prints `2`.

### 6. No Regression

```bash
pytest tests/ -q --tb=short
```

**Expected**: 352 passed (same count as before migration).

### 7. Session Kwargs Isolation (FR-003)

```bash
python -c "
from src.scraper.spider import _SESSION_KWARG_FACTORIES
# Verify stealth factory returns proxy/wait/wait_selector for justdial
kw = _SESSION_KWARG_FACTORIES['justdial_session']({'page_delay': 2.0, 'timeout': 90000}, 'http://proxy:8080')
assert 'proxy' in kw, 'Stealth factory must include proxy'
assert 'wait' in kw, 'Stealth factory must include wait'
# Verify plain factory returns no browser-only kwargs for tradeindia
kw2 = _SESSION_KWARG_FACTORIES['tradeindia_session']({'timeout': 90000}, None)
assert 'proxy' not in kw2, 'Plain factory must NOT include proxy'
assert 'wait' not in kw2, 'Plain factory must NOT include wait'
print('Session kwargs isolation: PASS')
"
```

**Expected**: `Session kwargs isolation: PASS`
