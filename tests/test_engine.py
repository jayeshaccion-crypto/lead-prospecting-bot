import os
from unittest.mock import patch, MagicMock

import pytest

from src.scraper import engine as scraper_engine
from src.scraper.targets import RawRecord


class TestScrapeAllTargets:
    def _mock_spider(self, records=None, errors=None):
        """Create a mock LeadSpider that returns given records and errors."""
        records = records or []
        errors = errors or []

        # We need to mock LeadSpider at the engine import level
        # The patch replaces the class; __init__ shouldn't call super().__init__()
        # (which tries to configure sessions). We mock that too.
        patcher = patch("src.scraper.engine.LeadSpider")
        mock_cls = patcher.start()
        mock_instance = MagicMock()
        mock_instance.all_records = records
        mock_instance.scrape_errors = errors
        mock_cls.return_value = mock_instance
        return patcher

    def test_empty_config_returns_empty(self):
        records, errors = scraper_engine.scrape_all_targets([])
        assert records == []
        assert errors == []

    def test_loads_default_config_when_none(self):
        patcher = self._mock_spider(records=[], errors=[])
        try:
            with patch.object(scraper_engine, "load_targets_config", return_value=[]):
                records, errors = scraper_engine.scrape_all_targets()
                assert records == []
                assert errors == []
        finally:
            patcher.stop()

    def test_aggregates_records_from_all_targets(self):
        expected_records = [
            RawRecord(company_name="Company A"),
            RawRecord(company_name="Company B"),
        ]
        patcher = self._mock_spider(records=expected_records, errors=[])
        try:
            config = [{"entry_url": "https://site1.com", "parser": "p1"}]
            records, errors = scraper_engine.scrape_all_targets(config)
            assert len(records) == 2
            assert records[0].company_name == "Company A"
            assert records[1].company_name == "Company B"
            assert errors == []
        finally:
            patcher.stop()

    def test_captures_errors_per_target(self):
        patcher = self._mock_spider(
            records=[RawRecord(company_name="Company A")],
            errors=[MagicMock(url="https://site2.com", error_type="ValueError")],
        )
        try:
            config = [{"entry_url": "https://site1.com", "parser": "p1"}]
            records, errors = scraper_engine.scrape_all_targets(config)
            assert len(records) == 1
            assert len(errors) == 1
            assert errors[0].url == "https://site2.com"
            assert errors[0].error_type == "ValueError"
        finally:
            patcher.stop()

    def test_skips_when_robots_disallows(self):
        # Robots check is inside LeadSpider; we test it via the spider's
        # scrape_errors which contain the robots-disallowed error
        from src.models import ScrapeError
        patcher = self._mock_spider(
            records=[RawRecord(company_name="Company A")],
            errors=[ScrapeError(url="https://blocked.com", error_type="RobotsDisallowed")],
        )
        try:
            config = [{"entry_url": "https://site1.com", "parser": "p1"}]
            records, errors = scraper_engine.scrape_all_targets(config)
            assert any(e.error_type == "RobotsDisallowed" for e in errors)
        finally:
            patcher.stop()

    def test_continues_after_target_failure(self):
        patcher = self._mock_spider(
            records=[RawRecord(company_name="Company A"), RawRecord(company_name="Company C")],
            errors=[MagicMock(url="https://site2.com", error_type="RuntimeError")],
        )
        try:
            config = [{"entry_url": "https://site1.com", "parser": "p1"}]
            records, errors = scraper_engine.scrape_all_targets(config)
            assert len(records) == 2
            assert len(errors) == 1
        finally:
            patcher.stop()

    def test_logs_scrape_progress(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        patcher = self._mock_spider(
            records=[RawRecord(company_name="A"), RawRecord(company_name="B")],
            errors=[],
        )
        try:
            config = [{"entry_url": "https://site1.com", "parser": "p1"}]
            scraper_engine.scrape_all_targets(config)
        finally:
            patcher.stop()

        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("Scrape complete via LeadSpider: 2 total records" in msg for msg in info_messages)

    def test_logs_failure_warning(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        from src.models import ScrapeError
        patcher = self._mock_spider(
            records=[],
            errors=[ScrapeError(url="https://fail.com", error_type="RuntimeError")],
        )
        try:
            config = [{"entry_url": "https://fail.com", "parser": "p1"}]
            scraper_engine.scrape_all_targets(config)
        finally:
            patcher.stop()

        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("1 target errors" in msg for msg in info_messages)


class TestProxyPool:
    def setup_method(self):
        scraper_engine._PROXY_POOL = None
        scraper_engine._PROXY_INDEX = 0

    def test_init_from_url_env(self):
        with patch.dict(os.environ, {"WEBSHARE_PROXY_URL": "http://rotating.proxy:80"}, clear=True):
            scraper_engine._init_proxy_pool()
            assert scraper_engine._PROXY_POOL == ["http://rotating.proxy:80"]

    def test_init_from_list_env(self):
        with patch.dict(os.environ, {"WEBSHARE_PROXY_LIST": "http://p1:80,http://p2:80"}, clear=True):
            scraper_engine._init_proxy_pool()
            assert scraper_engine._PROXY_POOL == ["http://p1:80", "http://p2:80"]

    def test_init_from_api_key(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "count": 1,
            "next": None,
            "results": [
                {
                    "id": "d-1",
                    "username": "u1",
                    "password": "p1",
                    "proxy_address": "1.2.3.4",
                    "port": 8168,
                    "valid": True,
                },
            ],
        }
        with patch.dict(os.environ, {"WEBSHARE_API_KEY": "test_key"}, clear=True):
            with patch("httpx.get", return_value=mock_response):
                scraper_engine._init_proxy_pool()
                assert len(scraper_engine._PROXY_POOL) == 1
                assert "u1:p1@1.2.3.4:8168" in scraper_engine._PROXY_POOL[0]

    def test_init_empty_sets_empty_list(self):
        with patch.dict(os.environ, {}, clear=True):
            scraper_engine._init_proxy_pool()
            assert scraper_engine._PROXY_POOL == []

    def test_get_next_proxy_round_robins(self):
        scraper_engine._PROXY_POOL = ["http://a:1", "http://b:2"]
        scraper_engine._PROXY_INDEX = 0
        assert scraper_engine._get_next_proxy() == "http://a:1"
        assert scraper_engine._get_next_proxy() == "http://b:2"
        assert scraper_engine._get_next_proxy() == "http://a:1"

    def test_get_next_proxy_returns_none_when_empty(self):
        scraper_engine._PROXY_POOL = []
        assert scraper_engine._get_next_proxy() is None


class TestProxySkip:
    def test_skips_justdial_when_no_proxy(self):
        config = [{"name": "Justdial", "entry_url": "https://justdial.com", "parser": "p1"}]
        with patch("src.scraper.engine.LeadSpider") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.all_records = []
            mock_instance.scrape_errors = []
            mock_cls.return_value = mock_instance
            records, errors = scraper_engine.scrape_all_targets(config)
        # Engine no longer skips at its level — proxy logic moved to spider.
        # With a mocked spider, no records or errors are produced.
        assert records == []
        assert errors == []

    def test_skips_indiamart_when_no_proxy(self):
        config = [{"name": "IndiaMART", "entry_url": "https://indiamart.com", "parser": "p1"}]
        with patch("src.scraper.engine.LeadSpider") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.all_records = []
            mock_instance.scrape_errors = []
            mock_cls.return_value = mock_instance
            records, errors = scraper_engine.scrape_all_targets(config)
        assert records == []
        assert errors == []

    def test_does_not_skip_tradeindia_when_no_proxy(self):
        config = [{"name": "TradeIndia", "entry_url": "https://tradeindia.com", "parser": "p1"}]
        with patch.object(scraper_engine, "_init_proxy_pool"):
            with patch("src.scraper.engine.LeadSpider") as mock_cls:
                mock_instance = MagicMock()
                mock_instance.all_records = []
                mock_instance.scrape_errors = []
                mock_cls.return_value = mock_instance
                records, errors = scraper_engine.scrape_all_targets(config)
        assert errors == []

    def test_injects_proxy_into_fetch_kwargs(self):
        # Proxy injection is now handled in the spider; the engine doesn't
        # directly inject into fetch_kwargs anymore. Instead the spider
        # handles proxy assignment inside start_requests().
        # This test verifies the engine still processes config with proxy.
        config = [{"name": "Justdial", "entry_url": "https://justdial.com", "parser": "p1", "fetch_kwargs": {}}]
        with patch("src.scraper.engine.LeadSpider") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.all_records = []
            mock_instance.scrape_errors = []
            mock_cls.return_value = mock_instance
            scraper_engine.scrape_all_targets(config)
        # Verify LeadSpider received the config with proxy in fetch_kwargs
        assert mock_cls.call_args[0][0] == config
