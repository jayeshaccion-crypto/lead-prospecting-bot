import logging
import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from src.scraper.targets import (
    RawRecord,
    register_parser,
    PARSER_REGISTRY,
    parse_example_directory,
    _is_directory_domain,
    _extract_emails_from_text,
    _extract_websites_from_text,
    _extract_phone_from_html,
    _clean_phone,
    _safe_str,
    _extract_xhr_data,
    _extract_next_data,
    _extract_json_ld,
    _extract_initial_state,
    _parse_jd_from_xhr,
    _parse_jd_from_css,
    _parse_im_from_state,
    _parse_ti_from_css,
    _enrich_from_detail_pages,
    _extract_detail_urls,
    _parse_reveal_xhr,
    _clean_contact_values,
    _jd_page_url,
    _im_page_url,
    _ti_page_url,
    _save_debug_html,
    DIRECTORY_DOMAINS,
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





class TestParseExampleDirectory:
    def test_parses_listings(self):
        def make_element(text_value):
            el = MagicMock()
            el.text = text_value
            return el

        def make_selector(text_value):
            s = MagicMock()
            s.first = make_element(text_value) if text_value is not None else None
            return s

        listing = MagicMock()

        def listing_css(sel):
            if sel == ".company-name":
                return make_selector("Acme Corp")
            elif sel == ".website":
                w = MagicMock()
                w.first = MagicMock(attrib={"href": "https://acme.com"})
                return w
            elif sel == ".email":
                return make_selector("contact@acme.com")
            elif sel == ".phone":
                return make_selector("+1-555-0100")
            elif sel == ".address":
                return make_selector("123 Main St")
            elif sel == ".industry":
                return make_selector("Software")
            return make_selector(None)

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
                if sel == ".company-name":
                    s = MagicMock()
                    s.first = MagicMock()
                    s.first.text = name
                    return s
                elif sel == ".website":
                    w = MagicMock()
                    w.first = MagicMock(attrib={"href": site})
                    return w
                elif sel == ".email":
                    s = MagicMock()
                    s.first = MagicMock()
                    s.first.text = mail
                    return s
                else:
                    s = MagicMock()
                    s.first = MagicMock()
                    s.first.text = ""
                    return s
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


class TestIsDirectoryDomain:
    def test_directory_domain_returns_true(self):
        for d in DIRECTORY_DOMAINS:
            assert _is_directory_domain(d), f"{d} should be directory"
            assert _is_directory_domain(f"www.{d}"), f"www.{d} should be directory"

    def test_subdomain_returns_true(self):
        assert _is_directory_domain("listing.justdial.com")
        assert _is_directory_domain("www.facebook.com")
        assert _is_directory_domain("tiimg.tistatic.com")
        assert _is_directory_domain("www.getdistributors.com")
        assert _is_directory_domain("www.w3.org")

    def test_non_directory_returns_false(self):
        assert not _is_directory_domain("acme-corp.com")
        assert not _is_directory_domain("www.my-consulting.com")

    def test_substring_does_not_false_positive(self):
        assert not _is_directory_domain("notjustdial.com")
        assert not _is_directory_domain("mygoogle-consulting.com")
        assert not _is_directory_domain("facetwitter.net")

    def test_url_with_port_stripped(self):
        assert _is_directory_domain("justdial.com:8080")
        assert not _is_directory_domain("acme.com:3000")


class TestExtractEmails:
    def test_finds_single_email(self):
        assert _extract_emails_from_text("Contact: info@example.com") == ["info@example.com"]

    def test_finds_multiple_emails(self):
        res = _extract_emails_from_text("a@b.com c@d.co.in")
        assert len(res) == 2

    def test_empty_text(self):
        assert _extract_emails_from_text("") == []
        assert _extract_emails_from_text("No emails here!") == []


class TestExtractWebsites:
    def test_extracts_http_urls(self):
        res = _extract_websites_from_text('Visit https://acme.com today')
        assert "https://acme.com" in res

    def test_filters_directory_domains(self):
        res = _extract_websites_from_text('https://facebook.com https://acme.com')
        assert "https://acme.com" in res
        assert "https://facebook.com" not in res

    def test_filters_justdial(self):
        res = _extract_websites_from_text('https://www.justdial.com/xyz https://real.com')
        assert "https://real.com" in res
        assert "https://www.justdial.com/xyz" not in res

    def test_filters_directory_asset_cdn(self):
        """T007 — a directory CDN asset (TradeIndia logo) is not a company website."""
        res = _extract_websites_from_text(
            'https://tiimg.tistatic.com/new_website1/ti-design/images/tiLoginLogo '
            'https://acme.com'
        )
        assert "https://acme.com" in res
        assert "https://tiimg.tistatic.com" not in res

    def test_ignores_json_ld_script_chrome(self):
        """T007 — JSON-LD sameAs/chrome URLs (Wikipedia, socials) inside
        <script> blocks are page metadata about the directory, not a company."""
        html = (
            '<script type="application/ld+json">'
            '{"sameAs":["https://en.wikipedia.org/wiki/TradeIndia",'
            '"https://www.facebook.com/tradeindia"],'
            '"url":"https://www.tradeindia.com/about-us/contact-us/"}</script>'
            '<a href="https://acme.com">acme</a>'
        )
        res = _extract_websites_from_text(html)
        assert "https://acme.com" in res
        assert not any("wikipedia" in u or "tradeindia" in u or "facebook" in u for u in res)

    def test_deduplicates_urls(self):
        res = _extract_websites_from_text('https://acme.com https://acme.com')
        assert len(res) == 1

    def test_requires_valid_domain(self):
        assert _extract_websites_from_text("https://a") == []
        assert _extract_websites_from_text("http://localhost") == []

    def test_empty_text(self):
        assert _extract_websites_from_text("") == []


class TestExtractPhone:
    def test_indian_mobile(self):
        phone = _extract_phone_from_html("Call 9876543210 now")
        assert phone == "9876543210"

    def test_indian_mobile_with_91(self):
        phone = _extract_phone_from_html("Call +919876543210 now")
        assert phone == "+919876543210"

    def test_indian_mobile_with_country_code_space(self):
        phone = _extract_phone_from_html("Call +91 9876543210 now")
        assert phone is not None

    def test_international_number(self):
        phone = _extract_phone_from_html("Call +1-555-1234567 now")
        assert phone is not None and len(phone) >= 10

    def test_landline_with_0_prefix(self):
        phone = _extract_phone_from_html("Call 011-12345678 now")
        assert phone is not None and len(phone) >= 10

    def test_rejects_short_numbers(self):
        assert _extract_phone_from_html("Pin 123456") is None

    def test_rejects_number_within_long_digit_seq(self):
        assert _extract_phone_from_html("id_98765432101234") is None

    def test_no_phone(self):
        assert _extract_phone_from_html("Hello world") is None

    def test_empty_html(self):
        assert _extract_phone_from_html("") is None


class TestCleanPhone:
    def test_clean_indian_mobile(self):
        assert _clean_phone("9876543210") == "9876543210"

    def test_clean_with_plus(self):
        assert _clean_phone("+919876543210") == "+919876543210"

    def test_clean_with_dashes(self):
        assert _clean_phone("987-654-3210") == "9876543210"

    def test_clean_strips_whitespace(self):
        assert _clean_phone("  9876543210  ") == "9876543210"

    def test_too_short_returns_none(self):
        assert _clean_phone("123456") is None

    def test_zero_returns_none(self):
        assert _clean_phone("0") is None

    def test_dash_returns_none(self):
        assert _clean_phone("-") is None

    def test_empty_returns_none(self):
        assert _clean_phone("") is None
        assert _clean_phone("   ") is None


class TestSafeStr:
    def test_none_returns_none(self):
        assert _safe_str(None) is None

    def test_empty_returns_none(self):
        assert _safe_str("") is None

    def test_null_string_returns_none(self):
        assert _safe_str("null") is None

    def test_trims_whitespace(self):
        assert _safe_str("  hello  ") == "hello"

    def test_truncates_long_strings(self):
        long = "x" * 5000
        assert len(_safe_str(long)) <= 1000

    def test_short_string_passes_through(self):
        assert _safe_str("hello") == "hello"


class TestExtractXhrData:
    def test_no_xhr_returns_none(self):
        resp = MagicMock()
        resp.captured_xhr = None
        assert _extract_xhr_data(resp) is None

    def test_empty_xhr_list_returns_none(self):
        resp = MagicMock()
        resp.captured_xhr = []
        assert _extract_xhr_data(resp) is None

    def test_extracts_from_search_output(self):
        xhr = MagicMock()
        xhr.body = b'{"data":{"searchOutput":{"results":[{"name":"Test Corp"}]}}}'
        xhr.url = "https://www.justdial.com/api/search"
        resp = MagicMock()
        resp.captured_xhr = [xhr]

        data = _extract_xhr_data(resp)
        assert data is not None
        assert data[0]["name"] == "Test Corp"

    def test_prefers_justdial_api_xhr(self):
        generic = MagicMock()
        generic.body = b'{"results":[{"name":"Generic"}]}'
        generic.url = "https://analytics.com/track"

        jd = MagicMock()
        jd.body = b'{"data":{"searchOutput":{"results":[{"name":"JD Corp"}]}}}'
        jd.url = "https://www.justdial.com/api/search"

        resp = MagicMock()
        resp.captured_xhr = [generic, jd]

        data = _extract_xhr_data(resp)
        assert data is not None
        assert data[0]["name"] == "JD Corp"

    def test_falls_back_to_first_xhr_if_no_justdial_match(self):
        xhr = MagicMock()
        xhr.body = b'{"results":[{"name":"Fallback Corp"}]}'
        xhr.url = None
        resp = MagicMock()
        resp.captured_xhr = [xhr]

        data = _extract_xhr_data(resp)
        assert data is not None
        assert data[0]["name"] == "Fallback Corp"

    def test_skips_non_dict_xhr_body(self):
        xhr = MagicMock()
        xhr.body = b'"just a string"'
        xhr.url = ""
        resp = MagicMock()
        resp.captured_xhr = [xhr]

        assert _extract_xhr_data(resp) is None


class TestExtractNextData:
    def test_extracts_valid_json(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{"key":"value"}</script>'
        assert _extract_next_data(html) == {"key": "value"}

    def test_no_next_data_returns_none(self):
        assert _extract_next_data("<html></html>") is None

    def test_malformed_json_returns_none(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{invalid}</script>'
        assert _extract_next_data(html) is None


class TestExtractJsonLd:
    def test_extracts_single_block(self):
        html = '<script type="application/ld+json">{"@type":"LocalBusiness","name":"Test"}</script>'
        data = _extract_json_ld(html)
        assert len(data) == 1
        assert data[0]["name"] == "Test"

    def test_extracts_multiple_blocks(self):
        html = (
            '<script type="application/ld+json">{"@type":"LocalBusiness","name":"A"}</script>'
            '<script type="application/ld+json">{"@type":"Organization","name":"B"}</script>'
        )
        assert len(_extract_json_ld(html)) == 2

    def test_skips_malformed_blocks(self):
        html = (
            '<script type="application/ld+json">{valid}</script>'
            '<script type="application/ld+json">{invalid}</script>'
        )
        # first is malformed, second is malformed, both skipped
        data = _extract_json_ld(html)
        assert len(data) == 0

    def test_no_json_ld_returns_empty(self):
        assert _extract_json_ld("<html></html>") == []


class TestExtractInitialState:
    def test_extracts_object_state(self):
        html = '<script>window.__INITIAL_STATE__ = {"data": [1, 2]};</script>'
        state = _extract_initial_state(html)
        assert state == {"data": [1, 2]}

    def test_extracts_array_state(self):
        html = '<script>window.__INITIAL_STATE__ = [{"name": "A"}, {"name": "B"}];</script>'
        state = _extract_initial_state(html)
        assert isinstance(state, list)
        assert len(state) == 2

    def test_extracts_preloaded_state(self):
        html = '<script>window.__PRELOADED_STATE__ = {"key": "val"};</script>'
        assert _extract_initial_state(html) == {"key": "val"}

    def test_no_state_returns_none(self):
        assert _extract_initial_state("<html></html>") is None

    def test_malformed_json_returns_none(self):
        html = '<script>window.__INITIAL_STATE__ = {bad json};</script>'
        assert _extract_initial_state(html) is None


class TestJustdialParsers:
    def test_xhr_parser_extracts_all_fields(self):
        data = [{
            "name": "Tech Corp",
            "contactNumber": "9876543210",
            "address": "123 Street",
            "area": "Downtown",
            "city": "Delhi",
            "type": "IT Services",
            "website": "https://techcorp.com",
            "email": "info@techcorp.com",
        }]
        records = _parse_jd_from_xhr(data, source_url="https://justdial.com")
        assert len(records) == 1
        assert records[0].company_name == "Tech Corp"
        assert records[0].phone == "9876543210"
        assert records[0].address == "123 Street, Downtown, Delhi"
        assert records[0].industry_code == "IT Services"
        assert records[0].website == "https://techcorp.com"
        assert records[0].email == "info@techcorp.com"

    def test_xhr_parser_filters_directory_websites(self):
        data = [{"name": "Dir Co", "website": "https://facebook.com/co"}]
        records = _parse_jd_from_xhr(data, source_url="")
        assert records[0].website is None

    def test_xhr_parser_skips_empty_name(self):
        assert _parse_jd_from_xhr([{"name": ""}], "") == []

    def test_css_parser_skips_missing_name(self):
        resp = MagicMock()
        card = MagicMock()
        sel = MagicMock()
        sel.first = None
        card.css.return_value = sel
        card._root = "<div></div>"
        resp.css.return_value = [card]
        records = _parse_jd_from_css(resp, "")
        assert records == []


class TestIndiaMartParsers:
    def test_state_parser_extracts_records(self):
        state = {
            "data": [
                {"CMP": "Tech Solutions", "ad": "addr1", "city": "Mumbai", "g_s": "MH", "ds": "Software Co"},
            ],
        }
        records = _parse_im_from_state(state, source_url="https://indiamart.com")
        assert len(records) == 1
        assert records[0].company_name == "Tech Solutions"
        assert records[0].address == "addr1, Mumbai, MH"
        assert records[0].industry_code == "Software Co"

    def test_state_parser_empty_data(self):
        assert _parse_im_from_state({"data": []}, "") == []
        assert _parse_im_from_state({}, "") == []

    def test_state_parser_skips_missing_name(self):
        assert _parse_im_from_state({"data": [{"CMP": ""}]}, "") == []

    def test_state_parser_filters_indiamart_url_in_website(self):
        state = {
            "data": [
                {"CMP": "Co", "s_url": "https://www.indiamart.com/co"},
            ],
        }
        records = _parse_im_from_state(state, "")
        assert records[0].website is None

    def test_state_parser_allows_external_url(self):
        state = {
            "data": [
                {"CMP": "Co", "s_url": "https://real-site.com"},
            ],
        }
        records = _parse_im_from_state(state, "")
        assert records[0].website == "https://real-site.com"


class TestTradeIndiaParsers:
    def test_css_parser_extracts_records(self):
        card = MagicMock()
        name_el = MagicMock()
        name_el.text = "Test Company"
        h3_list = [MagicMock(), MagicMock(text="Delhi")]
        card.css.side_effect = lambda sel: {
            ".company-url": type("sel", (), {"first": name_el})(),
            "h3": h3_list,
        }.get(sel, type("sel", (), {"first": None})())

        resp = MagicMock()
        resp.css.return_value = [card]

        records = _parse_ti_from_css(resp, source_url="https://tradeindia.com")
        assert len(records) == 1
        assert records[0].company_name == "Test Company"

    def test_css_parser_skips_missing_name(self):
        card = MagicMock()
        card.css.return_value.first = None
        card._root = "<div></div>"
        resp = MagicMock()
        resp.css.return_value = [card]
        records = _parse_ti_from_css(resp, "")
        assert records == []

    def _card_with_href(self, href):
        card = MagicMock()
        name_el = MagicMock()
        name_el.text = "Acme"
        name_el.attrib = {"href": href}
        h3_list = [MagicMock(), MagicMock(text="Delhi")]
        card.css.side_effect = lambda sel: {
            ".company-url": type("sel", (), {"first": name_el})(),
            "h3": h3_list,
        }.get(sel, type("sel", (), {"first": None})())
        return card

    def test_css_parser_captures_resolved_detail_url(self):
        """T012 — D1: relative anchor href is urljoined against the listing URL."""
        resp = MagicMock()
        resp.css.return_value = [self._card_with_href("/acme-com-152913794/")]
        records = _parse_ti_from_css(
            resp, source_url="https://www.tradeindia.com/kolkata/software-solutions-city-200579.html")
        assert len(records) == 1
        assert records[0].detail_url == "https://www.tradeindia.com/acme-com-152913794/"
        assert records[0].source_url == "https://www.tradeindia.com/kolkata/software-solutions-city-200579.html"

    def test_css_parser_detail_url_none_when_no_href(self):
        """T012 — card without a resolvable href gets detail_url=None (no crash)."""
        name_el = MagicMock()
        name_el.text = "Acme"
        name_el.attrib = {}
        card = MagicMock()
        card.css.side_effect = lambda sel: {
            ".company-url": type("sel", (), {"first": name_el})(),
            "h3": [MagicMock(), MagicMock(text="Delhi")],
        }.get(sel, type("sel", (), {"first": None})())
        resp = MagicMock()
        resp.css.return_value = [card]
        records = _parse_ti_from_css(resp, "https://www.tradeindia.com/listing.html")
        assert records[0].detail_url is None


class TestExtractDetailUrls:
    def test_ti_primary_path_captures_urls_across_pages(self):
        """H1 — base_idx > 0 (pagination page 2+) still captures per-record detail URLs."""
        records = [
            RawRecord(company_name="A", detail_url="https://www.tradeindia.com/a/", source_url="l"),
            RawRecord(company_name="B", detail_url="https://www.tradeindia.com/b/", source_url="l"),
            RawRecord(company_name="C", detail_url=None, source_url="l"),
        ]
        resp = MagicMock()
        resp.html_content = "<html></html>"
        out = _extract_detail_urls("parse_tradeindia", resp, records, base_idx=27)
        assert out == [
            (27, "https://www.tradeindia.com/a/"),
            (28, "https://www.tradeindia.com/b/"),
        ]

    @staticmethod
    def _card(name, href):
        card = MagicMock()

        def css(sel):
            if sel == ".company-url, a[href], h2, h3":
                name_el = MagicMock()
                name_el.text = name
                return type("sel", (), {"first": name_el})()
            if sel in (".company-url a", ".company-url", "a[href*='tradeindia.com']", "h2 a", "h3 a"):
                if href:
                    link_el = MagicMock()
                    link_el.attrib = {"href": href}
                    return type("sel", (), {"first": link_el})()
                return type("sel", (), {"first": None})()
            return type("sel", (), {"first": None})()

        card.css.side_effect = css
        return card

    def test_ti_fallback_aligns_named_cards_to_records(self):
        """M3 — a nameless card is skipped so card k still maps to record k."""
        cards = [
            self._card("A", "https://www.tradeindia.com/a/"),
            self._card(None, "https://www.tradeindia.com/nameless/"),
            self._card("B", "https://www.tradeindia.com/b/"),
        ]
        resp = MagicMock()
        resp.html_content = "<html></html>"
        resp.url = "https://www.tradeindia.com/kolkata/software-solutions-city-200579.html"
        resp.css.return_value = cards
        records = [
            RawRecord(company_name="A", detail_url=None, source_url="l"),
            RawRecord(company_name="B", detail_url=None, source_url="l"),
        ]
        out = _extract_detail_urls("parse_tradeindia", resp, records, base_idx=27)
        assert out == [
            (27, "https://www.tradeindia.com/a/"),
            (28, "https://www.tradeindia.com/b/"),
        ]

    def test_im_path_aligned_after_skipping_nameless_items(self, monkeypatch):
        """H1/M3 — nameless items are skipped so the item index matches the record index."""
        state = {"data": [
            {"CMP": "", "s_url": "https://dir.indiamart.com/nameless.html"},
            {"CMP": "A", "s_url": "https://dir.indiamart.com/a.html?f=1"},
            {"CMP": "B", "s_url": "https://dir.indiamart.com/b.html"},
        ]}
        monkeypatch.setattr("src.scraper.targets._extract_initial_state", lambda html: state)
        resp = MagicMock()
        resp.html_content = "<html></html>"
        records = [RawRecord(company_name="A"), RawRecord(company_name="B")]
        out = _extract_detail_urls("parse_indiamart", resp, records, base_idx=27)
        assert out == [
            (27, "https://dir.indiamart.com/a.html/"),
            (28, "https://dir.indiamart.com/b.html/"),
        ]


class TestParseRevealXhr:
    def test_extracts_phone_and_email(self):
        """T012 — get-user-mobile XHR is the js-reveal data source."""
        resp = SimpleNamespace(captured_xhr=[
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=1",
                body=b'{"ifpaid":false,"number_mask":false,"default_email":"puja@elab24x7.com","default_mobile":"07971671113"}',
            ),
        ])
        phone, email = _parse_reveal_xhr(resp)
        assert phone == "07971671113"
        assert email == "puja@elab24x7.com"

    def test_none_when_no_matching_xhr(self):
        resp = SimpleNamespace(captured_xhr=[
            SimpleNamespace(url="https://api.tradeindia.com/home/home-page/user-details", body=b"{}"),
        ])
        assert _parse_reveal_xhr(resp) == (None, None)

    def test_merges_fields_across_multiple_xhrs(self):
        """L5 — a response carrying only phone and another carrying only email
        are both honored (first non-empty wins per field)."""
        resp = SimpleNamespace(captured_xhr=[
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=1",
                body=b'{"default_mobile":"07971671113","default_email":""}',
            ),
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=2",
                body=b'{"default_mobile":"","default_email":"puja@elab24x7.com"}',
            ),
        ])
        assert _parse_reveal_xhr(resp) == ("07971671113", "puja@elab24x7.com")

    def test_rejects_invalid_phone_format(self):
        """L5 — the revealed phone is validated like every other phone source."""
        resp = SimpleNamespace(captured_xhr=[
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=1",
                body=b'{"default_mobile":"abc","default_email":"puja@elab24x7.com"}',
            ),
        ])
        assert _parse_reveal_xhr(resp) == (None, "puja@elab24x7.com")


class TestCleanContactValues:
    def test_rejects_site_wide_values(self):
        assert _clean_contact_values("01146710423", "helpdesk@tradeindia.com") == (None, None, None)

    def test_passes_through_genuine_values(self):
        assert _clean_contact_values("07971671113", "puja@elab24x7.com", "https://elab24x7.com") == (
            "07971671113", "puja@elab24x7.com", "https://elab24x7.com")


class TestEnrichFromDetailPages:
    def test_skips_already_enriched(self):
        rec = RawRecord(company_name="C", phone="1234567890", email="a@b.com")
        session = MagicMock()
        targets = [(0, "https://detail.com")]
        _enrich_from_detail_pages(session, [rec], targets, timeout=30000)
        session.fetch.assert_not_called()

    def test_merges_missing_fields(self):
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"Contact: 9876543210, info@co.com"
        session.fetch.return_value = resp
        records = [rec]
        targets = [(0, "https://detail.com")]
        _enrich_from_detail_pages(session, records, targets, timeout=30000)
        assert records[0].phone == "9876543210"
        assert records[0].email == "info@co.com"

    def test_preserves_existing_fields_when_detail_has_none(self):
        """Detail page returns no new data — listing page data preserved."""
        rec = RawRecord(company_name="C", website="https://orig.com", email="orig@co.com", phone=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"Welcome to our company"
        session.fetch.return_value = resp
        targets = [(0, "https://detail.com")]
        _enrich_from_detail_pages(session, [rec], targets, timeout=30000)
        assert rec.website == "https://orig.com"
        assert rec.email == "orig@co.com"

    def test_empty_targets_does_nothing(self):
        session = MagicMock()
        _enrich_from_detail_pages(session, [], [], timeout=30000)
        session.fetch.assert_not_called()

    def test_reveal_js_sets_phone_email_not_website(self):
        """T012 — js-reveal path: phone+email from the XHR; website stays unavailable."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"<html><body>company</body></html>"
        resp.captured_xhr = [
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=1",
                body=b'{"default_email":"puja@elab24x7.com","default_mobile":"07971671113"}',
            ),
        ]
        session.fetch.return_value = resp
        records = [rec]
        targets = [(0, "https://www.tradeindia.com/acme-1/")]
        _enrich_from_detail_pages(session, records, targets, timeout=30000, reveal_js=True)
        assert records[0].phone == "07971671113"
        assert records[0].email == "puja@elab24x7.com"
        assert records[0].website is None

    def test_mailto_email_extracted(self):
        """T012 — mailto href yields an email on the generic path."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b'<a href="mailto:info@co.com">Email us</a>'
        session.fetch.return_value = resp
        records = [rec]
        _enrich_from_detail_pages(session, records, [(0, "https://detail.com")], timeout=30000)
        assert records[0].email == "info@co.com"

    def test_enrichment_unavailable_literal_logged(self, caplog):
        """T012 — every unfilled field logs the grep-able token."""
        rec = RawRecord(company_name="Acme", phone=None, email=None, website=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"no contact details here"
        session.fetch.return_value = resp
        with caplog.at_level(logging.INFO, logger="src.scraper.targets"):
            _enrich_from_detail_pages(session, [rec], [(0, "https://detail.com")], timeout=30000)
        assert "enrichment_unavailable: phone" in caplog.text
        assert "enrichment_unavailable: email" in caplog.text
        assert "enrichment_unavailable: website" in caplog.text
        assert 'record="Acme"' in caplog.text

    def test_site_wide_values_rejected(self, caplog):
        """T012 — helpdesk email / 01146710423 phone never kept as company data."""
        rec = RawRecord(company_name="Acme", phone=None, email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"<html></html>"
        resp.captured_xhr = [
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=1",
                body=b'{"default_email":"helpdesk@tradeindia.com","default_mobile":"01146710423"}',
            ),
        ]
        session.fetch.return_value = resp
        records = [rec]
        with caplog.at_level(logging.INFO, logger="src.scraper.targets"):
            _enrich_from_detail_pages(session, records, [(0, "https://detail.com")], timeout=30000, reveal_js=True)
        assert records[0].phone is None
        assert records[0].email is None
        assert "enrichment_unavailable: phone" in caplog.text
        assert "enrichment_unavailable: email" in caplog.text

    def test_does_not_overwrite_populated_fields(self):
        """T012 — a detail value never overwrites an existing listing field;
        only genuinely empty fields are filled (partial-field case)."""
        rec = RawRecord(company_name="C", phone="9876543210", email=None, website=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"Contact: 1111111111, other@co.com, https://other.example"
        session.fetch.return_value = resp
        records = [rec]
        _enrich_from_detail_pages(session, records, [(0, "https://detail.com")], timeout=30000)
        assert records[0].phone == "9876543210"  # populated phone preserved
        assert records[0].email == "other@co.com"  # empty email filled
        assert records[0].website == "https://other.example"  # empty website filled

    def test_site_wide_rejected_at_merge_boundary(self, caplog):
        """M1 — a polluted value captured at listing time is rejected at the
        merge boundary too, not just the freshly-extracted detail value."""
        rec = RawRecord(company_name="Acme", phone="01146710423", email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b"<html>helpdesk@tradeindia.com 01146710423</html>"
        session.fetch.return_value = resp
        records = [rec]
        with caplog.at_level(logging.INFO, logger="src.scraper.targets"):
            _enrich_from_detail_pages(session, records, [(0, "https://detail.com")], timeout=30000)
        assert records[0].phone is None  # site-wide phone purged
        assert records[0].email is None  # site-wide email rejected too
        assert "enrichment_unavailable: phone" in caplog.text
        assert "enrichment_unavailable: email" in caplog.text

    def test_robots_denied_not_counted_as_attempted(self, caplog):
        """L1 — a robots-disallowed URL is not counted in 'attempted'."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        records = [rec]
        stats = _enrich_from_detail_pages(
            session, records, [(0, "https://detail.com")], timeout=30000,
            robots_allowed=lambda url: False,
        )
        session.fetch.assert_not_called()
        assert stats["attempted"] == 0
        assert stats["fetched"] == 0

    def test_reveal_js_extracts_website_when_present(self):
        """M2 — the reveal path no longer hardcodes website=None; an external
        site anchor in the page is captured (unavailable still logged when absent)."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        resp = MagicMock()
        resp.html_content = b'<html><a href="https://acme.example/about">our site</a></html>'
        resp.captured_xhr = [
            SimpleNamespace(
                url="https://api.tradeindia.com/manufacturers/manufacturers/get-user-mobile?profile_id=1",
                body=b'{"default_email":"puja@elab24x7.com","default_mobile":"07971671113"}',
            ),
        ]
        session.fetch.return_value = resp
        records = [rec]
        _enrich_from_detail_pages(
            session, records, [(0, "https://www.tradeindia.com/acme-1/")], timeout=30000, reveal_js=True)
        assert records[0].phone == "07971671113"
        assert records[0].email == "puja@elab24x7.com"
        assert records[0].website == "https://acme.example/about"

    def test_robots_gate_skips_disallowed(self):
        """T012 — robots disallow precedes the fetch (Constitution I)."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        records = [rec]
        _enrich_from_detail_pages(
            session, records, [(0, "https://detail.com")], timeout=30000,
            robots_allowed=lambda url: False,
        )
        session.fetch.assert_not_called()

    def test_cap_zero_denies_all_fetches(self):
        """T012 — cap=0 / over-cap: no request issued for the domain."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        records = [rec]
        calls = []
        _enrich_from_detail_pages(
            session, records, [(0, "https://detail.com/1"), (1, "https://detail.com/2")],
            timeout=30000,
            cap_guard=lambda: (calls.append(1), False)[1],
        )
        session.fetch.assert_not_called()
        assert len(calls) == 1

    def test_parse_error_not_conflated_with_unavailable(self, caplog):
        """T012 — a genuine extraction/fetch exception is NEVER logged as
        enrichment_unavailable (Constitution V); it is a distinct detail_parse_error."""
        rec = RawRecord(company_name="C", phone=None, email=None)
        session = MagicMock()
        session.fetch.side_effect = RuntimeError("boom: selector gone")
        with caplog.at_level(logging.ERROR, logger="src.scraper.targets"):
            _enrich_from_detail_pages(session, [rec], [(0, "https://detail.com")], timeout=30000)
        assert "detail_parse_error" in caplog.text
        assert "enrichment_unavailable" not in caplog.text


class TestBuildPageUrl:
    def test_jd_page_1_returns_base(self):
        assert _jd_page_url("https://justdial.com/search", 1) == "https://justdial.com/search"

    def test_jd_page_2_appends_query(self):
        assert _jd_page_url("https://justdial.com/search", 2) == "https://justdial.com/search?page=2"

    def test_im_page_1_returns_base(self):
        assert _im_page_url("https://indiamart.com/search", 1) == "https://indiamart.com/search"

    def test_im_page_2_appends_query(self):
        assert _im_page_url("https://indiamart.com/search", 2) == "https://indiamart.com/search?page=2"

    def test_ti_page_1_returns_base(self):
        assert _ti_page_url("https://tradeindia.com/search", 1) == "https://tradeindia.com/search"

    def test_ti_page_2_appends_query(self):
        assert _ti_page_url("https://tradeindia.com/search", 2) == "https://tradeindia.com/search?page=2"


class TestSaveDebugHtml:
    def test_saves_html_to_debug_dir(self):
        import os
        import tempfile
        from pathlib import Path

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                _save_debug_html("https://example.com/test-co", "<html>test content</html>")
                debug_dir = Path("debug_output")
                assert debug_dir.exists()
                files = list(debug_dir.glob("*.html"))
                assert len(files) == 1
                content = files[0].read_text(encoding="utf-8")
                assert "test content" in content
            finally:
                os.chdir(original_cwd)

    def test_handles_empty_html(self):
        import os
        import tempfile
        from pathlib import Path

        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                _save_debug_html("https://example.com/empty", "")
                debug_dir = Path("debug_output")
                assert debug_dir.exists()
                files = list(debug_dir.glob("*.html"))
                assert len(files) == 1
            finally:
                os.chdir(original_cwd)
