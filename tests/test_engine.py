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
