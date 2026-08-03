"""Unit tests for LeadSpider: kwarg factories, throttling, block detection, retry, and start_requests routing."""

import anyio
import inspect
import json
import logging
import pytest
from unittest.mock import MagicMock

from scrapling.spiders.request import Request

from src.scraper import engine as scraper_engine
from src.scraper import spider as spider_mod
from src.scraper.spider import (
    ASN_PROBE_MAX,
    ASN_CONCLUSION,
    BLOCKED_STATUS_CODES,
    DOMAIN_DELAYS,
    SID_INDIAMART,
    SID_JUSTDIAL,
    SID_TRADEINDIA,
    LeadSpider,
    _SESSION_KWARG_FACTORIES,
    _make_session_kwargs,
)
from src.scraper.targets import RawRecord


@pytest.fixture
def small_config(monkeypatch):
    """Patches config loading so start_requests iterates 1 category x 1 city."""
    full = {
        "categories": [{
            "slug": "it-services",
            "labels": {
                "justdial": "IT-Services",
                "indiamart": "software-development-services",
                "tradeindia": "IT-Services",
            },
        }],
        "cities": [{
            "slug": "delhi",
            "labels": {"justdial": "Delhi", "indiamart": "new-delhi", "tradeindia": "new-delhi"},
            "tradeindia_code": "228067",
        }],
        "url_templates": {
            "justdial": "https://www.justdial.com/{city}/{category}/nct-10278073",
            "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
            "tradeindia": "https://www.tradeindia.com/{city}/{category}-city-{code}.html",
        },
        "icp_categories": [],
        "icp_cities": [],
    }
    monkeypatch.setattr(spider_mod, "load_full_config", lambda: full)
    monkeypatch.setattr(spider_mod, "get_icp_categories", lambda cfg: [])
    monkeypatch.setattr(spider_mod, "get_icp_cities", lambda cfg: [])
    return full


@pytest.fixture
def make_spider(monkeypatch, small_config):
    """Build a LeadSpider with browser/network side effects neutralized."""
    monkeypatch.setattr("scrapling.fetchers.FetcherSession", MagicMock)
    monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", MagicMock)
    monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: True)
    monkeypatch.setattr(spider_mod.DomainRequestCounter, "allowed", lambda self, d, c: True)

    def _make(config):
        return LeadSpider(config)

    return _make


@pytest.fixture
def proxy_pool(monkeypatch):
    monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://user:pass@1.2.3.4:8080"])
    monkeypatch.setattr(scraper_engine, "_PROXY_INDEX", 0)


@pytest.fixture
def isolated_counter(tmp_path, monkeypatch):
    """Redirect DomainRequestCounter persistence to a temp file (keeps data/ clean)."""
    target = tmp_path / "request_counts.json"

    def _save(self):
        try:
            target.write_text(json.dumps({"date": self._date, "counts": self._counts}))
        except Exception:
            pass

    def _load(self):
        self._date = spider_mod.time.strftime("%Y-%m-%d")
        try:
            if target.exists():
                data = json.loads(target.read_text())
                if data.get("date") == self._date:
                    self._counts = data.get("counts", {})
        except Exception:
            self._counts = {}

    monkeypatch.setattr(spider_mod.DomainRequestCounter, "_save", _save)
    monkeypatch.setattr(spider_mod.DomainRequestCounter, "_load", _load)
    return target


class _StubSessionManager:
    """SessionManager stand-in returning canned (status, body) responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def fetch(self, request):
        self.calls.append(request)
        status, body = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return MagicMock(status=status, body=body, headers={}, url=request.url)


class _FakeRotator:
    def __init__(self, proxies):
        self._proxies = list(proxies)
        self._i = 0

    def get_proxy(self):
        proxy = self._proxies[self._i % len(self._proxies)]
        self._i += 1
        return proxy


def _collect(spider):
    async def run():
        reqs = []
        async for req in spider.start_requests():
            reqs.append(req)
        return reqs

    return anyio.run(run)


class TestProxyKey:
    """Redaction/dedup key for proxy URLs (constitution III)."""

    @pytest.mark.parametrize("proxy,want", [
        ("http://user:pass@host:8080", "host:8080"),
        ("http://host:8080", "host:8080"),
        ("host:8080", "host:8080"),
        ("user:pass@host:8080", "host:8080"),
        ("http://user:pass@[::1]:8080", "[::1]:8080"),
        ("", ""),
        ("   ", ""),
        (None, ""),
        ({"server": "http://h:80", "username": "u"}, ""),
    ])
    def test_credential_free_key(self, proxy, want):
        assert spider_mod._proxy_key(proxy) == want


class TestKwargFactories:
    def test_stealth_factory(self):
        kw = _make_session_kwargs(
            SID_JUSTDIAL,
            {"page_delay": 2.0, "timeout": 90000, "wait_selector": ".card"},
            "http://user:pass@1.2.3.4:8080",
        )
        assert kw["proxy"] == "http://user:pass@1.2.3.4:8080"
        assert kw["wait"] >= 2000
        assert kw["wait_selector"] == ".card"
        assert kw["wait_selector_state"] == "visible"
        assert kw["timeout"] == 90000

    def test_stealth_factory_requires_proxy(self):
        with pytest.raises(ValueError):
            _make_session_kwargs(SID_JUSTDIAL, {"timeout": 90000}, None)

    def test_plain_factory_only_timeout(self):
        kw = _make_session_kwargs(SID_TRADEINDIA, {"timeout": 90000}, "http://user:pass@1.2.3.4:8080")
        assert kw == {"timeout": 90000}
        assert "proxy" not in kw
        assert "wait" not in kw
        assert "wait_selector" not in kw

    def test_unknown_sid_raises_keyerror(self):
        with pytest.raises(KeyError):
            _make_session_kwargs("unknown_session", {}, None)

    def test_factory_dict_isolation(self):
        assert set(_SESSION_KWARG_FACTORIES) == {SID_JUSTDIAL, SID_INDIAMART, SID_TRADEINDIA}
        assert _SESSION_KWARG_FACTORIES[SID_JUSTDIAL] == _SESSION_KWARG_FACTORIES[SID_INDIAMART]
        assert _SESSION_KWARG_FACTORIES[SID_JUSTDIAL] != _SESSION_KWARG_FACTORIES[SID_TRADEINDIA]

    def test_no_shared_dict_filtering(self):
        """FR-003 invariant: entry point is a dict lookup, never an if/elif chain."""
        src = inspect.getsource(spider_mod._make_session_kwargs)
        assert "_SESSION_KWARG_FACTORIES[sid]" in src
        assert "if sid" not in src
        assert "if sid == " not in src


class TestConfigureSessions:
    """FR-002/SC-001: correct session class and registration per sid."""

    def test_registers_three_sessions(self, make_spider):
        s = make_spider([])
        mgr = s._session_manager
        assert set(mgr.session_ids) == {SID_JUSTDIAL, SID_INDIAMART, SID_TRADEINDIA}
        assert mgr.default_session_id == SID_TRADEINDIA
        assert SID_TRADEINDIA not in mgr._lazy_sessions
        assert SID_JUSTDIAL in mgr._lazy_sessions
        assert SID_INDIAMART in mgr._lazy_sessions

    def test_plain_session_constructed_once_for_tradeindia(self, make_spider, monkeypatch):
        import scrapling.fetchers

        created = []

        def fake_fetcher(*args, **kwargs):
            obj = MagicMock()
            created.append(obj)
            return obj

        monkeypatch.setattr(scrapling.fetchers, "FetcherSession", fake_fetcher)
        s = make_spider([])
        assert len(created) == 1
        assert s._session_manager.get(SID_TRADEINDIA) is created[0]

    def test_stealth_sessions_constructed_with_browser_kwargs(self, make_spider, monkeypatch):
        import scrapling.fetchers

        calls = []

        def fake_stealth(**kwargs):
            calls.append(kwargs)
            return MagicMock()

        monkeypatch.setattr(scrapling.fetchers, "AsyncStealthySession", fake_stealth)
        s = make_spider([])
        assert len(calls) == 2

        # JustDial gets XHR capture; IndiaMART does not. Both get shared stealth kwargs.
        xhr = [kw for kw in calls if kw.get("capture_xhr") == r".*"]
        assert len(xhr) == 1
        assert xhr[0]["solve_cloudflare"] is True
        non_xhr = [kw for kw in calls if "capture_xhr" not in kw]
        assert len(non_xhr) == 1
        assert non_xhr[0]["headless"] is True
        assert non_xhr[0]["blocked_domains"] == spider_mod.BLOCKED_DOMAINS


class TestSessionRouting:
    """US1/FR-002: requests reach the correct session carrying only session-valid kwargs."""

    def _fake_manager(self):
        from scrapling.spiders.session import SessionManager

        received = {}

        class FakeSession:
            _is_alive = True

            def __init__(self, name):
                self.name = name

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def fetch(self, url, **kwargs):
                received[self.name] = kwargs
                return MagicMock(status=200, body=b"x" * 600, headers={}, url=url)

        manager = SessionManager()
        manager.add(SID_TRADEINDIA, FakeSession("ti"))
        manager.add(SID_JUSTDIAL, FakeSession("jd"), lazy=True)
        manager.add(SID_INDIAMART, FakeSession("im"), lazy=True)
        return manager, received

    def test_tradeindia_never_receives_browser_kwargs(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://u:p@residential.example:3128")
        s = make_spider([TestStartRequests.JD, TestStartRequests.TI])
        manager, received = self._fake_manager()
        reqs = _collect(s)

        async def run():
            for req in reqs:
                await manager.fetch(req)

        anyio.run(run)
        assert received["ti"] == {"timeout": 90000}
        assert "proxy" not in received["ti"]
        assert "wait" not in received["ti"]
        assert "wait_selector" not in received["ti"]

    def test_justdial_receives_stealth_kwargs(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://u:p@residential.example:3128")
        s = make_spider([TestStartRequests.JD])
        manager, received = self._fake_manager()
        reqs = _collect(s)

        async def run():
            for req in reqs:
                await manager.fetch(req)

        anyio.run(run)
        jd_kw = received["jd"]
        assert jd_kw["proxy"] == "http://u:p@residential.example:3128"
        assert jd_kw["wait"] >= 2000
        assert jd_kw["timeout"] == 90000

    def test_unknown_sid_raises_at_fetch(self, make_spider):
        manager, _ = self._fake_manager()
        req = Request("https://x.com", sid="unknown_session")
        with pytest.raises(KeyError):
            anyio.run(manager.fetch, req)


class TestThrottlingConfig:
    def test_domain_delays(self):
        assert DOMAIN_DELAYS[SID_JUSTDIAL] == (5.0, 10.0)
        assert DOMAIN_DELAYS[SID_INDIAMART] == (8.0, 20.0)
        assert DOMAIN_DELAYS[SID_TRADEINDIA] == (0.0, 0.0)

    def test_concurrency_attributes(self):
        assert LeadSpider.concurrent_requests == 2
        assert LeadSpider.concurrent_requests_per_domain == 1
        assert LeadSpider.max_blocked_retries == 3
        assert LeadSpider.download_delays is DOMAIN_DELAYS

    def test_engine_applies_per_domain_delay(self, make_spider):
        from scrapling.spiders.engine import CrawlerEngine

        s = make_spider([])
        engine = CrawlerEngine(s, s._session_manager, crawldir=None)

        jd = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL)
        delay_jd = anyio.run(engine._get_domain_delay, jd)
        assert 5.0 <= delay_jd <= 10.0

        ti = Request("https://www.tradeindia.com/x", sid=SID_TRADEINDIA)
        delay_ti = anyio.run(engine._get_domain_delay, ti)
        assert delay_ti == 0.0

        im = Request("https://dir.indiamart.com/x", sid=SID_INDIAMART)
        delay_im = anyio.run(engine._get_domain_delay, im)
        assert 8.0 <= delay_im <= 20.0

    def test_delay_is_random_within_range(self, make_spider):
        from scrapling.spiders.engine import CrawlerEngine

        s = make_spider([])
        engine = CrawlerEngine(s, s._session_manager, crawldir=None)
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL)
        drawn = {anyio.run(engine._get_domain_delay, req) for _ in range(100)}
        assert drawn
        assert all(5.0 <= d <= 10.0 for d in drawn)
        assert len(drawn) > 1  # random per request, not a constant

    def test_unknown_domain_falls_back_to_safe_default(self, make_spider):
        """Spec edge case: a domain/sid with no delay rule gets no artificial delay."""
        from scrapling.spiders.engine import CrawlerEngine

        s = make_spider([])
        engine = CrawlerEngine(s, s._session_manager, crawldir=None)
        req = Request("https://unknown.example/x", sid="mystery_session")
        assert anyio.run(engine._get_domain_delay, req) == s.download_delay == 0.0


class TestEngineThrottling:
    """FR-007/SC-003: the engine (not start_requests) sleeps the drawn per-domain delay."""

    @staticmethod
    def _stub_session(status=200, body=b"x" * 5000):
        class StubSession:
            default_session_id = "default"

            async def fetch(self, request):
                return MagicMock(status=status, body=body, headers={}, url=request.url)

        return StubSession()

    def test_engine_sleeps_justdial_delay(self, make_spider, monkeypatch):
        from scrapling.spiders.engine import CrawlerEngine

        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr("scrapling.spiders.engine.anyio.sleep", fake_sleep)
        s = make_spider([])
        engine = CrawlerEngine(s, self._stub_session(), crawldir=None)
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL)
        anyio.run(engine._process_request, req)
        assert len(sleeps) == 1
        assert 5.0 <= sleeps[0] <= 10.0

    def test_engine_sleeps_indiamart_delay(self, make_spider, monkeypatch):
        from scrapling.spiders.engine import CrawlerEngine

        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr("scrapling.spiders.engine.anyio.sleep", fake_sleep)
        s = make_spider([])
        engine = CrawlerEngine(s, self._stub_session(), crawldir=None)
        req = Request("https://dir.indiamart.com/x", sid=SID_INDIAMART)
        anyio.run(engine._process_request, req)
        assert len(sleeps) == 1
        assert 8.0 <= sleeps[0] <= 20.0

    def test_engine_does_not_sleep_for_tradeindia(self, make_spider, monkeypatch):
        from scrapling.spiders.engine import CrawlerEngine

        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr("scrapling.spiders.engine.anyio.sleep", fake_sleep)
        s = make_spider([])
        engine = CrawlerEngine(s, self._stub_session(), crawldir=None)
        req = Request("https://www.tradeindia.com/x", sid=SID_TRADEINDIA)
        anyio.run(engine._process_request, req)
        assert sleeps == []

    def test_no_handrolled_sleep_in_start_requests(self):
        """FR-007: pacing lives in the scheduler/engine, not in request generation."""
        src = inspect.getsource(spider_mod.LeadSpider.start_requests)
        assert "anyio.sleep" not in src
        assert "time.sleep" not in src


class TestIsBlocked:
    @pytest.mark.parametrize("status,body,expected", [
        (429, b"Rate limited", True),
        (403, b"<html>challenge</html>", True),
        (200, b"x" * 100, True),
        (200, b"", True),
        (200, b"x" * 5000, False),
        (404, b"Not found", False),
    ])
    def test_classification(self, make_spider, status, body, expected):
        s = make_spider([])
        resp = MagicMock(status=status, body=body)
        assert anyio.run(s.is_blocked, resp) is expected

    @pytest.mark.parametrize("status", list(BLOCKED_STATUS_CODES))
    def test_full_status_superset(self, make_spider, status):
        """FR-004 contract: every configured block status is flagged regardless of body."""
        s = make_spider([])
        resp = MagicMock(status=status, body=b"<html>full page</html>" * 200)
        assert anyio.run(s.is_blocked, resp) is True

    @pytest.mark.parametrize("body", [b"x" * 499, "x" * 499])
    def test_499_bytes_is_blocked(self, make_spider, body):
        s = make_spider([])
        assert anyio.run(s.is_blocked, MagicMock(status=200, body=body)) is True

    @pytest.mark.parametrize("body", [b"x" * 500, "x" * 500, b"x" * 501, "x" * 501])
    def test_500_bytes_and_above_not_blocked(self, make_spider, body):
        s = make_spider([])
        assert anyio.run(s.is_blocked, MagicMock(status=200, body=body)) is False

    def test_multibyte_str_body_measured_in_utf8_bytes(self, make_spider):
        """Non-bytes bodies are sized via UTF-8 encoding (contract)."""
        s = make_spider([])
        # 300 two-byte chars -> 600 bytes; under the 500-char count but over 500 bytes.
        assert anyio.run(s.is_blocked, MagicMock(status=200, body="\u00e9" * 300)) is False
        # 100 two-byte chars -> 200 bytes -> blocked.
        assert anyio.run(s.is_blocked, MagicMock(status=200, body="\u00e9" * 100)) is True

    def test_none_body_counts_as_blocked(self, make_spider):
        s = make_spider([])
        assert anyio.run(s.is_blocked, MagicMock(status=200, body=None)) is True


class TestRetryBlockedRequest:
    def test_rotates_proxy_for_justdial(self, make_spider, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        s = make_spider([])
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: "http://user:pass@9.9.9.9:8080")
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL, proxy="http://user:pass@1.2.3.4:8080")
        resp = MagicMock(body=b"x" * 100)

        anyio.run(s.retry_blocked_request, req, resp)

        assert req._session_kwargs["proxy"] == "http://user:pass@9.9.9.9:8080"
        assert "9.9.9.9:8080" in s._jd_stats["blocked_ips"]
        assert s._jd_stats["blocked"] == 1

    def test_residential_keeps_residential_proxy(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        s = make_spider([])
        anyio.run(s.on_start, False)
        assert s._jd_mode == "residential"
        req = Request(
            "https://www.justdial.com/x", sid=SID_JUSTDIAL,
            proxy="http://user:pass@residential.example:3128",
        )
        resp = MagicMock(body=b"x" * 100)

        anyio.run(s.retry_blocked_request, req, resp)

        assert req._session_kwargs["proxy"] == "http://user:pass@residential.example:3128"
        assert "residential.example:3128" in s._jd_stats["blocked_ips"]
        assert s._jd_stats["blocked"] == 1

    def test_no_proxy_injected_for_tradeindia(self, make_spider, monkeypatch):
        s = make_spider([])
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: "http://user:pass@9.9.9.9:8080")
        req = Request("https://www.tradeindia.com/x", sid=SID_TRADEINDIA)
        resp = MagicMock(body=b"x" * 100)

        anyio.run(s.retry_blocked_request, req, resp)

        assert "proxy" not in req._session_kwargs

    def test_no_proxy_available_for_stealth(self, make_spider, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        s = make_spider([])
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: None)
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL, proxy="http://user:pass@1.2.3.4:8080")
        resp = MagicMock(body=b"x" * 100)

        anyio.run(s.retry_blocked_request, req, resp)

        assert "proxy" not in req._session_kwargs

    def test_jd_stats_only_increment_when_body_under_500(self, make_spider, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        s = make_spider([])
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: "http://user:pass@9.9.9.9:8080")
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL)
        resp = MagicMock(body=b"x" * 5000)

        anyio.run(s.retry_blocked_request, req, resp)

        assert s._jd_stats["blocked"] == 0
        assert "9.9.9.9:8080" in s._jd_stats["blocked_ips"]


class TestStartRequests:
    JD = {"name": "justdial", "enabled": True, "parser": "parse_justdial", "pages": 1,
          "max_requests_per_day": 10, "fetch_kwargs": {"timeout": 90000, "page_delay": 2.0}}
    IM = {"name": "indiamart", "enabled": True, "parser": "parse_indiamart", "pages": 1,
          "max_requests_per_day": 10, "fetch_kwargs": {"timeout": 120000, "page_delay": 2.0}}
    TI = {"name": "tradeindia", "enabled": True, "parser": "parse_tradeindia", "pages": 1,
          "max_requests_per_day": 10, "fetch_kwargs": {"timeout": 90000}}

    def test_tradeindia_request_only_timeout_kwargs(self, make_spider):
        s = make_spider([self.TI])
        reqs = _collect(s)
        assert len(reqs) == 1
        assert reqs[0].sid == SID_TRADEINDIA
        assert reqs[0]._session_kwargs == {"timeout": 90000}

    def test_stealth_request_has_proxy_and_wait(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        s = make_spider([self.JD])
        reqs = _collect(s)
        assert len(reqs) == 1
        assert reqs[0].sid == SID_JUSTDIAL
        kw = reqs[0]._session_kwargs
        assert kw["proxy"] == "http://user:pass@residential.example:3128"
        assert kw["wait"] >= 2000
        assert "timeout" in kw

    def test_no_proxy_skips_stealth_sites(self, make_spider, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        s = make_spider([self.JD, self.IM, self.TI])
        reqs = _collect(s)
        sids = [r.sid for r in reqs]
        assert SID_JUSTDIAL not in sids
        assert SID_INDIAMART not in sids
        assert sids == [SID_TRADEINDIA]
        assert any(e.error_type == "ProxyNotConfigured" for e in s.scrape_errors)

    def test_residential_mode_uses_residential_proxy(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        s = make_spider([self.JD])
        reqs = _collect(s)
        assert len(reqs) == 1
        assert reqs[0].sid == SID_JUSTDIAL
        assert reqs[0]._session_kwargs["proxy"] == "http://user:pass@residential.example:3128"
        assert s._jd_mode == "residential"

    def test_robots_disallowed_skips_target(self, make_spider, monkeypatch):
        monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: False)
        s = make_spider([self.TI])
        assert _collect(s) == []
        assert any(e.error_type == "RobotsDisallowed" for e in s.scrape_errors)

    def test_daily_cap_stops_generation(self, make_spider, monkeypatch):
        monkeypatch.setattr(spider_mod.DomainRequestCounter, "allowed", lambda self, d, c: False)
        s = make_spider([self.TI])
        assert _collect(s) == []

    def test_wait_selector_only_on_first_page(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        cfg = dict(self.JD)
        cfg["pages"] = 2
        cfg["fetch_kwargs"] = {"timeout": 90000, "page_delay": 2.0, "wait_selector": ".card"}
        s = make_spider([cfg])

        reqs = _collect(s)
        by_page = {r.meta["page"]: r for r in reqs}
        assert set(by_page) == {1, 2}
        assert by_page[1]._session_kwargs["wait_selector"] == ".card"
        assert "wait_selector" not in by_page[2]._session_kwargs

    def test_disabled_target_is_skipped(self, make_spider):
        cfg = dict(self.JD)
        cfg["enabled"] = False
        s = make_spider([cfg])
        assert _collect(s) == []


class TestStartRequestsExpansion:
    """SC-001 — start_requests yields exactly N×M page-1 Requests per site (lazy)."""

    def _n_m_config(self, n_cats, n_cities, monkeypatch):
        cats = [{
            "slug": f"cat{i}",
            "labels": {"indiamart": f"cat-{i}", "tradeindia": f"cat{i}"},
        } for i in range(n_cats)]
        cities = [{
            "slug": f"city{i}",
            "labels": {"indiamart": f"city{i}", "tradeindia": f"city{i}"},
            "tradeindia_code": str(100000 + i),
        } for i in range(n_cities)]
        full = {
            "categories": cats,
            "cities": cities,
            "url_templates": {
                "justdial": "https://www.justdial.com/{city}/{category}/nct-10278073",
                "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
                "tradeindia": "https://www.tradeindia.com/{city}/{category}-city-{code}.html",
            },
            "icp_categories": [],
            "icp_cities": [],
        }
        monkeypatch.setattr(spider_mod, "load_full_config", lambda: full)

    def test_two_by_two_yields_four_per_site(self, make_spider, monkeypatch, proxy_pool):
        self._n_m_config(2, 2, monkeypatch)
        s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
        reqs = _collect(s)
        im = [r for r in reqs if r.sid == SID_INDIAMART]
        ti = [r for r in reqs if r.sid == SID_TRADEINDIA]
        assert len(im) == 4
        assert len(ti) == 4
        assert all(r.meta["page"] == 1 for r in im + ti)
        assert all(r.meta["pages_total"] == 10 for r in im + ti)

    def test_requests_carry_sid_and_session_kwargs(self, make_spider, monkeypatch, proxy_pool):
        self._n_m_config(1, 1, monkeypatch)
        s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
        reqs = _collect(s)
        by_sid = {r.sid: r for r in reqs}
        assert by_sid[SID_TRADEINDIA]._session_kwargs == {"timeout": 90000}
        assert by_sid[SID_INDIAMART]._session_kwargs["proxy"].startswith("http://")
        assert by_sid[SID_INDIAMART].meta["daily_cap"] == 10

    def test_stale_scrape_full_pages_ignored(self, make_spider, monkeypatch, proxy_pool):
        """US2/Q5 — a stale SCRAPE_FULL_PAGES env var is ignored; max_pages is sole control."""
        monkeypatch.setenv("SCRAPE_FULL_PAGES", "true")
        self._n_m_config(1, 1, monkeypatch)
        s = make_spider([TestStartRequests.TI])
        reqs = _collect(s)
        assert len(reqs) == 1  # page 1 only (lazy), regardless of stale gate
        assert reqs[0].meta["pages_total"] == 10

        monkeypatch.setenv("SCRAPE_FULL_PAGES", "false")
        s2 = make_spider([TestStartRequests.TI])
        reqs2 = _collect(s2)
        assert len(reqs2) == 1
        assert reqs2[0].meta["pages_total"] == 10

    def test_robots_disallowed_reported_once_per_domain(self, make_spider, monkeypatch):
        """H2 — a per-domain robots disallow logs one error, not one per combo."""
        self._n_m_config(2, 2, monkeypatch)
        monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: False)
        s = make_spider([TestStartRequests.TI])
        _collect(s)
        errs = [e for e in s.scrape_errors if e.error_type == "RobotsDisallowed"]
        assert len(errs) == 1

    def test_missing_tradeindia_code_skips_site_with_config_error(
        self, make_spider, monkeypatch, proxy_pool,
    ):
        """M1 — a missing tradeindia_code fails loudly for TI only; IM keeps crawling."""
        full = {
            "categories": [{"slug": "c0", "labels": {"indiamart": "c0", "tradeindia": "c0"}}],
            "cities": [{"slug": "ci0", "labels": {"indiamart": "ci0", "tradeindia": "ci0"}}],
            "url_templates": {
                "justdial": "https://www.justdial.com/{city}/{category}/nct-10278073",
                "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
                "tradeindia": "https://www.tradeindia.com/{city}/{category}-city-{code}.html",
            },
            "icp_categories": [],
            "icp_cities": [],
        }
        monkeypatch.setattr(spider_mod, "load_full_config", lambda: full)
        s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
        reqs = _collect(s)
        assert len(reqs) == 1
        assert all(r.sid == SID_INDIAMART for r in reqs)
        assert any(e.error_type == "ConfigError" for e in s.scrape_errors)

    def test_invalid_max_pages_records_config_error(self, make_spider):
        """M4 — max_pages < 1 fails loudly per site instead of silently over-running."""
        cfg = dict(TestStartRequests.TI)
        cfg["max_pages"] = 0
        s = make_spider([cfg])
        assert _collect(s) == []
        assert any(e.error_type == "ConfigError" for e in s.scrape_errors)

    def test_enabled_defaults_to_false(self, make_spider):
        """M4 — a target without an `enabled` key is skipped (contract default false)."""
        cfg = dict(TestStartRequests.TI)
        cfg.pop("enabled")
        s = make_spider([cfg])
        assert _collect(s) == []

    def test_icp_allowlists_inert_at_crawl(self, make_spider, monkeypatch, proxy_pool):
        """V12/FR-002 — populated ICP allowlists change nothing at crawl time."""
        self._n_m_config(2, 2, monkeypatch)
        full = spider_mod.load_full_config()
        full["icp_categories"] = ["cat0"]
        full["icp_cities"] = ["city0"]
        monkeypatch.setattr(spider_mod, "load_full_config", lambda: full)
        s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
        reqs = _collect(s)
        assert len([r for r in reqs if r.sid == SID_INDIAMART]) == 4
        assert len([r for r in reqs if r.sid == SID_TRADEINDIA]) == 4
        assert s.scrape_errors == []

    def test_empty_categories_at_spider_level_continues(self, make_spider, monkeypatch, caplog):
        """V11 — empty categories → no combos, explicit warning, run continues."""
        self._n_m_config(0, 2, monkeypatch)
        import logging
        with caplog.at_level(logging.WARNING):
            s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
            assert _collect(s) == []
        assert "No categories configured" in caplog.text

    def test_robots_disallowed_domain_never_consumes_cap(self, make_spider, monkeypatch, proxy_pool):
        """T008 — robots runs before cap; a disallowed domain consumes zero budget."""
        self._n_m_config(2, 2, monkeypatch)

        def robots(url, **kw):
            return "indiamart.com" not in url

        monkeypatch.setattr(spider_mod, "is_robots_allowed", robots)
        consumed = []
        monkeypatch.setattr(
            spider_mod.DomainRequestCounter, "allowed",
            lambda self, domain, cap: consumed.append(domain) or True,
        )
        s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
        _collect(s)
        assert "dir.indiamart.com" not in consumed
        assert consumed == ["www.tradeindia.com"] * 4

    def test_large_cross_product_cap_bounds_requests(
        self, monkeypatch, isolated_counter, proxy_pool,
    ):
        """SC-004 — 100 IndiaMART combos with a cap of 5 yield exactly 5 requests; TradeIndia continues."""
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: True)
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        self._n_m_config(10, 10, monkeypatch)
        im = dict(TestStartRequests.IM)
        im["max_requests_per_day"] = 5
        ti = dict(TestStartRequests.TI)
        ti["max_requests_per_day"] = 1000
        s = spider_mod.LeadSpider([im, ti])
        reqs = _collect(s)
        im_reqs = [r for r in reqs if r.sid == SID_INDIAMART]
        ti_reqs = [r for r in reqs if r.sid == SID_TRADEINDIA]
        assert len(im_reqs) == 5
        assert len(ti_reqs) == 100
        assert "dir.indiamart.com" in s._cap_reached
        assert "www.tradeindia.com" not in s._cap_reached
        assert all(r.meta["page"] == 1 for r in reqs)


class TestLazyPagination:
    """T009/T011 — lazy pagination + early-stop for IndiaMART/TradeIndia."""

    @staticmethod
    def _response(meta, body=b"<html>lead page</html>"):
        resp = MagicMock()
        resp.status = 200
        resp.body = body
        resp.html_content = body
        resp.text = body.decode("utf-8", errors="replace")
        resp.meta = meta
        resp.url = meta["source_url"]
        return resp

    @staticmethod
    def _collect(s, response):
        async def run():
            out = []
            async for item in s.parse(response):
                out.append(item)
            return out
        return anyio.run(run)

    def _im_meta(self, **over):
        meta = {
            "parser": "parse_indiamart",
            "source_url": "https://dir.indiamart.com/new-delhi/software-development-services.html",
            "site_name": "IndiaMART",
            "category_slug": "software-development",
            "city_slug": "new-delhi",
            "fetch_kwargs": {"timeout": 120000, "wait_selector": ".card"},
            "page": 1,
            "pages_total": 5,
            "daily_cap": 40,
        }
        meta.update(over)
        return meta

    def _register_parser(self, monkeypatch, records):
        def fake_parser(response, source_url=""):
            return [RawRecord(company_name=n, source_url=source_url) for n in records]
        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_indiamart", fake_parser)

    def test_new_listings_yields_next_page(self, make_spider, monkeypatch, proxy_pool):
        s = make_spider([TestStartRequests.IM])
        self._register_parser(monkeypatch, ["Acme", "Beta"])
        out = self._collect(s, self._response(self._im_meta()))
        next_reqs = [x for x in out if isinstance(x, Request)]
        assert len(next_reqs) == 1
        req = next_reqs[0]
        assert req.sid == SID_INDIAMART
        assert req.meta["page"] == 2
        assert req.meta["pages_total"] == 5
        assert req.meta["category_slug"] == "software-development"
        assert "wait_selector" not in req._session_kwargs
        assert req._session_kwargs["proxy"].startswith("http://")
        assert req.url == "https://dir.indiamart.com/new-delhi/software-development-services.html?page=2"
        assert s._early_stopped_targets == {}

    def test_max_pages_never_exceeded(self, make_spider, monkeypatch, proxy_pool):
        s = make_spider([TestStartRequests.IM])
        self._register_parser(monkeypatch, ["Acme"])
        out = self._collect(s, self._response(self._im_meta(page=5, pages_total=5)))
        next_reqs = [x for x in out if isinstance(x, Request)]
        assert next_reqs == []

    def test_all_duplicate_page_early_stops(self, make_spider, monkeypatch, proxy_pool):
        s = make_spider([TestStartRequests.IM])
        self._register_parser(monkeypatch, ["Acme", "Beta"])
        self._collect(s, self._response(self._im_meta(page=1)))
        # page 2 repeats every listing from page 1 → 0 new → early-stop
        out2 = self._collect(s, self._response(self._im_meta(page=2)))
        next_reqs = [x for x in out2 if isinstance(x, Request)]
        assert next_reqs == []
        assert s._early_stopped_targets[("indiamart", "software-development", "new-delhi")] == "0_new"

    def test_empty_page_early_stops(self, make_spider, monkeypatch, proxy_pool):
        s = make_spider([TestStartRequests.IM])
        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_indiamart",
                            lambda response, source_url="": [])
        out = self._collect(s, self._response(self._im_meta()))
        assert out == []
        assert s._early_stopped_targets[("indiamart", "software-development", "new-delhi")] == "empty"

    def test_blocked_page_retried_not_early_stopped(self, make_spider, monkeypatch):
        """US2-AS4 — a blocked body is retried by the engine and never mistaken for an empty result."""
        from scrapling.spiders.engine import CrawlerEngine

        s = make_spider([TestStartRequests.TI])
        s.download_delays = {}
        session = _StubSessionManager([(429, b"Rate limited"), (200, b"x" * 5000)])
        engine = CrawlerEngine(s, session, crawldir=None)
        req = Request(
            "https://www.tradeindia.com/x", sid=SID_TRADEINDIA,
            meta={"parser": "parse_tradeindia", "source_url": "https://www.tradeindia.com/x",
                  "site_name": "TradeIndia", "category_slug": "c", "city_slug": "ci",
                  "fetch_kwargs": {}, "page": 1, "pages_total": 5, "daily_cap": 40},
        )

        async def run():
            await engine._process_request(req)
            return engine.scheduler.snapshot()

        pending, _ = anyio.run(run)
        assert len(pending) == 1  # re-enqueued for retry, not dropped
        assert engine.stats.blocked_requests_count == 1
        assert s._early_stopped_targets == {}  # never recorded as early-stop

    def test_next_page_carries_pages_total_for_tradeindia(self, make_spider, monkeypatch):
        s = make_spider([TestStartRequests.TI])
        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_tradeindia",
                            lambda response, source_url="": [RawRecord(company_name="A", source_url=source_url)])
        meta = {
            "parser": "parse_tradeindia",
            "source_url": "https://www.tradeindia.com/new-delhi/software-development-city-228067.html",
            "site_name": "TradeIndia",
            "category_slug": "software-development",
            "city_slug": "new-delhi",
            "fetch_kwargs": {"timeout": 90000},
            "page": 1,
            "pages_total": 7,
            "daily_cap": 100,
        }
        out = self._collect(s, self._response(meta))
        next_reqs = [x for x in out if isinstance(x, Request)]
        assert len(next_reqs) == 1
        assert next_reqs[0].sid == SID_TRADEINDIA
        assert next_reqs[0].meta["pages_total"] == 7
        assert next_reqs[0]._session_kwargs == {"timeout": 90000}

    def test_next_page_stops_gracefully_when_no_proxy(self, make_spider, monkeypatch):
        """F2 — no proxy for a stealth next page stops the target without raising."""
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        s = make_spider([TestStartRequests.IM])
        self._register_parser(monkeypatch, ["Acme"])
        out = self._collect(s, self._response(self._im_meta()))
        next_reqs = [x for x in out if isinstance(x, Request)]
        assert next_reqs == []
        items = [x for x in out if isinstance(x, dict)]
        assert len(items) == 1  # page records still emitted
        assert s._early_stopped_targets[("indiamart", "software-development", "new-delhi")] == "no_proxy"

    def test_justdial_parse_never_early_stopped(self, make_spider, monkeypatch):
        """FR-004 — JD eager depth is not subject to lazy early-stop."""
        s = make_spider([TestStartRequests.JD])
        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_justdial",
                            lambda response, source_url="": [RawRecord(company_name="Acme", source_url=source_url)])
        meta = {
            "parser": "parse_justdial",
            "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073",
            "site_name": "Justdial",
            "category_slug": "it-services",
            "city_slug": "delhi",
            "fetch_kwargs": {},
            "page": 1,
            "pages_total": 3,
            "daily_cap": 10,
        }
        out = self._collect(s, self._response(meta))
        assert s._early_stopped_targets == {}
        assert s._jd_stats["succeeded"] == 1
        assert all(not isinstance(x, Request) for x in out)
        assert len([x for x in out if isinstance(x, dict)]) == 1

    def test_all_empty_company_names_early_stops_but_emits(self, make_spider, monkeypatch):
        """F9 — records with empty names count as 0 new (early-stop) but still emit."""
        s = make_spider([TestStartRequests.IM])
        self._register_parser(monkeypatch, ["", ""])
        out = self._collect(s, self._response(self._im_meta()))
        assert s._early_stopped_targets[("indiamart", "software-development", "new-delhi")] == "0_new"
        items = [x for x in out if isinstance(x, dict)]
        assert len(items) == 2
        assert all(not isinstance(x, Request) for x in out)

    def test_page_three_all_duplicates_never_requests_four(self, make_spider, monkeypatch, proxy_pool):
        """V4 — a target whose results end on page 3 issues zero requests for pages 4-10."""
        s = make_spider([TestStartRequests.IM])
        plan = {"p1": ["A", "B"], "p2": ["C"], "p3": ["C"]}

        def fake(response, source_url=""):
            return [RawRecord(company_name=n, source_url=source_url)
                    for n in plan[response.meta["page_key"]]]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_indiamart", fake)
        out = self._collect(s, self._response(self._im_meta(pages_total=10, page_key="p1")))
        assert len([x for x in out if isinstance(x, Request)]) == 1  # page 2
        out = self._collect(s, self._response(self._im_meta(pages_total=10, page=2, page_key="p2")))
        assert len([x for x in out if isinstance(x, Request)]) == 1  # page 3
        out = self._collect(s, self._response(self._im_meta(pages_total=10, page=3, page_key="p3")))
        assert [x for x in out if isinstance(x, Request)] == []  # pages 4-10 never requested
        assert s._early_stopped_targets[("indiamart", "software-development", "new-delhi")] == "0_new"

    def test_early_stop_is_per_target_other_targets_continue(self, make_spider, monkeypatch, proxy_pool):
        """V4 — stopping one category×city target does not stop another target."""
        full = {
            "categories": [
                {"slug": "cat0", "labels": {"indiamart": "cat-0", "tradeindia": "cat0"}},
                {"slug": "cat1", "labels": {"indiamart": "cat-1", "tradeindia": "cat1"}},
            ],
            "cities": [{
                "slug": "city0", "labels": {"indiamart": "city0", "tradeindia": "city0"},
                "tradeindia_code": "100000",
            }],
            "url_templates": {
                "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
                "tradeindia": "https://www.tradeindia.com/{city}/{category}-city-{code}.html",
            },
            "icp_categories": [],
            "icp_cities": [],
        }
        monkeypatch.setattr(spider_mod, "load_full_config", lambda: full)
        s = make_spider([TestStartRequests.IM])
        content = {"cat0": ["Acme"], "cat1": ["Beta"]}

        def fake(response, source_url=""):
            return [RawRecord(company_name=n, source_url=source_url)
                    for n in content[response.meta["category_slug"]]]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_indiamart", fake)
        out = self._collect(s, self._response(self._im_meta(category_slug="cat0", city_slug="city0")))
        assert len([x for x in out if isinstance(x, Request)]) == 1  # cat0 page 2
        out = self._collect(s, self._response(self._im_meta(category_slug="cat0", city_slug="city0", page=2)))
        assert [x for x in out if isinstance(x, Request)] == []  # cat0 early-stops
        out = self._collect(s, self._response(self._im_meta(category_slug="cat1", city_slug="city0")))
        assert len([x for x in out if isinstance(x, Request)]) == 1  # cat1 still paginates
        assert s._early_stopped_targets[("indiamart", "cat0", "city0")] == "0_new"
        assert ("indiamart", "cat1", "city0") not in s._early_stopped_targets

    def test_next_page_does_not_recheck_robots(self, make_spider, monkeypatch, proxy_pool):
        """U6 — pagination relies on the page-1 robots cache; no per-page re-check."""
        calls = []
        monkeypatch.setattr(spider_mod, "is_robots_allowed",
                            lambda url, **kw: calls.append(url) or True)
        s = make_spider([TestStartRequests.IM])
        reqs = _collect(s)  # page 1 start request → one robots check per domain
        assert len(reqs) == 1
        self._register_parser(monkeypatch, ["Acme"])
        out = self._collect(s, self._response(self._im_meta()))
        assert len([x for x in out if isinstance(x, Request)]) == 1  # page 2 yielded
        assert len(calls) == 1  # robots not re-checked for page 2


class TestDailyCaps:
    """T012/T013 — hard stop per domain, enrichment counting, same-day persistence, day reset."""

    def test_cap_hard_stop_per_domain(self, make_spider, monkeypatch, proxy_pool):
        allowed_calls = []

        def fake_allowed(self, domain, cap):
            allowed_calls.append(domain)
            return domain != "dir.indiamart.com"  # IndiaMART exhausted, TradeIndia allowed

        monkeypatch.setattr(spider_mod.DomainRequestCounter, "allowed", fake_allowed)
        s = make_spider([TestStartRequests.IM, TestStartRequests.TI])
        reqs = _collect(s)
        assert [r.sid for r in reqs] == [SID_TRADEINDIA]
        assert "dir.indiamart.com" in allowed_calls
        assert "www.tradeindia.com" in allowed_calls
        assert "dir.indiamart.com" in s._cap_reached

    def test_parse_next_page_stops_when_cap_exhausted(self, small_config, isolated_counter, monkeypatch):
        """T013 — the cap is checked at every page yield point (parse included)."""
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: True)
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        s = spider_mod.LeadSpider([TestStartRequests.TI])

        # exhaust the tradeindia budget (real counter persisted via isolated_counter)
        assert s._req_counter.allowed("www.tradeindia.com", 2) is True
        assert s._req_counter.allowed("www.tradeindia.com", 2) is True

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_tradeindia",
                            lambda response, source_url="": [RawRecord(company_name="A", source_url=source_url)])
        meta = {
            "parser": "parse_tradeindia",
            "source_url": "https://www.tradeindia.com/x",
            "site_name": "TradeIndia",
            "category_slug": "c", "city_slug": "ci",
            "fetch_kwargs": {"timeout": 90000},
            "page": 1, "pages_total": 5, "daily_cap": 2,
        }
        resp = TestLazyPagination._response(meta)
        out = TestLazyPagination._collect(s, resp)
        next_reqs = [x for x in out if isinstance(x, Request)]
        assert next_reqs == []
        assert "www.tradeindia.com" in s._cap_reached
        assert s._early_stopped_targets[("tradeindia", "c", "ci")] == "cap_reached"

    def test_justdial_cap_counts_each_page_request(self, small_config, isolated_counter, monkeypatch):
        """F1 — JD consumes one budget unit per page request, not one per combo."""
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: True)
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        cfg = dict(TestStartRequests.JD)
        cfg["pages"] = 3
        cfg["max_requests_per_day"] = 2
        s = spider_mod.LeadSpider([cfg])
        reqs = _collect(s)
        assert len(reqs) == 2  # cap 2 → only 2 of the 3 eager pages yielded
        assert all(r.sid == SID_JUSTDIAL for r in reqs)
        assert "www.justdial.com" in s._cap_reached

    def test_on_close_im_enrichment_runs_once(self, small_config, isolated_counter, monkeypatch):
        """M5 — multiple IM _enrich_data entries trigger a single httpx enrichment pass."""
        from unittest.mock import MagicMock as _MM
        import anyio
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        s = spider_mod.LeadSpider([TestStartRequests.IM])
        s._enrich_data = [
            {"parser": "parse_indiamart", "domain": "dir.indiamart.com", "daily_cap": 40},
            {"parser": "parse_indiamart", "domain": "dir.indiamart.com", "daily_cap": 40},
        ]
        calls = []
        monkeypatch.setattr(
            spider_mod, "_enrich_indiamart_via_httpx",
            lambda records, proxy, cap_guard: calls.append(1) or 0,
        )
        anyio.run(s.on_close)
        assert calls == [1]

    def test_enrichment_detail_pages_count_against_cap(self):
        """T014 — cap_guard gates each detail-page fetch; a record that is
        already enriched consumes no budget unit (L2 fix)."""
        from src.scraper.targets import _enrich_from_detail_pages
        rec0 = RawRecord(company_name="A", phone=None, email=None)
        rec1 = RawRecord(company_name="B", phone=None, email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"Contact: 9876543210, info@co.com"
        session.fetch.return_value = resp
        calls = []

        def guard():
            calls.append(1)
            return len(calls) <= 1  # first fetch allowed, rest denied

        targets = [(0, "https://detail.com/1"), (1, "https://detail.com/2")]
        records = [rec0, rec1]
        _enrich_from_detail_pages(session, records, targets, timeout=30000, cap_guard=guard)
        assert session.fetch.call_count == 1  # second fetch denied → skipped
        assert len(calls) == 2

    def test_cap_not_consumed_for_already_enriched_or_out_of_range(self):
        """L2 — budget units are not spent on records already carrying phone+email."""
        from src.scraper.targets import _enrich_from_detail_pages
        rec = RawRecord(company_name="C", phone="9876543210", email="a@b.com")
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"Contact: 123, x@y.com"
        session.fetch.return_value = resp
        calls = []

        def guard():
            calls.append(1)
            return True

        _enrich_from_detail_pages(
            session, [rec],
            [(0, "https://detail.com/1"), (1, "https://detail.com/2"), (99, "https://detail.com/99")],
            timeout=30000, cap_guard=guard,
        )
        session.fetch.assert_not_called()
        assert calls == []  # cap_guard never invoked for skippable targets

    def test_on_close_ti_enrichment_passes_robots_and_reveal_js(
            self, small_config, isolated_counter, monkeypatch):
        """T010/T003 — on_close gates detail fetches with robots AND reveals JS
        (one click consumes the get-user-mobile XHR), aggregating the stats."""
        import anyio
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        s = spider_mod.LeadSpider([dict(TestStartRequests.TI)])
        s.all_records = [RawRecord(company_name="Acme", phone=None, email=None)]
        s._enrich_data = [{
            "parser": "parse_tradeindia",
            "detail_urls": [(0, "https://www.tradeindia.com/acme-1/")],
            "fetch_kwargs": {"timeout": 90000, "max_detail_pages": 20},
            "domain": "www.tradeindia.com",
            "daily_cap": 10,
        }]
        captured = {}

        def fake_enrich(session, records, targets, timeout, cap_guard, robots_allowed, reveal_js):
            captured["robots_allowed"] = robots_allowed
            captured["reveal_js"] = reveal_js
            captured["targets"] = targets
            return {"attempted": 1, "fetched": 1, "fetch_failed": 0,
                    "phone_unavailable": 0, "email_unavailable": 0, "website_unavailable": 1}

        monkeypatch.setattr(spider_mod, "_enrich_from_detail_pages", fake_enrich)
        anyio.run(s.on_close)
        assert captured["reveal_js"] is True
        assert captured["robots_allowed"] is spider_mod.is_robots_allowed
        assert captured["targets"] == [(0, "https://www.tradeindia.com/acme-1/")]
        assert s._detail_enrich_stats["attempted"] == 1
        assert s._detail_enrich_stats["fetched"] == 1
        assert s._detail_enrich_stats["website_unavailable"] == 1

    def test_on_close_seeds_zero_fill_rate_for_enabled_target(
            self, small_config, isolated_counter, monkeypatch, caplog):
        """SC-003 — a 0-record run still reports a 0/0 row for every enabled target."""
        import anyio
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        s = spider_mod.LeadSpider([{
            "name": "TradeIndia", "enabled": True, "parser": "parse_tradeindia",
            "pages": 1, "max_requests_per_day": 10,
            "fetch_kwargs": {"timeout": 90000},
        }])
        assert s.all_records == []
        with caplog.at_level(logging.INFO, logger="src.scraper.spider"):
            anyio.run(s.on_close)
        assert s._fill_rates["TradeIndia"] == {"total": 0, "phone": 0, "email": 0, "website": 0}
        assert "TradeIndia: 0 records, phone=0/0, email=0/0, website=0/0" in caplog.text

    def test_on_close_ti_global_detail_budget_across_entries(
            self, small_config, isolated_counter, monkeypatch):
        """SC-001/H2 — max_detail_pages is a per-RUN budget shared across every
        _enrich_data entry, not a per-page budget."""
        import anyio
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        s = spider_mod.LeadSpider([dict(TestStartRequests.TI)])
        s.all_records = [
            RawRecord(company_name="A", phone=None, email=None),
            RawRecord(company_name="B", phone=None, email=None),
            RawRecord(company_name="C", phone=None, email=None),
        ]
        s._enrich_data = [
            {"parser": "parse_tradeindia", "detail_urls": [(0, "u0"), (1, "u1")],
             "fetch_kwargs": {"timeout": 90000, "max_detail_pages": 2},
             "domain": "www.tradeindia.com", "daily_cap": 100},
            {"parser": "parse_tradeindia", "detail_urls": [(2, "u2")],
             "fetch_kwargs": {"timeout": 90000, "max_detail_pages": 2},
             "domain": "www.tradeindia.com", "daily_cap": 100},
        ]
        handed = []

        def fake_enrich(session, records, targets, timeout, cap_guard, robots_allowed, reveal_js):
            handed.append(list(targets))
            return {"attempted": len(targets), "fetched": len(targets), "fetch_failed": 0,
                    "phone_unavailable": 0, "email_unavailable": 0, "website_unavailable": len(targets)}

        monkeypatch.setattr(spider_mod, "_enrich_from_detail_pages", fake_enrich)
        anyio.run(s.on_close)
        assert handed == [[(0, "u0"), (1, "u1")]]  # second entry skipped: run budget (2) exhausted
        assert s._detail_enrich_stats["attempted"] == 2

    def test_on_close_seed_key_derived_from_site_names(
            self, small_config, isolated_counter, monkeypatch):
        """L6 — seeding key goes through SITE_NAMES so a lowercase config name
        cannot produce a duplicate/divergent fill-rate row."""
        import anyio
        from unittest.mock import MagicMock as _MM
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", _MM)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", _MM)
        s = spider_mod.LeadSpider([{
            "name": "tradeindia", "enabled": True, "parser": "parse_tradeindia",
            "pages": 1, "max_requests_per_day": 10,
            "fetch_kwargs": {"timeout": 90000},
        }])
        s.all_records = [RawRecord(
            company_name="A", source_url="https://www.tradeindia.com/kolkata/x.html")]
        anyio.run(s.on_close)
        assert set(s._fill_rates) == {"TradeIndia"}  # one canonical row
        assert s._fill_rates["TradeIndia"]["total"] == 1

    def test_httpx_enrichment_cap_guard_denied_early(self, monkeypatch):
        """T014 — httpx enrichment respects the cap guard."""
        import sys
        monkeypatch.setitem(sys.modules, "httpx", MagicMock())
        from src.scraper.targets import _enrich_indiamart_via_httpx
        rec = RawRecord(company_name="C", phone=None)
        calls = []

        def guard():
            calls.append(1)
            return False

        assert _enrich_indiamart_via_httpx([rec], None, guard) == 0
        assert calls == [1]

    def test_second_same_day_run_respects_consumed_budget(self, isolated_counter):
        """US3-AS3 — a second run sees the first run's consumed budget."""
        from src.scraper.spider import DomainRequestCounter
        counter1 = DomainRequestCounter()
        assert counter1.allowed("dir.indiamart.com", 1) is True
        assert counter1.allowed("dir.indiamart.com", 1) is False

        counter2 = DomainRequestCounter()  # same calendar day, same persisted store
        assert counter2.allowed("dir.indiamart.com", 1) is False
        assert counter2.snapshot().get("dir.indiamart.com") == 1

    def test_new_calendar_day_resets_budget(self, isolated_counter, monkeypatch):
        """US3-AS4 — a new calendar day resets per-domain budgets."""
        from src.scraper.spider import DomainRequestCounter
        counter1 = DomainRequestCounter()
        assert counter1.allowed("dir.indiamart.com", 1) is True
        assert counter1.snapshot().get("dir.indiamart.com") == 1

        monkeypatch.setattr(spider_mod.time, "strftime", lambda fmt: "2099-01-02")
        counter2 = DomainRequestCounter()
        assert counter2.allowed("dir.indiamart.com", 1) is True  # budget reset
        assert counter2.snapshot().get("dir.indiamart.com") == 1


class TestOnStart:
    def test_on_start_sets_datacenter_mode(self, make_spider, proxy_pool):
        s = make_spider([])
        anyio.run(s.on_start, False)
        assert s._jd_mode == "datacenter"

    def test_on_start_sets_no_proxy_mode(self, make_spider, monkeypatch):
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        s = make_spider([])
        anyio.run(s.on_start, False)
        assert s._jd_mode == "no_proxy"


class TestEngineRetryLoop:
    """Engine-level blocked→retry→re-enqueue wiring (FR-005, SC-002)."""

    def _make_engine(self, spider, session):
        from scrapling.spiders.engine import CrawlerEngine

        spider.download_delays = {}
        return CrawlerEngine(spider, session, crawldir=None)

    @staticmethod
    def _stub_session(status=429, body=b"Rate limited"):
        class StubSession:
            default_session_id = "default"

            async def fetch(self, request):
                return MagicMock(status=status, body=body, headers={}, url=request.url)

        return StubSession()

    def test_blocked_request_is_re_enqueued(self, make_spider, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        s = make_spider([])
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: "http://user:pass@9.9.9.9:8080")
        engine = self._make_engine(s, self._stub_session())
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL, proxy="http://user:pass@1.2.3.4:8080")

        async def run():
            await engine._process_request(req)
            pending, _ = engine.scheduler.snapshot()
            return pending

        pending = anyio.run(run)
        assert len(pending) == 1
        retried = pending[0]
        assert retried._retry_count == 1
        assert retried._session_kwargs["proxy"] == "http://user:pass@9.9.9.9:8080"
        assert engine.stats.blocked_requests_count == 1

    def test_max_retries_exhausted_not_re_enqueued(self, make_spider):
        s = make_spider([])
        engine = self._make_engine(s, self._stub_session())
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL)
        req._retry_count = 3

        async def run():
            await engine._process_request(req)
            pending, _ = engine.scheduler.snapshot()
            return pending

        pending = anyio.run(run)
        assert pending == []
        assert engine.stats.blocked_requests_count == 1

    @pytest.mark.parametrize("retry_count,re_enqueued", [(0, True), (1, True), (2, True), (3, False)])
    def test_re_enqueue_until_limit(self, make_spider, monkeypatch, retry_count, re_enqueued):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: "http://user:pass@9.9.9.9:8080")
        s = make_spider([])
        engine = self._make_engine(s, self._stub_session())
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL, proxy="http://user:pass@1.2.3.4:8080")
        req._retry_count = retry_count

        async def run():
            await engine._process_request(req)
            pending, _ = engine.scheduler.snapshot()
            return pending

        pending = anyio.run(run)
        if re_enqueued:
            assert len(pending) == 1
            assert pending[0]._retry_count == retry_count + 1
            assert pending[0]._session_kwargs["proxy"] == "http://user:pass@9.9.9.9:8080"
            assert engine.stats.blocked_requests_count == 1
        else:
            assert pending == []

    def test_full_retry_loop_three_attempts_exact_counts(self, make_spider, monkeypatch):
        """SC-002: initial + exactly 3 retries, then drop (no more, no less)."""
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_get_next_proxy", lambda: "http://user:pass@9.9.9.9:8080")
        s = make_spider([])
        engine = self._make_engine(s, self._stub_session())
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL, proxy="http://user:pass@1.2.3.4:8080")

        async def drain():
            fetches = 0
            await engine.scheduler.enqueue(req)
            while not engine.scheduler.is_empty:
                current = await engine.scheduler.dequeue()
                try:
                    await engine._process_request(current)
                finally:
                    engine.scheduler.complete(current)
                fetches += 1
            return fetches

        assert anyio.run(drain) == 4
        assert engine.stats.blocked_requests_count == 4

    def test_exhausted_block_does_not_abort_remaining_requests(self, make_spider, monkeypatch):
        """Spec edge case: one blocked item exhausting retries must not abort the crawl."""
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        s = make_spider([])

        def stub_by_url(responses):
            class StubSession:
                default_session_id = "default"

                async def fetch(self, request):
                    status, body = responses[request.url]
                    return MagicMock(status=status, body=body, headers={}, url=request.url)

            return StubSession()

        engine = self._make_engine(s, stub_by_url({
            "https://www.justdial.com/blocked": (429, b"Rate limited"),
            "https://www.tradeindia.com/ok": (200, b"x" * 5000),
        }))

        blocked = Request("https://www.justdial.com/blocked", sid=SID_JUSTDIAL)
        blocked._retry_count = 3

        scraped = []

        async def cb(response):
            scraped.append(response.url)
            yield {"company_name": "OK"}

        ok = Request("https://www.tradeindia.com/ok", sid=SID_TRADEINDIA, callback=cb)

        async def run():
            await engine._process_request(blocked)
            await engine._process_request(ok)

        anyio.run(run)
        pending, _ = engine.scheduler.snapshot()
        assert pending == []
        assert engine.stats.blocked_requests_count == 1
        assert engine.stats.items_scraped == 1
        assert scraped == ["https://www.tradeindia.com/ok"]


class TestCheckpointRestore:
    """US4/FR-009: checkpoint save/load and corrupt-file fallback."""

    def _make_engine(self, spider, tmp_path):
        from scrapling.spiders.engine import CrawlerEngine

        return CrawlerEngine(spider, spider._session_manager, crawldir=str(tmp_path))

    def test_restore_from_valid_checkpoint(self, make_spider, tmp_path):
        from scrapling.spiders.checkpoint import CheckpointData

        s = make_spider([])
        engine = self._make_engine(s, tmp_path)
        req = Request("https://www.justdial.com/x", sid=SID_JUSTDIAL)

        async def save():
            await engine._checkpoint_manager.save(CheckpointData(requests=[req], seen=set()))

        anyio.run(save)
        restored = anyio.run(engine._restore_from_checkpoint)
        assert restored is True
        pending, seen = engine.scheduler.snapshot()
        assert len(pending) == 1
        assert pending[0].sid == SID_JUSTDIAL

    def test_restore_from_corrupt_checkpoint_starts_fresh(self, make_spider, tmp_path):
        s = make_spider([])
        engine = self._make_engine(s, tmp_path)
        (tmp_path / "checkpoint.pkl").write_bytes(b"definitely not a pickle")

        restored = anyio.run(engine._restore_from_checkpoint)
        assert restored is False
        pending, _ = engine.scheduler.snapshot()
        assert pending == []

    def test_missing_checkpoint_returns_false(self, make_spider, tmp_path):
        """FR-009: no checkpoint file -> no resume; crawl must start from scratch."""
        s = make_spider([])
        engine = self._make_engine(s, tmp_path)
        assert anyio.run(engine._restore_from_checkpoint) is False

    def test_restore_restores_pending_and_seen_set(self, make_spider, tmp_path):
        """SC-004: resume restores the pending queue AND the seen-set blocks re-fetch."""
        from scrapling.spiders.checkpoint import CheckpointData

        s = make_spider([])
        engine = self._make_engine(s, tmp_path)
        url_a = "https://www.justdial.com/a"
        url_b = "https://www.justdial.com/b"
        req_a = Request(url_a, sid=SID_JUSTDIAL)
        req_b = Request(url_b, sid=SID_JUSTDIAL)

        async def setup():
            await engine.scheduler.enqueue(req_a)
            await engine.scheduler.enqueue(req_b)
            done = await engine.scheduler.dequeue()  # A in flight
            engine.scheduler.complete(done)          # A finished -> no longer pending
            await engine._save_checkpoint()

        anyio.run(setup)

        s2 = make_spider([])
        engine2 = self._make_engine(s2, tmp_path)
        assert anyio.run(engine2._restore_from_checkpoint) is True
        pending, seen = engine2.scheduler.snapshot()
        assert [r.url for r in pending] == [url_b]
        assert req_a.update_fingerprint() in seen
        assert req_b.update_fingerprint() in seen
        # Completed URL must never be re-fetched after resume.
        assert anyio.run(engine2.scheduler.enqueue, Request(url_a, sid=SID_JUSTDIAL)) is False

    @staticmethod
    def _noop_session_manager():
        class NoopSessionManager:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            async def fetch(self, request):
                resp = MagicMock(status=200, body=b"x" * 5000, headers={}, url=request.url, meta={})
                resp.request = request
                resp.meta = {**request.meta, **resp.meta}
                return resp

        return NoopSessionManager()

    def test_crawl_without_checkpoint_starts_fresh(self, make_spider, tmp_path, monkeypatch):
        from scrapling.spiders.engine import CrawlerEngine

        s = make_spider([])
        s.download_delays = {}
        start_calls = []
        flags = []

        async def tracked_start_requests(self):
            start_calls.append(1)
            if False:
                yield

        async def spy_on_start(self, resuming=False):
            flags.append(resuming)

        monkeypatch.setattr(spider_mod.LeadSpider, "start_requests", tracked_start_requests)
        monkeypatch.setattr(spider_mod.LeadSpider, "on_start", spy_on_start)
        engine = CrawlerEngine(s, self._noop_session_manager(), crawldir=str(tmp_path))
        anyio.run(engine.crawl)
        assert flags == [False]
        assert start_calls == [1]

    def test_crawl_with_checkpoint_resumes_pending_only(self, make_spider, tmp_path, monkeypatch):
        from scrapling.spiders.checkpoint import CheckpointData
        from scrapling.spiders.engine import CrawlerEngine

        s1 = make_spider([])
        engine1 = self._make_engine(s1, tmp_path)
        req = Request(
            "https://www.justdial.com/x", sid=SID_JUSTDIAL,
            meta={"parser": "no_such_parser", "source_url": "https://www.justdial.com/x"},
        )
        anyio.run(
            engine1._checkpoint_manager.save,
            CheckpointData(requests=[req], seen={req.update_fingerprint()}),
        )

        s2 = make_spider([])
        s2.download_delays = {}
        start_calls = []
        flags = []

        async def tracked_start_requests(self):
            start_calls.append(1)
            if False:
                yield

        async def spy_on_start(self, resuming=False):
            flags.append(resuming)

        monkeypatch.setattr(spider_mod.LeadSpider, "start_requests", tracked_start_requests)
        monkeypatch.setattr(spider_mod.LeadSpider, "on_start", spy_on_start)
        engine2 = CrawlerEngine(s2, self._noop_session_manager(), crawldir=str(tmp_path))
        anyio.run(engine2.crawl)
        assert flags == [True]
        assert start_calls == []  # resume skips start_requests
        assert engine2.stats.items_scraped == 0
        assert any(e.error_type == "UnknownParser" for e in s2.scrape_errors)
        assert s2.scrape_errors[0].url == "https://www.justdial.com/x"


class TestJdMode:
    """T001/T002/T004 — mode precedence, pool init, resolved-once semantics."""

    def test_jd_mode_residential_only(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        s = make_spider([])
        assert s._determine_jd_mode() == "residential"

    def test_jd_mode_residential_wins_when_both(self, make_spider, monkeypatch, proxy_pool):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        s = make_spider([])
        assert s._determine_jd_mode() == "residential"

    def test_jd_mode_whitespace_falls_through_to_datacenter(self, make_spider, monkeypatch, proxy_pool):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "   ")
        s = make_spider([])
        assert s._determine_jd_mode() == "datacenter"

    def test_jd_mode_whitespace_falls_through_to_no_proxy(self, make_spider, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "   ")
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        s = make_spider([])
        assert s._determine_jd_mode() == "no_proxy"

    def test_jd_mode_pool_only_datacenter(self, make_spider, proxy_pool):
        s = make_spider([])
        assert s._determine_jd_mode() == "datacenter"

    def test_jd_mode_neither_no_proxy(self, make_spider, monkeypatch):
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        s = make_spider([])
        assert s._determine_jd_mode() == "no_proxy"

    def test_jd_mode_init_proxy_pool_called_before_checks(self, make_spider, monkeypatch):
        calls = []
        monkeypatch.setattr(scraper_engine, "_init_proxy_pool", lambda: calls.append(1))
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        s = make_spider([])
        s._determine_jd_mode()
        assert calls == [1]

    def test_jd_mode_resolved_once_per_run(self, make_spider, isolated_counter, monkeypatch, proxy_pool):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        counter = []
        orig = spider_mod.LeadSpider._determine_jd_mode

        def counting(self):
            counter.append(1)
            return orig(self)

        monkeypatch.setattr(spider_mod.LeadSpider, "_determine_jd_mode", counting)
        s = make_spider([TestStartRequests.JD])
        anyio.run(s.on_start, False)
        reqs = _collect(s)
        assert counter == [1]
        assert s._jd_mode == "datacenter"
        assert reqs == []


class TestAsnProbe:
    """T005-T010 — candidate building, ProxyRotator reuse, tally, robustness."""

    PROXIES = [
        "http://u:p@1.1.1.1:80",
        "http://u:p@2.2.2.2:80",
        "http://u:p@3.3.3.3:80",
    ]

    def _clear_webshare_env(self, monkeypatch):
        monkeypatch.delenv("WEBSHARE_PROXY_URL", raising=False)
        monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
        monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)

    def test_empty_pool_skips_with_warning(self, make_spider, isolated_counter, monkeypatch, caplog):
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        anyio.run(s._run_asn_test)
        assert "no distinct Webshare proxy IPs" in caplog.text
        assert s._jd_stats.get("asn_attempted", 0) == 0
        flag = isolated_counter.exists() and '"__jd_asn_test": 1' in isolated_counter.read_text()
        assert not flag

    def test_robots_disallowed_skips(self, make_spider, isolated_counter, monkeypatch):
        monkeypatch.setattr(spider_mod, "is_robots_allowed", lambda url, **kw: False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [self.PROXIES[0]])
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        anyio.run(s._run_asn_test)
        assert any(e.error_type == "RobotsDisallowed" for e in s.scrape_errors)
        assert s._jd_stats.get("asn_attempted", 0) == 0
        flag = isolated_counter.exists() and '"__jd_asn_test": 1' in isolated_counter.read_text()
        assert not flag

    def test_single_request_per_ip_and_tally(self, make_spider, isolated_counter, monkeypatch):
        manager = _StubSessionManager([(200, b"x" * 600), (403, b"blocked"), (200, b"y" * 700)])
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", self.PROXIES)
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        s._session_manager = manager
        anyio.run(s._run_asn_test)
        assert s._jd_stats["asn_attempted"] == 3
        assert s._jd_stats["asn_blocked"] == 1
        assert s._jd_stats["asn_succeeded"] == 2
        assert len(manager.calls) == 3
        assert {c.sid for c in manager.calls} == {SID_JUSTDIAL}
        used = [c._session_kwargs["proxy"] for c in manager.calls]
        assert used == self.PROXIES
        assert all(c._session_kwargs["wait"] >= 2000 for c in manager.calls)
        assert "2.2.2.2:80" in s._jd_stats["blocked_ips"]
        assert '"__jd_asn_test": 1' in isolated_counter.read_text()

    def test_request_error_counts_blocked(self, make_spider, isolated_counter, monkeypatch):
        class BoomManager:
            async def fetch(self, request):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [self.PROXIES[0]])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        s._session_manager = BoomManager()
        anyio.run(s._run_asn_test)
        assert s._jd_stats["asn_attempted"] == 1
        assert s._jd_stats["asn_blocked"] == 1
        assert s._jd_stats["asn_succeeded"] == 0

    def test_exception_in_probe_loop_never_crashes(self, make_spider, isolated_counter, monkeypatch):
        class BoomManager:
            async def fetch(self, request):
                raise RuntimeError("boom")

        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", self.PROXIES)
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        s._session_manager = BoomManager()
        anyio.run(s._run_asn_test)
        assert s._jd_stats["asn_attempted"] == 3
        assert s._jd_stats["asn_blocked"] == 3
        assert s._jd_stats["asn_succeeded"] == 0

    def test_api_called_when_single_rotating_endpoint(self, make_spider, monkeypatch):
        monkeypatch.setenv("WEBSHARE_PROXY_URL", "http://u:p@rotate.webshare.io:80")
        monkeypatch.setenv("WEBSHARE_API_KEY", "test-key")
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@rotate.webshare.io:80"])
        api_result = ["http://u:p@10.0.0.1:80", "http://u:p@10.0.0.2:80"]
        monkeypatch.setattr(scraper_engine, "_fetch_proxies_from_api", lambda key: api_result)
        s = make_spider([])
        assert s._build_asn_candidates() == api_result

    def test_pool_distinct_used_without_api_call(self, make_spider, monkeypatch):
        def fail(key):
            raise AssertionError("API must not be called when pool has distinct IPs")

        self._clear_webshare_env(monkeypatch)
        monkeypatch.setenv("WEBSHARE_API_KEY", "test-key")
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", self.PROXIES)
        monkeypatch.setattr(scraper_engine, "_fetch_proxies_from_api", fail)
        s = make_spider([])
        assert s._build_asn_candidates() == self.PROXIES

    def test_api_failure_falls_back_to_rotating_endpoint(self, make_spider, monkeypatch):
        def boom(key):
            raise RuntimeError("401 Unauthorized")

        monkeypatch.setenv("WEBSHARE_PROXY_URL", "http://u:p@rotate.webshare.io:80")
        monkeypatch.setenv("WEBSHARE_API_KEY", "test-key")
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@rotate.webshare.io:80"])
        monkeypatch.setattr(scraper_engine, "_fetch_proxies_from_api", boom)
        s = make_spider([])
        assert s._build_asn_candidates() == ["http://u:p@rotate.webshare.io:80"]

    def test_rotating_endpoint_only_single_candidate(self, make_spider, monkeypatch):
        self._clear_webshare_env(monkeypatch)
        monkeypatch.setenv("WEBSHARE_PROXY_URL", "http://u:p@rotate.webshare.io:80")
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@rotate.webshare.io:80"])
        s = make_spider([])
        assert s._build_asn_candidates() == ["http://u:p@rotate.webshare.io:80"]

    def test_credentialless_proxy_urls_kept(self, make_spider, monkeypatch):
        pool = ["http://10.0.0.1:8080", "http://10.0.0.2:8080", "10.0.0.3:8080"]
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", pool)
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        assert s._build_asn_candidates() == pool

    def test_aborted_loop_does_not_mark_flag(self, make_spider, isolated_counter, monkeypatch):
        class RotatorBoom:
            def get_proxy(self):
                raise RuntimeError("rotator failure")

        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", self.PROXIES)
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", lambda proxies: RotatorBoom())
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        anyio.run(s._run_asn_test)
        assert s._jd_stats["asn_attempted"] == 0
        flag = isolated_counter.exists() and '"__jd_asn_test": 1' in isolated_counter.read_text()
        assert not flag

    def test_candidates_cap_at_ten(self, make_spider, monkeypatch):
        pool = [f"http://u:p@10.0.0.{i}:80" for i in range(1, 15)]
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", pool)
        self._clear_webshare_env(monkeypatch)
        s = make_spider([])
        assert len(s._build_asn_candidates()) == ASN_PROBE_MAX


class TestAsnDatacenterMode:
    """FR-003/FR-009 — probe only, zero crawl requests, persisted once-daily gate."""

    def test_datacenter_probe_runs_and_zero_crawl(self, make_spider, isolated_counter, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        s = make_spider([TestStartRequests.JD])
        s._session_manager = _StubSessionManager([(200, b"x" * 600)])
        reqs = _collect(s)
        assert reqs == []
        assert s._jd_stats["asn_attempted"] == 1
        assert s._jd_stats["asn_succeeded"] == 1
        assert '"__jd_asn_test": 1' in isolated_counter.read_text()

    def test_second_run_same_day_skips_probe(self, make_spider, isolated_counter, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)

        s1 = make_spider([TestStartRequests.JD])
        s1._session_manager = _StubSessionManager([(200, b"x" * 600)])
        assert _collect(s1) == []
        assert s1._jd_stats.get("asn_attempted") == 1

        calls = []

        async def spy(self, timeout=30000):
            calls.append(1)

        monkeypatch.setattr(spider_mod.LeadSpider, "_run_asn_test", spy)
        s2 = make_spider([TestStartRequests.JD])
        assert _collect(s2) == []
        assert calls == []

    def test_on_start_logs_display_label(self, make_spider, monkeypatch, caplog):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        s = make_spider([])
        with caplog.at_level(logging.INFO, logger="src.scraper.spider"):
            anyio.run(s.on_start, False)
        mode_lines = [ln.rstrip() for ln in caplog.text.splitlines() if "JustDial mode:" in ln]
        assert any(ln.endswith("JustDial mode: datacenter-ASN-test") for ln in mode_lines)
        assert not any(ln.endswith("JustDial mode: datacenter") for ln in mode_lines)

    def test_resume_probes_when_not_tested(self, make_spider, isolated_counter, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        s = make_spider([TestStartRequests.JD])
        s._session_manager = _StubSessionManager([(200, b"x" * 600)])
        anyio.run(s.on_start, True)
        assert s._jd_stats["asn_attempted"] == 1
        assert s._jd_stats["asn_succeeded"] == 1
        assert '"__jd_asn_test": 1' in isolated_counter.read_text()

    def test_resume_skips_probe_when_tested(self, make_spider, isolated_counter, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)

        s1 = make_spider([TestStartRequests.JD])
        s1._session_manager = _StubSessionManager([(200, b"x" * 600)])
        assert _collect(s1) == []
        assert s1._jd_stats.get("asn_attempted") == 1

        calls = []

        async def spy(self, timeout=90000, page_delay=2.0):
            calls.append(1)

        monkeypatch.setattr(spider_mod.LeadSpider, "_run_asn_test", spy)
        s2 = make_spider([TestStartRequests.JD])
        anyio.run(s2.on_start, True)
        assert calls == []

    def test_resume_skips_probe_when_jd_disabled(self, make_spider, isolated_counter, monkeypatch):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)

        calls = []

        async def spy(self, timeout=90000, page_delay=2.0):
            calls.append(1)

        monkeypatch.setattr(spider_mod.LeadSpider, "_run_asn_test", spy)
        jd_off = {**TestStartRequests.JD, "enabled": False}
        s = make_spider([jd_off])
        anyio.run(s.on_start, True)
        assert calls == []


class TestSummaryLines:
    """T015-T018 — exact verdict/CONCLUSION/mode strings, no_proxy warning names vars."""

    def _close(self, s, caplog):
        with caplog.at_level(logging.INFO, logger="src.scraper.spider"):
            anyio.run(s.on_close)

    def test_justdial_summary_all_blocked_fires_conclusion(self, make_spider, isolated_counter, monkeypatch, caplog):
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", ["http://u:p@1.1.1.1:80"])
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        s = make_spider([])
        s._jd_mode = "datacenter"
        s._session_manager = _StubSessionManager([(200, b"x" * 100)])
        anyio.run(s._run_asn_test)
        self._close(s, caplog)
        assert "JustDial: 1/10 distinct proxy IPs attempted, 1 blocked (body<500B), 0 succeeded." in caplog.text
        assert ASN_CONCLUSION in caplog.text
        assert "JustDial mode: datacenter-ASN-test" in caplog.text

    def test_justdial_summary_partial_success_no_conclusion(self, make_spider, isolated_counter, monkeypatch, caplog):
        monkeypatch.setattr(
            scraper_engine, "_PROXY_POOL",
            ["http://u:p@1.1.1.1:80", "http://u:p@2.2.2.2:80"],
        )
        monkeypatch.setattr("scrapling.fetchers.ProxyRotator", _FakeRotator)
        s = make_spider([])
        s._jd_mode = "datacenter"
        s._session_manager = _StubSessionManager([(200, b"x" * 100), (200, b"y" * 600)])
        anyio.run(s._run_asn_test)
        self._close(s, caplog)
        assert "JustDial: 2/10 distinct proxy IPs attempted, 1 blocked (body<500B), 1 succeeded." in caplog.text
        assert ASN_CONCLUSION not in caplog.text

    def test_justdial_summary_no_proxy_warning_names_vars(self, make_spider, monkeypatch, caplog):
        monkeypatch.delenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", raising=False)
        monkeypatch.setattr(scraper_engine, "_PROXY_POOL", [])
        monkeypatch.delenv("WEBSHARE_PROXY_URL", raising=False)
        monkeypatch.delenv("WEBSHARE_PROXY_LIST", raising=False)
        monkeypatch.delenv("WEBSHARE_API_KEY", raising=False)
        s = make_spider([TestStartRequests.JD])
        _collect(s)
        assert any(e.error_type == "ProxyNotConfigured" for e in s.scrape_errors)
        for var in ("RESIDENTIAL_PROXY_URL_JUSTDIAL", "WEBSHARE_PROXY_URL", "WEBSHARE_PROXY_LIST", "WEBSHARE_API_KEY"):
            assert var in caplog.text

    def test_justdial_summary_mode_label_residential(self, make_spider, caplog):
        s = make_spider([])
        s._jd_mode = "residential"
        self._close(s, caplog)
        assert "JustDial mode: residential" in caplog.text

    def test_justdial_summary_mode_label_no_proxy(self, make_spider, caplog):
        s = make_spider([])
        s._jd_mode = "no_proxy"
        self._close(s, caplog)
        assert "JustDial mode: no_proxy" in caplog.text

    def test_summary_reports_cap_reached_and_early_stopped(self, make_spider, caplog):
        """FR-008 — run summary logs cap-reached and early-stopped targets."""
        s = make_spider([])
        s._cap_reached.add("dir.indiamart.com")
        s._early_stopped_targets[("indiamart", "software-development", "new-delhi")] = "0_new"
        self._close(s, caplog)
        assert "Daily cap reached for domain(s): dir.indiamart.com" in caplog.text
        assert "Early-stopped targets (1)" in caplog.text
        assert "indiamart/software-development/new-delhi" in caplog.text

    def test_summary_reports_budget_used_per_domain(self, small_config, isolated_counter, monkeypatch, caplog):
        """FR-008 — summary logs budget units consumed per domain (snapshot, no internal keys)."""
        monkeypatch.setattr("scrapling.fetchers.FetcherSession", MagicMock)
        monkeypatch.setattr("scrapling.fetchers.AsyncStealthySession", MagicMock)
        s = spider_mod.LeadSpider([TestStartRequests.TI])
        s._req_counter.allowed("www.tradeindia.com", 100)
        s._req_counter.allowed("dir.indiamart.com", 40)
        self._close(s, caplog)
        assert "Daily request budget used per domain:" in caplog.text
        assert "www.tradeindia.com=1" in caplog.text
        assert "dir.indiamart.com=1" in caplog.text
        assert "__jd_asn_test" not in caplog.text  # internal marker filtered

    def test_justdial_summary_residential_conclusion_wording(self, make_spider, isolated_counter, monkeypatch, caplog):
        s = make_spider([])
        s._jd_mode = "residential"
        s._jd_stats["blocked_ips"] = {"1.2.3.4:8080"}
        s._jd_stats["blocked"] = 2
        self._close(s, caplog)
        assert ASN_CONCLUSION in caplog.text
        assert "Residential proxy tier required." not in caplog.text


class TestResidentialDepth:
    """SC-001/FR-002/SC-005 — JD eager depth equals IM/TI configured max_pages (lazy)."""

    def test_jd_eager_pages_equal_im_ti_max_pages(self, make_spider, monkeypatch, proxy_pool):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        cfg = dict(TestStartRequests.JD)
        cfg["pages"] = 3
        im = dict(TestStartRequests.IM)
        im["max_pages"] = 3
        ti = dict(TestStartRequests.TI)
        ti["max_pages"] = 3
        s = make_spider([cfg, im, ti])
        reqs = _collect(s)
        jd = [r for r in reqs if r.sid == SID_JUSTDIAL]
        im_reqs = [r for r in reqs if r.sid == SID_INDIAMART]
        ti_reqs = [r for r in reqs if r.sid == SID_TRADEINDIA]
        # JD yields all `pages` eagerly (unchanged); IM/TI yield page 1 only (lazy).
        assert len(jd) == 3
        assert len(im_reqs) == 1
        assert len(ti_reqs) == 1
        assert im_reqs[0].meta["pages_total"] == 3
        assert ti_reqs[0].meta["pages_total"] == 3
        assert all(r._session_kwargs["proxy"] == "http://user:pass@residential.example:3128" for r in jd)


class TestParseDispatch:
    """T006/T030-T036 — parse callback: dispatch, RawRecord tagging, fill rates, JD stats."""

    @staticmethod
    def _make_response(meta):
        html = b"<html>lead page</html>"
        resp = MagicMock()
        resp.status = 200
        resp.body = html
        resp.html_content = html
        resp.text = html.decode("utf-8", errors="replace")
        resp.meta = meta
        resp.url = "https://www.justdial.com/city/cat"
        return resp

    @staticmethod
    def _collect(s, response):
        async def run():
            out = []
            async for item in s.parse(response):
                out.append(item)
            return out

        return anyio.run(run)

    def _jd_meta(self, **over):
        meta = {
            "parser": "parse_test",
            "source_url": "https://www.justdial.com/src",
            "site_name": "Justdial",
            "category_slug": "it-services",
            "city_slug": "delhi",
            "page": 1,
            "pages_total": 1,
        }
        meta.update(over)
        return meta

    def test_dispatches_to_registered_parser_and_yields_dicts(self, make_spider, monkeypatch):
        s = make_spider([])
        seen = {}

        def fake_parser(response, source_url=""):
            seen["source_url"] = source_url
            return [RawRecord(company_name="Acme", phone="123", email="a@b.com")]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_test", fake_parser)
        items = self._collect(s, self._make_response(self._jd_meta()))

        assert seen["source_url"] == "https://www.justdial.com/src"
        assert len(items) == 1
        assert items[0]["company_name"] == "Acme"
        assert items[0]["category_slug"] == "it-services"
        assert items[0]["city_slug"] == "delhi"
        assert items[0]["source_url"] == "https://www.justdial.com/src"
        assert len(s.all_records) == 1
        assert s._jd_stats["succeeded"] == 1
        assert s._fill_rates["Justdial"] == {"total": 1, "phone": 1, "email": 1, "website": 0}
        assert s._bytes_fetched.get("parse_test", 0) > 0

    def test_source_url_falls_back_when_record_lacks_one(self, make_spider, monkeypatch):
        s = make_spider([])

        def fake_parser(response, source_url=""):
            return [
                RawRecord(company_name="A"),
                RawRecord(company_name="B", source_url="https://rec-b"),
            ]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_test", fake_parser)
        items = self._collect(s, self._make_response(self._jd_meta()))
        assert items[0]["source_url"] == "https://www.justdial.com/src"
        assert items[1]["source_url"] == "https://rec-b"
        assert s.all_records[0].source_url == "https://www.justdial.com/src"
        assert s.all_records[1].source_url == "https://rec-b"

    def test_unknown_parser_records_error_without_crash(self, make_spider):
        s = make_spider([])
        items = self._collect(s, self._make_response(self._jd_meta(parser="parse_missing")))
        assert items == []
        assert any(e.error_type == "UnknownParser" for e in s.scrape_errors)

    def test_empty_records_yield_nothing(self, make_spider, monkeypatch):
        s = make_spider([])

        def fake_parser(response, source_url=""):
            return []

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_test", fake_parser)
        items = self._collect(s, self._make_response(self._jd_meta()))
        assert items == []
        assert s._fill_rates == {}
        assert s._jd_stats["succeeded"] == 0

    def test_fill_rates_count_partial_contact_fields(self, make_spider, monkeypatch):
        s = make_spider([])

        def fake_parser(response, source_url=""):
            return [
                RawRecord(company_name="A", phone="1"),
                RawRecord(company_name="B", email="b@x.com"),
                RawRecord(company_name="C", website="https://c"),
            ]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_test", fake_parser)
        self._collect(s, self._make_response(self._jd_meta(site_name="TradeIndia")))
        assert s._fill_rates["TradeIndia"] == {"total": 3, "phone": 1, "email": 1, "website": 1}
        assert s._jd_stats["succeeded"] == 0

    def test_detail_urls_captured_for_enrichment(self, make_spider, monkeypatch):
        s = make_spider([])

        def fake_parser(response, source_url=""):
            return [RawRecord(company_name="A", phone="1")]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_enrich", fake_parser)
        monkeypatch.setattr(
            spider_mod, "_extract_detail_urls",
            lambda parser_name, response, tagged, base_idx: [(0, "https://detail.tradeindia.com/x")],
        )
        self._collect(s, self._make_response(self._jd_meta(parser="parse_enrich", fetch_kwargs={"timeout": 90000})))

        assert len(s._enrich_data) == 1
        entry = s._enrich_data[0]
        assert entry["parser"] == "parse_enrich"
        assert entry["detail_urls"] == [(0, "https://detail.tradeindia.com/x")]
        assert entry["source_url"] == "https://www.justdial.com/src"
        assert entry["records"][0].company_name == "A"

    def test_jd_succeeded_increments_only_for_justdial(self, make_spider, monkeypatch):
        s = make_spider([])

        def fake_parser(response, source_url=""):
            return [RawRecord(company_name="A")]

        monkeypatch.setitem(spider_mod.PARSER_REGISTRY, "parse_test", fake_parser)
        self._collect(s, self._make_response(self._jd_meta(site_name="IndiaMART")))
        assert s._jd_stats["succeeded"] == 0
        self._collect(s, self._make_response(self._jd_meta(site_name="justdial")))
        assert s._jd_stats["succeeded"] == 1
