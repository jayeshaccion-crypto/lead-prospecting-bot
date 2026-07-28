from unittest.mock import patch, MagicMock

import pytest

from src.scraper.utils import (
    normalize_domain,
    is_valid_email,
    flag_invalid_email,
    retry,
    is_robots_allowed,
)


class TestNormalizeDomain:
    def test_returns_none_for_none(self):
        assert normalize_domain(None) is None

    def test_returns_none_for_empty(self):
        assert normalize_domain("") is None

    def test_strips_www_prefix(self):
        assert normalize_domain("www.example.com") == "example.com"

    def test_strips_trailing_slash(self):
        assert normalize_domain("example.com/") == "example.com"

    def test_lowercases_domain(self):
        assert normalize_domain("Example.COM") == "example.com"

    def test_strips_whitespace(self):
        assert normalize_domain("  www.Example.COM/  ") == "example.com"

    def test_preserves_subdomain(self):
        assert normalize_domain("sub.example.com") == "sub.example.com"

    def test_no_www_no_slash(self):
        assert normalize_domain("example.com") == "example.com"


class TestIsValidEmail:
    def test_valid_email_returns_true(self):
        assert is_valid_email("user@example.com") is True

    def test_valid_email_with_plus(self):
        assert is_valid_email("user+tag@example.co.uk") is True

    def test_valid_email_with_dots(self):
        assert is_valid_email("first.last@example.io") is True

    def test_none_returns_false(self):
        assert is_valid_email(None) is False

    def test_empty_returns_false(self):
        assert is_valid_email("") is False

    def test_missing_at_sign(self):
        assert is_valid_email("userexample.com") is False

    def test_missing_domain(self):
        assert is_valid_email("user@") is False

    def test_missing_local_part(self):
        assert is_valid_email("@example.com") is False


class TestFlagInvalidEmail:
    def test_valid_email_returns_trimmed(self):
        assert flag_invalid_email("  user@example.com  ") == "user@example.com"

    def test_invalid_email_gets_prefix(self):
        assert flag_invalid_email("bademail") == "UNVERIFIED:bademail"

    def test_none_returns_none(self):
        assert flag_invalid_email(None) is None

    def test_empty_returns_none(self):
        assert flag_invalid_email("") is None


class TestRetryDecorator:
    def test_succeeds_on_first_try(self):
        mock_fn = MagicMock(return_value="ok")

        @retry(max_attempts=3)
        def wrapped():
            return mock_fn()

        assert wrapped() == "ok"
        assert mock_fn.call_count == 1

    def test_succeeds_after_retries(self):
        mock_fn = MagicMock(side_effect=[ValueError("fail"), ValueError("fail"), "ok"])

        @retry(max_attempts=3)
        def wrapped():
            return mock_fn()

        assert wrapped() == "ok"
        assert mock_fn.call_count == 3

    def test_fails_after_all_retries(self):
        mock_fn = MagicMock(side_effect=ValueError("always fail"))

        @retry(max_attempts=3)
        def wrapped():
            return mock_fn()

        with pytest.raises(ValueError, match="always fail"):
            wrapped()
        assert mock_fn.call_count == 3

    @patch("src.scraper.utils.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        mock_fn = MagicMock(side_effect=[ValueError("fail"), ValueError("fail"), "ok"])

        @retry(max_attempts=3, base_delay=1.0, backoff=4.0)
        def wrapped():
            return mock_fn()

        wrapped()
        assert mock_sleep.call_args_list[0][0][0] == 1.0
        assert mock_sleep.call_args_list[1][0][0] == 4.0

    def test_single_attempt_no_retry(self):
        mock_fn = MagicMock(side_effect=ValueError("fail"))

        @retry(max_attempts=1)
        def wrapped():
            return mock_fn()

        with pytest.raises(ValueError):
            wrapped()
        assert mock_fn.call_count == 1


class TestIsRobotsAllowed:
    def test_allows_when_robots_allows(self):
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = True

        with patch("src.scraper.utils.RobotFileParser", return_value=mock_rp):
            result = is_robots_allowed("https://example.com/page")

        assert result is True
        mock_rp.read.assert_called_once()
        mock_rp.can_fetch.assert_called_once_with("LeadProspectingBot", "https://example.com/page")

    def test_disallows_when_robots_disallows(self):
        from src.scraper.utils import _robots_cache
        _robots_cache.clear()
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = False

        with patch("src.scraper.utils.RobotFileParser", return_value=mock_rp):
            result = is_robots_allowed("https://other-example.com/page")

        assert result is False

    def test_allows_when_robots_unreachable(self):
        mock_rp = MagicMock()
        mock_rp.read.side_effect = Exception("timeout")

        with patch("src.scraper.utils.RobotFileParser", return_value=mock_rp):
            result = is_robots_allowed("https://example.com/page")

        assert result is True

    def test_caches_parser_per_domain(self):
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = True

        with patch("src.scraper.utils.RobotFileParser", return_value=mock_rp):
            from src.scraper.utils import _robots_cache
            _robots_cache.clear()
            is_robots_allowed("https://example.com/page1")
            is_robots_allowed("https://example.com/page2")

        assert mock_rp.read.call_count == 1
        assert mock_rp.can_fetch.call_count == 2
