"""Unit tests for LeadSpider: kwarg factories, throttling, block detection, retry, and start_requests routing."""

import anyio
import pytest
from unittest.mock import MagicMock

from scrapling.spiders.request import Request

from src.scraper import engine as scraper_engine
from src.scraper import spider as spider_mod
from src.scraper.spider import (
    DOMAIN_DELAYS,
    SID_INDIAMART,
    SID_JUSTDIAL,
    SID_TRADEINDIA,
    LeadSpider,
    _SESSION_KWARG_FACTORIES,
    _make_session_kwargs,
)


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


def _collect(spider):
    async def run():
        reqs = []
        async for req in spider.start_requests():
            reqs.append(req)
        return reqs

    return anyio.run(run)


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

    def test_stealth_request_has_proxy_and_wait(self, make_spider, proxy_pool):
        s = make_spider([self.JD])
        reqs = _collect(s)
        assert len(reqs) == 1
        assert reqs[0].sid == SID_JUSTDIAL
        kw = reqs[0]._session_kwargs
        assert kw["proxy"] == "http://user:pass@1.2.3.4:8080"
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

    def test_wait_selector_only_on_first_page(self, make_spider, proxy_pool, monkeypatch):
        monkeypatch.setenv("SCRAPE_FULL_PAGES", "true")
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
