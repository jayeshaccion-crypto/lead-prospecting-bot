# Quickstart: JustDial Three-Mode Proxy Routing

**Date**: 2026-07-31 | **Context**: Phase 1 validation guide

## Prerequisites

- Python 3.12+ with `pip install -e "."`
- Environment variables per mode under test:
  - Residential mode: `RESIDENTIAL_PROXY_URL_JUSTDIAL`
  - Datacenter mode: `WEBSHARE_API_KEY` (or `WEBSHARE_PROXY_URL` / `WEBSHARE_PROXY_LIST`)
  - No-proxy mode: neither set
- Existing state file: `data/request_counts.json` (created lazily)

## Validation Scenarios

### 1. Mode Precedence (FR-001)

```bash
# Residential wins when both are set
set RESIDENTIAL_PROXY_URL_JUSTDIAL=http://user:pass@residential.example:3128
set WEBSHARE_API_KEY=test-key
python -c "from src.scraper.spider import LeadSpider; s=LeadSpider([]); print(s._determine_jd_mode())"
```

**Expected**: prints `residential`.

```bash
# Datacenter when only Webshare pool present
set WEBSHARE_API_KEY=test-key
python -c "from src.scraper.spider import LeadSpider; s=LeadSpider([]); print(s._determine_jd_mode())"
```

**Expected**: prints `datacenter`.

```bash
# No-proxy when neither set
python -c "from src.scraper.spider import LeadSpider; s=LeadSpider([]); print(s._determine_jd_mode())"
```

**Expected**: prints `no_proxy`.

### 2. Datacenter Mode — Once-Daily ASN Test (FR-003, FR-004, FR-009)

```bash
# Run 1 (first run of the day)
set WEBSHARE_API_KEY=test-key
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()" 2>&1 | Select-String "JustDial"
```

**Expected**: verdict line `JustDial: X/10 distinct proxy IPs attempted, Y blocked (body<500B), Z succeeded.` and, if `Y==X`, the CONCLUSION line. No JustDial crawl requests (no category/city expansion).

```bash
# Run 2 (same day) — test must NOT repeat
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()" 2>&1 | Select-String "JustDial"
```

**Expected**: no new verdict line; just the mode summary `JustDial mode: datacenter-ASN-test`. Verify `data/request_counts.json` still has `"__jd_asn_test": 1` for today's date.

### 3. Residential Mode — Full Depth (FR-002)

```bash
set RESIDENTIAL_PROXY_URL_JUSTDIAL=http://user:pass@residential.example:3128
set SCRAPE_FULL_PAGES=true
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()" 2>&1 | Select-String "JustDial"
```

**Expected**: JustDial crawled at the same page depth as IndiaMart/TradeIndia; mode summary `JustDial mode: residential`; no ASN verdict line.

### 4. No-Proxy Mode — Skip with Warning (FR-007)

```bash
python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()" 2>&1 | Select-String "Justdial|JustDial"
```

**Expected**: explicit warning naming the missing env var(s) (`RESIDENTIAL_PROXY_URL_JUSTDIAL` and `WEBSHARE_PROXY_URL` / `WEBSHARE_PROXY_LIST` / `WEBSHARE_API_KEY`), `ScrapeError("ProxyNotConfigured")` recorded, mode summary `JustDial mode: no_proxy`, zero JustDial requests.

### 5. Summary Lines (FR-005, FR-006, FR-008)

```bash
pytest tests/test_spider.py -v -k "jd_mode or asn or justdial_summary"
```

**Expected**: tests assert the exact verdict string, the CONCLUSION string (only when `Y==X`), and the three mode summary lines. See [contracts/summary-lines.md](contracts/summary-lines.md).

### 6. Flag Idempotency (FR-009 / SC-003)

```bash
pytest tests/test_spider.py -v -k "asn"
```

**Expected**: tests run the mode twice on the same date and assert the probe runs once total (persisted `__jd_asn_test` flag honored across separate spider instances).

## Notes

- No live-network crawl is required for CI validation — tests use monkeypatched env vars and stubbed probe responses (consistent with the existing harness patch approach).
- Live probes only in datacenter mode and bounded to ≤ 10 single requests per day.
- Reference contracts: [jd-mode.md](contracts/jd-mode.md), [asn-test.md](contracts/asn-test.md), [summary-lines.md](contracts/summary-lines.md); entity details in [data-model.md](data-model.md).
