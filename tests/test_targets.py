from unittest.mock import patch, MagicMock

import pytest

from src.scraper.engine import fetch_with_retry
from src.scraper.targets import (
    RawRecord,
    register_parser,
    PARSER_REGISTRY,
    scrape_target,
    parse_example_directory,
)


class TestRawRecord:
    def test_creates_with_minimal_fields(self):
        record = RawRecord(company_name="Acme Corp")
        assert record.company_name == "Acme Corp"
        assert record.website is None
        assert record.email is None
        assert record.phone is None
        assert record.address is None
        assert record.industry_code is None
        assert record.source_url is None

    def test_creates_with_all_fields(self):
        record = RawRecord(
            company_name="Acme Corp",
            website="https://acme.com",
            email="contact@acme.com",
            phone="+1-555-0100",
            address="123 Main St",
            industry_code="Software",
            source_url="https://dir.example.com",
        )
        assert record.company_name == "Acme Corp"
        assert record.website == "https://acme.com"
        assert record.source_url == "https://dir.example.com"


class TestRegisterParser:
    def test_registers_function(self):
        PARSER_REGISTRY.clear()

        @register_parser("test_parser")
        def dummy_parser(response, source_url=""):
            return []

        assert "test_parser" in PARSER_REGISTRY
        assert PARSER_REGISTRY["test_parser"] is dummy_parser

    def test_multiple_parsers(self):
        PARSER_REGISTRY.clear()

        @register_parser("parser_a")
        def parser_a(response, source_url=""):
            return []

        @register_parser("parser_b")
        def parser_b(response, source_url=""):
            return []

        assert len(PARSER_REGISTRY) == 2
        PARSER_REGISTRY.clear()


class TestScrapeTarget:
    def test_unknown_parser_raises_value_error(self):
        PARSER_REGISTRY.clear()

        config = {"entry_url": "https://example.com", "parser": "nonexistent"}
        with pytest.raises(ValueError, match="Unknown parser: nonexistent"):
            scrape_target(config)

    def test_calls_fetch_with_retry_and_parser(self):
        PARSER_REGISTRY.clear()

        @register_parser("test_parser")
        def dummy_parser(response, source_url=""):
            return [RawRecord(company_name="Test Co", source_url=source_url)]

        config = {"entry_url": "https://dir.example.com", "parser": "test_parser"}
        mock_response = MagicMock()

        with patch("src.scraper.engine.fetch_with_retry", return_value=mock_response) as mock_fetch:
            records = scrape_target(config)

        mock_fetch.assert_called_once_with("https://dir.example.com", timeout=30000)
        assert len(records) == 1
        assert records[0].company_name == "Test Co"
        assert records[0].source_url == "https://dir.example.com"

    def test_passes_custom_timeout(self):
        PARSER_REGISTRY.clear()

        @register_parser("test_parser")
        def dummy_parser(response, source_url=""):
            return []

        config = {
            "entry_url": "https://dir.example.com",
            "parser": "test_parser",
            "fetch_kwargs": {"timeout": 60000},
        }

        with patch("src.scraper.engine.fetch_with_retry") as mock_fetch:
            scrape_target(config)

        mock_fetch.assert_called_once_with("https://dir.example.com", timeout=60000)

    def test_parser_receives_response(self):
        PARSER_REGISTRY.clear()
        captured = []

        @register_parser("capture_parser")
        def capture_parser(response, source_url=""):
            captured.append((response, source_url))
            return []

        config = {"entry_url": "https://dir.example.com", "parser": "capture_parser"}
        mock_response = MagicMock()

        with patch("src.scraper.engine.fetch_with_retry", return_value=mock_response):
            scrape_target(config)

        assert captured[0][0] is mock_response
        assert captured[0][1] == "https://dir.example.com"


class TestParseExampleDirectory:
    def test_parses_listings(self):
        def make_mock(value):
            m = MagicMock()
            m.get.return_value = value
            return m

        listing = MagicMock()

        def listing_css(sel):
            if sel == ".company-name":
                return make_mock("Acme Corp")
            elif sel == ".website":
                w = MagicMock()
                w.first = MagicMock(attrib={"href": "https://acme.com"})
                return w
            elif sel == ".email":
                return make_mock("contact@acme.com")
            elif sel == ".phone":
                return make_mock("+1-555-0100")
            elif sel == ".address":
                return make_mock("123 Main St")
            elif sel == ".industry":
                return make_mock("Software")
            return MagicMock()

        listing.css.side_effect = listing_css

        response = MagicMock()
        response.css.return_value = [listing]

        records = parse_example_directory(response, source_url="https://dir.example.com")
        assert len(records) == 1
        assert records[0].company_name == "Acme Corp"
        assert records[0].website == "https://acme.com"
        assert records[0].email == "contact@acme.com"
        assert records[0].phone == "+1-555-0100"
        assert records[0].address == "123 Main St"
        assert records[0].industry_code == "Software"
        assert records[0].source_url == "https://dir.example.com"

    def test_skip_listings_without_company_name(self):
        mock_response = MagicMock()
        mock_response.css.return_value = []

        records = parse_example_directory(mock_response)
        assert records == []

    def test_multiple_listings(self):
        def make_listing(name, site, mail):
            def css(sel):
                m = MagicMock()
                m.get.return_value = {
                    ".company-name": name,
                    ".email": mail,
                    ".phone": "",
                    ".address": "",
                    ".industry": "",
                }.get(sel, "")
                if sel == ".website":
                    w = MagicMock()
                    w.first = MagicMock(attrib={"href": site})
                    return w
                return m
            item = MagicMock()
            item.css.side_effect = css
            return item

        response = MagicMock()
        response.css.return_value = [
            make_listing("Alpha Corp", "https://alpha.com", "alpha@alpha.com"),
            make_listing("Beta Inc", "https://beta.com", "beta@beta.com"),
        ]

        records = parse_example_directory(response, source_url="https://dir.example.com")
        assert len(records) == 2
        assert records[0].company_name == "Alpha Corp"
        assert records[1].company_name == "Beta Inc"
