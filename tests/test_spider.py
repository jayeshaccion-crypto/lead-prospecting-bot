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
        "expansion": {
            "categories": [{
                "slug": "it-services",
                "labels": {
                    "justdial": "IT-Services",
                    "indiamart": "software-development-services",
                    "tradeindia": "IT-Services",
                },
            }],
            "cities": [{"slug": "delhi", "labels": {"justdial": "Delhi", "indiamart": "new-delhi"}}],
        },
        "url_templates": {
            "justdial": "https://www.justdial.com/{city}/{category}/nct-10278073",
            "indiamart": "https://dir.indiamart.com/{city}/{category}.html",
            "tradeindia": "https://www.tradeindia.com/manufacturers/{category}.html",
        },
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
        monkeypatch.setenv("SCRAPE_FULL_PAGES", "true")
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

    def test_justdial_summary_residential_conclusion_wording(self, make_spider, isolated_counter, monkeypatch, caplog):
        s = make_spider([])
        s._jd_mode = "residential"
        s._jd_stats["blocked_ips"] = {"1.2.3.4:8080"}
        s._jd_stats["blocked"] = 2
        self._close(s, caplog)
        assert ASN_CONCLUSION in caplog.text
        assert "Residential proxy tier required." not in caplog.text


class TestResidentialDepth:
    """SC-001/FR-002 — JD crawl depth equals IndiaMart/TradeIndia at full pages."""

    def test_full_depth_equals_other_directories(self, make_spider, monkeypatch, proxy_pool):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL_JUSTDIAL", "http://user:pass@residential.example:3128")
        monkeypatch.setenv("SCRAPE_FULL_PAGES", "true")
        cfg = dict(TestStartRequests.JD)
        cfg["pages"] = 2
        im = dict(TestStartRequests.IM)
        im["pages"] = 2
        ti = dict(TestStartRequests.TI)
        ti["pages"] = 2
        s = make_spider([cfg, im, ti])
        reqs = _collect(s)
        jd = [r for r in reqs if r.sid == SID_JUSTDIAL]
        im_reqs = [r for r in reqs if r.sid == SID_INDIAMART]
        ti_reqs = [r for r in reqs if r.sid == SID_TRADEINDIA]
        assert len(jd) == len(im_reqs) == len(ti_reqs) == 2
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
