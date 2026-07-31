---

description: "Task list for Spider Migration — Crawl Orchestration"
---

# Tasks: Spider Migration — Crawl Orchestration

**Input**: Design documents from `specs/003-spider-migration/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (all complete)

**Organization**: Six sequential tasks, each independently verifiable before the next begins. Foundation-first: skeleton → session factories → throttling → blocked detection → checkpointing → parse migration.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other [P] tasks
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Task Dependency Graph

```text
T001 ──→ T002 ──→ T003 ──→ T004 ──→ T005 ──→ T006
(foundation)  (kw isolation)  (throttle)  (block-detect)  (checkpoint)  (parse migration)
```

Every task MUST pass its verification gate before the next task begins. No parallelism across tasks — they touch the same file (`spider.py`) in sequence.

---

## Phase 1: T001 — Spider Subclass Skeleton with start_requests()

**Goal**: Define the `LeadSpider` subclass skeleton with `start_requests()` that generates `Request` objects tagged with the correct `sid` per site. No session logic, no parse logic — just prove URL generation and sid tagging works.

**User Stories**: US1 (foundation)

**Files touched**: `src/scraper/spider.py`, `src/scraper/engine.py`

### Implementation Tasks

- [X] T001 Define `LeadSpider(Spider)` class with `name = "lead_spider"` in `src/scraper/spider.py`
- [X] T002 Set class attributes `concurrent_requests = 2`, `max_blocked_retries = 3`, `download_delay = 0.0`, `autothrottle_enabled = False` in `LeadSpider`
- [X] T003 Define `__init__(self, targets_config)` storing config, categories, cities, ICP lists, `DomainRequestCounter` — copy constructor body from existing spider.py:123-141
- [X] T004 Call `super().__init__(crawldir=".scrapling_checkpoints")` at end of `__init__`
- [X] T005 Define `configure_sessions(self, manager)` with placeholder — add bare `FetcherSession()` for each of the three sids (no stealth kwargs yet, just prove sid registration works)
- [X] T006 Implement `start_requests(self)` generating `Request` objects per site/category/city/page with correct `sid` per site — use `SID_BY_NAME` lookup, `_build_source_url()`, `_build_page_url()` from `targets.py`
- [X] T007 Include `_site_label()`, `_build_source_url()`, `_jd_stats`, `_req_counter`, `_jd_mode` logic from existing spider.py:157-309 — copy verbatim, strip only session-kwargs construction
- [X] T008 Implement `parse(self, response)` as minimal stub — log `"Parsing {response.url}"` and return `None` (no extraction yet)
- [X] T009 Implement `on_close(self)` as stub — log `"Spider closed"`
- [X] T010 Update `scrape_all_targets()` in `src/scraper/engine.py` to instantiate `LeadSpider(targets_config)` and call `spider.start()`

**Verification gate** (run before T002 begins):

```bash
python -c "
from src.scraper.spider import LeadSpider, SID_BY_NAME
s = LeadSpider([{'name': 'justdial', 'enabled': True, 'parser': 'parse_justdial', 'pages': 1, 'max_requests_per_day': 10}])
# Iterate start_requests manually (async context)
import anyio
async def check():
    reqs = []
    async for req in s.start_requests():
        reqs.append((req.url, req.sid))
    for url, sid in reqs:
        print(f'URL={url[:80]} SID={sid}')
        assert sid == 'justdial_session', f'Expected justdial_session, got {sid}'
    print(f'Generated {len(reqs)} requests — all sid=justdial_session')
    # Verify no session kwargs leaked (no proxy, no wait — just proving Request objects work)
    kwarg_keys = list(reqs[0]._session_kwargs.keys()) if reqs[0]._session_kwargs else []
    assert 'proxy' not in kwarg_keys, 'No proxy kwargs in skeleton'
    print('Skeleton verifies: URL generation + sid tagging works, no session kwargs leaked')
anyio.run(check)
"
```

**Expected output**: `Generated N requests — all sid=justdial_session` + `Skeleton verifies: URL generation + sid tagging works, no session kwargs leaked`

---

## Phase 2: T002 — Session-Factory Functions (Kwargs Isolation)

**Goal**: Implement the `_SESSION_KWARG_FACTORIES` dict-of-factories pattern. One factory per sid. Stealth factories return proxy/wait/wait_selector; plain factory returns only `timeout`. Structural guarantee — no shared dict, no if/elif, no post-hoc filtering.

**User Stories**: US1

**Files touched**: `src/scraper/spider.py`

**Reference**: `contracts/session-kwargs-factory.md`

### Implementation Tasks

- [X] T011 Define `SID_JUSTDIAL`, `SID_INDIAMART`, `SID_TRADEINDIA` constants in `src/scraper/spider.py` (move from existing spider.py:37-39 if not already present)
- [X] T012 Implement `_build_stealth_kwargs(fetch_kwargs: dict, proxy: str | None) -> dict` — returns `timeout`, `proxy` (required), `wait`, `wait_selector` per contract
- [X] T013 Implement `_build_plain_kwargs(fetch_kwargs: dict, proxy: str | None) -> dict` — returns only `timeout`, guarantees no browser-only kwargs
- [X] T014 Define `_SESSION_KWARG_FACTORIES: dict[str, Callable]` mapping {{`SID_JUSTDIAL:` `_build_stealth_kwargs`, `SID_INDIAMART:` `_build_stealth_kwargs`, `SID_TRADEINDIA:` `_build_plain_kwargs`}}
- [X] T015 Implement `_make_session_kwargs(sid: str, fetch_kwargs: dict, proxy: str | None) -> dict` — single entry point: `factory = _SESSION_KWARG_FACTORIES[sid]` (KeyError for unknown sid)
- [X] T016 Wire `_make_session_kwargs()` into `start_requests()` — replace placeholder kwargs construction with factory call
- [X] T017 Now fill in `configure_sessions()` fully: `FetcherSession()` for TI, `AsyncStealthySession(capture_xhr=r".*", **stealth_kw)` for JD, `AsyncStealthySession(**stealth_kw)` for IM, with proxy/geoip/Cloudflare kwargs

**Verification gate** (run before T003 begins):

```bash
python -c "
from src.scraper.spider import _SESSION_KWARG_FACTORIES, _make_session_kwargs

# Test stealth factory
kw = _make_session_kwargs('justdial_session', {'page_delay': 2.0, 'timeout': 90000, 'wait_selector': '.result'}, 'http://u:p@1.2.3.4:8080')
assert 'proxy' in kw and kw['proxy'] == 'http://u:p@1.2.3.4:8080'
assert 'wait' in kw and kw['wait'] >= 2000
assert 'wait_selector' in kw
assert 'timeout' in kw
print('Stealth factory: PASS')

# Test plain factory
kw2 = _make_session_kwargs('tradeindia_session', {'timeout': 90000}, None)
assert 'proxy' not in kw2
assert 'wait' not in kw2
assert 'wait_selector' not in kw2
assert kw2 == {'timeout': 90000}
print('Plain factory: PASS')

# Test unknown sid raises KeyError
try:
    _make_session_kwargs('unknown_session', {}, None)
    assert False, 'Should have raised KeyError'
except KeyError:
    print('Unknown sid KeyError: PASS')

# Test siloed dict (no cross-contamination)
from src.scraper.spider import SID_JUSTDIAL, SID_TRADEINDIA
assert SID_JUSTDIAL in _SESSION_KWARG_FACTORIES
assert SID_TRADEINDIA in _SESSION_KWARG_FACTORIES
assert _SESSION_KWARG_FACTORIES[SID_JUSTDIAL] != _SESSION_KWARG_FACTORIES[SID_TRADEINDIA]
print('Dict isolation: PASS')
"
```

**Expected output**: `Stealth factory: PASS` / `Plain factory: PASS` / `Unknown sid KeyError: PASS` / `Dict isolation: PASS`

---

## Phase 3: T003 — Per-Domain Throttling & Global Concurrency

**Goal**: Wire per-domain random delays and global concurrency limit. Global concurrency via `concurrent_requests = 2` class attribute. Per-domain delays via `DOMAIN_DELAYS` dict + `anyio.sleep(random.uniform(...))` in `start_requests()`.

**User Stories**: US3

**Files touched**: `src/scraper/spider.py`

**Reference**: `contracts/scheduler-config.md`

### Implementation Tasks

- [X] T018 Define `DOMAIN_DELAYS: dict[str, tuple[float, float]]` with entries for all three sids (JD 5-10s, IM 8-20s, TI 0-0s)
- [X] T019 Add `random.uniform(*DOMAIN_DELAYS[sid])` delay in `start_requests()` between page yields for the same site — use `anyio.sleep()` so it integrates with checkpointing
- [X] T020 Verify `concurrent_requests = 2` is already set from T001 (if not, add it)
- [X] T021 Remove any hand-rolled `time.sleep()` or `anyio.sleep()` calls in `start_requests()` that duplicate the new delay logic (keep only the random-range delay via `DOMAIN_DELAYS`)

**Verification gate** (run before T004 begins):

```bash
# Unit test: verify DOMAIN_DELAYS exists and has correct ranges
python -c "
from src.scraper.spider import DOMAIN_DELAYS, SID_JUSTDIAL, SID_INDIAMART, SID_TRADEINDIA
assert DOMAIN_DELAYS[SID_JUSTDIAL] == (5.0, 10.0)
assert DOMAIN_DELAYS[SID_INDIAMART] == (8.0, 20.0)
assert DOMAIN_DELAYS[SID_TRADEINDIA] == (0.0, 0.0)
print('DOMAIN_DELAYS: PASS')
from src.scraper.spider import LeadSpider
assert LeadSpider.concurrent_requests == 2
print('Global concurrency 2: PASS')
"
```

**Expected output**: `DOMAIN_DELAYS: PASS` / `Global concurrency 2: PASS`

---

## Phase 4: T004 — Blocked-Response Detection & Retry

**Goal**: Implement `is_blocked()` and `retry_blocked_request()` hooks. Classify 429 or 200-with-body<500B as blocked. Rotate proxy on retry. Register via `max_blocked_retries = 3`.

**User Stories**: US2

**Files touched**: `src/scraper/spider.py`

**Reference**: `contracts/blocked-response.md`

### Implementation Tasks

- [X] T022 Override `async def is_blocked(self, response) -> bool` in `LeadSpider` — return `True` if `response.status == 429`, or if `response.status == 200` and `0 < body_size < 500`
- [X] T023 Override `async def retry_blocked_request(self, request, response) -> Request` — rotate proxy via `_get_next_proxy()`, log block at WARNING with sid and proxy host
- [X] T024 Add JustDial stats tracking inside `retry_blocked_request()` — `.add(log_proxy)` to `_jd_stats["blocked_ips"]`, increment `_jd_stats["blocked"]` if body < 500B
- [X] T025 Verify `max_blocked_retries = 3` is set (should be from T001)

**Verification gate** (run before T005 begins):

```bash
# Unit test: is_blocked() classification
python -c "
import anyio
from src.scraper.spider import LeadSpider
from unittest.mock import AsyncMock, MagicMock

s = LeadSpider([])

async def test():
    # 429 is blocked
    r = MagicMock(status=429)
    r.body = b'Rate limited'
    assert await s.is_blocked(r) == True, '429 should be blocked'

    # 200 with 100B body is blocked
    r = MagicMock(status=200)
    r.body = b'x' * 100
    assert await s.is_blocked(r) == True, '200 with <500B should be blocked'

    # 200 with 5000B body is not blocked
    r = MagicMock(status=200)
    r.body = b'x' * 5000
    assert await s.is_blocked(r) == False, '200 with >=500B should not be blocked'

    # 404 is not blocked
    r = MagicMock(status=404)
    r.body = b'Not found'
    assert await s.is_blocked(r) == False, '404 should not be blocked'

    print('is_blocked: PASS')

anyio.run(test)
"
```

**Expected output**: `is_blocked: PASS`

---

## Phase 5: T005 — Checkpoint Save/Resume

**Goal**: Ensure checkpointing works end-to-end. The `crawldir` is already set in `__init__` (T001). This task verifies that Scrapling's `CrawlerEngine` writes checkpoints on pause and resumes correctly.

**User Stories**: US4

**Files touched**: `src/scraper/spider.py` (minor), `src/scraper/engine.py` (minor)

**Reference**: `plan.md` §5, `contracts/scheduler-config.md`

### Implementation Tasks

- [X] T026 Verify `super().__init__(crawldir=".scrapling_checkpoints")` is present in `LeadSpider.__init__()` (should be from T001) — if missing, add it
- [X] T027 Add `logger.info("Resuming spider from checkpoint")` in `on_start(self, resuming: bool)` override — called by Scrapling when resuming
- [X] T028 Add `logger.info("Checkpoint saved")` in `on_close(self)` override if checkpoint was active
- [X] T029 Ensure `.scrapling_checkpoints/` is in `.gitignore` (should be from prior T003) — if missing, add pattern

**Verification gate** (run before T006 begins):

```bash
# Verify crawldir is set
python -c "
from src.scraper.spider import LeadSpider
s = LeadSpider([])
# craname is stored as crawldir on base Spider
crawldir = str(s.crawldir) if s.crawldir else None
assert crawldir is not None, 'crawldir must be set'
assert 'scrapling_checkpoints' in crawldir
print(f'crawldir={crawldir} — PASS')

# Verify .gitignore contains scrapling_checkpoints
import pathlib
gi = pathlib.Path('.gitignore').read_text().splitlines()
assert any('scrapling_checkpoints' in line for line in gi), '.gitignore must contain scrapling_checkpoints'
print('.gitignore scrapling_checkpoints: PASS')
"
```

**Expected output**: `crawldir=.scrapling_checkpoints — PASS` / `.gitignore scrapling_checkpoints: PASS`

---

## Phase 6: T006 — Parse Logic Migration

**Goal**: Migrate each site's existing parse logic (CSS selectors, extraction, detail enrichment, fill rates, JD stats, summary logging) from the pre-migration code into the new `parse()` callback, verifying identical output structure.

**User Stories**: US1, US2, US3, US4 (all)

**Files touched**: `src/scraper/spider.py`

### Implementation Tasks

- [X] T030 Implement `parse(self, response)` with full parser dispatch — lookup `PARSER_REGISTRY[meta["parser"]]`, call parser, extract records
- [X] T031 Add record tagging with `RawRecord` (company_name, website, email, phone, address, industry_code, source_url) — append to `self.all_records`
- [X] T032 Add detail URL extraction via `_extract_detail_urls()` — store in `self._enrich_data` for post-parse enrichment
- [X] T033 Add fill rate tracking in `parse()` — increment `_fill_rates[site]["total"/"phone"/"email"/"website"]`
- [X] T034 Add JustDial `_jd_stats["succeeded"]` increment in `parse()` when `site_name.lower() == "justdial"`
- [X] T035 `yield` each record as dict from `parse()` (item for CrawlerEngine to collect)
- [X] T036 Implement `on_close(self)` fully — copy from existing spider.py:428-513: TradeIndia enrichment, IndiaMART httpx enrichment, fill rate recompute, byte totals, JD summary, mode report
- [X] T037 Implement `on_start(self, resuming)` — log startup mode, JD mode, config summary

**Verification gate**:

```bash
# Run full test suite — all 352 existing tests must pass
pytest tests/ -q --tb=short

# Basic crawl with debug output
python -c "
from src.scraper.spider import LeadSpider
s = LeadSpider([{'name': 'justdial', 'enabled': False, 'parser': 'parse_justdial', 'pages': 1, 'max_requests_per_day': 10}])
# The crawl completes without errors
print('Crawl initialization: PASS')
" 2>&1
```

**Expected output**: `352 passed` (pytest) + `Crawl initialization: PASS`

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verify everything works end-to-end, no regressions, quickstart scenarios pass.

- [X] T038 Run `pytest tests/ -q --tb=short` — confirm 352 passed (same as before migration)
- [X] T039 Run `python -c "from src.scraper.engine import scrape_all_targets; scrape_all_targets()"` with all three targets enabled — verify no TypeError, no silent failures
- [X] T040 Verify session kwargs isolation with `python specs/003-spider-migration/quickstart.md` validation scenario 7

---

## Dependencies & Execution Order

### Phase Dependencies

- **T001 (Skeleton)**: No dependencies — starting point
- **T002 (Session Factories)**: Depends on T001 — needs `start_requests()` and `configure_sessions()`
- **T003 (Throttling)**: Depends on T002 — delay logic lives inside `start_requests()` alongside kwargs
- **T004 (Block Detection)**: Depends on T003 — retry logic uses session kwargs from T002 + delay timing from T003
- **T005 (Checkpoint)**: Depends on T004 — checkpoint resume uses retry hooks; minimal, can be done in parallel with T006 prep
- **T006 (Parse Migration)**: Depends on T001-T005 — full pipeline needs skeleton, factories, throttling, block detection, checkpoint
- **T007 (Polish)**: Depends on all prior phases

### Sequential Requirement

All 6 main tasks are strictly sequential — each touches `src/scraper/spider.py` and must be verified independently before the next begins.

### Parallel Opportunities

None within this feature — single file (`spider.py`), single developer scope.

---

## Implementation Strategy

### MVP: T001 + T002

The minimum that demonstrates value: a Spider subclass that generates correct `Request` objects with correct `sid` and never passes browser-only kwargs to `FetcherSession`. This alone proves the core architectural change works and the prior bug is structurally eliminated.

### Incremental Delivery

1. **T001 complete**: Skeleton works — can print Request objects with correct sids
2. **T002 complete**: Kwargs isolation proven — structurally impossible for stealth kwargs to reach plain sessions
3. **T003 complete**: Throttling active — no hand-rolled sleep calls
4. **T004 complete**: Block detection — 429 and empty pages retried
5. **T005 complete**: Checkpointing — killed runs resume
6. **T006 complete**: Full migration — identical output to pre-migration code
7. **T007 complete**: All 352 tests pass, quickstart scenarios valid
