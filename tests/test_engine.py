from unittest.mock import patch, MagicMock

import pytest

from src.scraper import engine as scraper_engine
from src.scraper.targets import RawRecord


class TestCreateFetcher:
    def test_returns_stealthy_fetcher(self):
        with patch.object(scraper_engine, "StealthyFetcher") as mock_fetcher:
            result = scraper_engine.create_fetcher()

        mock_fetcher.configure.assert_called_once_with(adaptive=True)
        assert result is mock_fetcher


class TestFetchWithRetry:
    def test_fetches_url(self):
        mock_fetcher_class = MagicMock()

        with patch.object(scraper_engine, "StealthyFetcher", mock_fetcher_class):
            scraper_engine.fetch_with_retry("https://example.com", timeout=30000)

        mock_fetcher_class.fetch.assert_called_once_with("https://example.com", timeout=30000)

    def test_uses_default_timeout(self):
        mock_fetcher_class = MagicMock()

        with patch.object(scraper_engine, "StealthyFetcher", mock_fetcher_class):
            scraper_engine.fetch_with_retry("https://example.com")

        mock_fetcher_class.fetch.assert_called_once_with("https://example.com", timeout=30000)

    def test_no_robots_txt_obey_in_kwargs(self):
        mock_fetcher_class = MagicMock()

        with patch.object(scraper_engine, "StealthyFetcher", mock_fetcher_class):
            scraper_engine.fetch_with_retry("https://example.com")

        call_kwargs = mock_fetcher_class.fetch.call_args.kwargs
        assert "robots_txt_obey" not in call_kwargs


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
