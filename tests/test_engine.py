import os
from unittest.mock import patch, MagicMock

import pytest

from src.scraper import engine as scraper_engine
from src.scraper.targets import RawRecord


class TestScrapeAllTargets:
    def test_empty_config_returns_empty(self):
        records, errors = scraper_engine.scrape_all_targets([])
        assert records == []
        assert errors == []

    def test_loads_default_config_when_none(self):
        mock_config = [{"entry_url": "https://example.com", "parser": "test"}]

        with patch.object(scraper_engine, "load_targets_config", return_value=mock_config):
            with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
                with patch.object(scraper_engine, "scrape_target", return_value=[]):
                    records, errors = scraper_engine.scrape_all_targets()
                    assert records == []
                    assert errors == []

    def test_aggregates_records_from_all_targets(self):
        config = [
            {"entry_url": "https://site1.com", "parser": "p1"},
            {"entry_url": "https://site2.com", "parser": "p2"},
        ]

        with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
            with patch.object(
                scraper_engine,
                "scrape_target",
                side_effect=[
                    [RawRecord(company_name="Company A")],
                    [RawRecord(company_name="Company B"), RawRecord(company_name="Company C")],
                ],
            ):
                records, errors = scraper_engine.scrape_all_targets(config)

        assert len(records) == 3
        assert records[0].company_name == "Company A"
        assert records[1].company_name == "Company B"
        assert records[2].company_name == "Company C"
        assert errors == []

    def test_captures_errors_per_target(self):
        config = [
            {"entry_url": "https://site1.com", "parser": "p1"},
            {"entry_url": "https://site2.com", "parser": "p2"},
        ]

        with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
            with patch.object(
                scraper_engine,
                "scrape_target",
                side_effect=[
                    [RawRecord(company_name="Company A")],
                    ValueError("Connection refused"),
                ],
            ):
                records, errors = scraper_engine.scrape_all_targets(config)

        assert len(records) == 1
        assert len(errors) == 1
        assert errors[0].url == "https://site2.com"
        assert errors[0].error_type == "ValueError"

    def test_skips_when_robots_disallows(self):
        config = [
            {"entry_url": "https://site1.com", "parser": "p1"},
            {"entry_url": "https://site2.com", "parser": "p2"},
        ]

        def robots_check(url, **kwargs):
            return url != "https://site2.com"

        with patch.object(scraper_engine, "is_robots_allowed", side_effect=robots_check):
            with patch.object(scraper_engine, "scrape_target", return_value=[RawRecord(company_name="Company A")]):
                records, errors = scraper_engine.scrape_all_targets(config)

        assert len(records) == 1
        assert len(errors) == 1
        assert errors[0].url == "https://site2.com"
        assert errors[0].error_type == "RobotsDisallowed"

    def test_continues_after_target_failure(self):
        config = [
            {"entry_url": "https://site1.com", "parser": "p1"},
            {"entry_url": "https://site2.com", "parser": "p2"},
            {"entry_url": "https://site3.com", "parser": "p3"},
        ]

        with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
            with patch.object(
                scraper_engine,
                "scrape_target",
                side_effect=[
                    [RawRecord(company_name="Company A")],
                    RuntimeError("fail"),
                    [RawRecord(company_name="Company C")],
                ],
            ):
                records, errors = scraper_engine.scrape_all_targets(config)

        assert len(records) == 2
        assert len(errors) == 1
        assert errors[0].url == "https://site2.com"

    def test_logs_scrape_progress(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        config = [
            {"entry_url": "https://site1.com", "parser": "p1"},
            {"entry_url": "https://site2.com", "parser": "p2"},
        ]
        with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
            with patch.object(
                scraper_engine,
                "scrape_target",
                side_effect=[
                    [RawRecord(company_name="A")],
                    [RawRecord(company_name="B"), RawRecord(company_name="C")],
                ],
            ):
                scraper_engine.scrape_all_targets(config)

        info_messages = [r.message for r in caplog.records if r.levelname == "INFO"]
        assert any("Scraping target: https://site1.com" in msg for msg in info_messages)
        assert any("Scraped 1 records from https://site1.com" in msg for msg in info_messages)
        assert any("Scraping target: https://site2.com" in msg for msg in info_messages)
        assert any("Scraped 2 records from https://site2.com" in msg for msg in info_messages)
        assert any("Scrape complete: 3 total records" in msg for msg in info_messages)

    def test_logs_robots_disallow_warning(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        config = [{"entry_url": "https://blocked.com", "parser": "p1"}]
        with patch.object(scraper_engine, "is_robots_allowed", return_value=False):
            with patch.object(scraper_engine, "scrape_target"):
                scraper_engine.scrape_all_targets(config)
        warning_messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("Robots.txt disallows" in msg for msg in warning_messages)

    def test_logs_failure_warning(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        config = [{"entry_url": "https://fail.com", "parser": "p1"}]
        with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
            with patch.object(scraper_engine, "scrape_target", side_effect=RuntimeError("fail")):
                scraper_engine.scrape_all_targets(config)
        warning_messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("Failed to scrape https://fail.com" in msg for msg in warning_messages)


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
        with patch.object(scraper_engine, "_init_proxy_pool"):
            with patch.object(scraper_engine, "_PROXY_POOL", []):
                records, errors = scraper_engine.scrape_all_targets(config)
        assert records == []
        assert any(e.error_type == "ProxyNotConfigured" for e in errors)

    def test_skips_indiamart_when_no_proxy(self):
        config = [{"name": "IndiaMART", "entry_url": "https://indiamart.com", "parser": "p1"}]
        with patch.object(scraper_engine, "_init_proxy_pool"):
            with patch.object(scraper_engine, "_PROXY_POOL", []):
                records, errors = scraper_engine.scrape_all_targets(config)
        assert records == []
        assert any(e.error_type == "ProxyNotConfigured" for e in errors)

    def test_does_not_skip_tradeindia_when_no_proxy(self):
        config = [{"name": "TradeIndia", "entry_url": "https://tradeindia.com", "parser": "p1"}]
        with patch.object(scraper_engine, "_init_proxy_pool"):
            with patch.object(scraper_engine, "_PROXY_POOL", []):
                with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
                    with patch.object(scraper_engine, "scrape_target", return_value=[]):
                        records, errors = scraper_engine.scrape_all_targets(config)
        assert errors == []

    def test_injects_proxy_into_fetch_kwargs(self):
        config = [{"name": "Justdial", "entry_url": "https://justdial.com", "parser": "p1", "fetch_kwargs": {}}]
        with patch.object(scraper_engine, "_get_next_proxy", return_value="http://proxy:80"):
            with patch.object(scraper_engine, "is_robots_allowed", return_value=True):
                with patch.object(scraper_engine, "scrape_target", return_value=[]):
                    scraper_engine.scrape_all_targets(config)
        assert config[0]["fetch_kwargs"]["proxy"] == "http://proxy:80"
