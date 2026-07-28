import os
from unittest.mock import patch, MagicMock

import httpx
import pytest

from src.config import load_enrichment_base_url
from src.enrichment.client import EnrichmentClient, enrich_records
from src.models import LeadRecord


class TestEnrichmentClientConstructor:
    def test_default_constructor_calls_load_functions(self):
        with patch("src.enrichment.client.load_enrichment_base_url", return_value="https://env.url"):
            with patch("src.enrichment.client.load_enrichment_api_key", return_value="env-key"):
                client = EnrichmentClient()
        assert client.base_url == "https://env.url"
        assert client.api_key == "env-key"
        assert client.timeout == 15.0

    def test_explicit_args_override_env(self):
        with patch("src.enrichment.client.load_enrichment_base_url") as mock_base:
            with patch("src.enrichment.client.load_enrichment_api_key") as mock_key:
                client = EnrichmentClient(base_url="https://custom.url", api_key="custom-key", timeout=30.0)
        mock_base.assert_not_called()
        mock_key.assert_not_called()
        assert client.base_url == "https://custom.url"
        assert client.api_key == "custom-key"
        assert client.timeout == 30.0

    def test_base_url_strips_trailing_slash(self):
        with patch("src.enrichment.client.load_enrichment_api_key", return_value="key"):
            client = EnrichmentClient(base_url="https://api.test.com/")
        assert client.base_url == "https://api.test.com"


class TestEnrichmentClient:
    def test_get_enrichment_success(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "domain": "acme.com",
            "company_name": "Acme Corp",
            "employee_count": 250,
            "revenue_band": "$10M-$50M",
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("acme.com")

        assert result == {"employee_count": 250, "revenue_band": "$10M-$50M"}
        mock_client.get.assert_called_once_with(
            "https://api.test.com/enrich",
            params={"domain": "acme.com"},
            headers={"Authorization": "Bearer test-key"},
        )

    def test_get_enrichment_non_200_returns_empty(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("acme.com")

        assert result == {}

    def test_get_enrichment_timeout_returns_empty(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = httpx.TimeoutException("timeout")

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("acme.com")

        assert result == {}

    def test_get_enrichment_network_error_returns_empty(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = httpx.RequestError("connection refused")

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("acme.com")

        assert result == {}

    def test_get_enrichment_partial_response(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "domain": "acme.com",
            "company_name": None,
            "employee_count": None,
            "revenue_band": None,
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("acme.com")

        assert result == {"employee_count": None, "revenue_band": None}

    def test_get_enrichment_empty_domain_calls_api(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"employee_count": None, "revenue_band": None}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("")

        assert result == {"employee_count": None, "revenue_band": None}
        mock_client.get.assert_called_once()

    def test_get_enrichment_malformed_json_returns_empty(self):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("malformed json")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.get_enrichment("acme.com")

        assert result == {}


class TestEnrichRecords:
    def test_empty_records_list(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = enrich_records([], base_url="https://api.test.com", api_key="test-key")
        mock_client.get.assert_not_called()
        assert result == []

    def test_same_dedup_key_shared_enrichment(self):
        records = [
            LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="shared.com"),
            LeadRecord(company_name="Alpha Clone", website="https://alpha.com", dedup_key="shared.com"),
        ]

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"employee_count": 99, "revenue_band": "$5M"}
            mock_client.get.return_value = resp

            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        mock_client.get.assert_called_once()
        assert result[0].employee_count == 99
        assert result[1].employee_count == 99
        assert result[0].revenue_band == "$5M"
        assert result[1].revenue_band == "$5M"

    def test_empty_string_dedup_key_skipped(self):
        records = [LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="")]

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        mock_client.get.assert_not_called()
        assert result[0].employee_count is None
        assert result[0].revenue_band is None

    def test_revenue_only_enrichment(self):
        records = [LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="alpha.com")]

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"employee_count": None, "revenue_band": "$10M-$50M"}
            mock_client.get.return_value = resp

            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        assert result[0].employee_count is None
        assert result[0].revenue_band == "$10M-$50M"

    def test_default_base_url_from_env(self):
        records = [LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="alpha.com")]

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"employee_count": 10, "revenue_band": "$1M"}

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            with patch("src.enrichment.client.load_enrichment_base_url", return_value="https://env-base.url"):
                result = enrich_records(records, api_key="test-key")

        assert result[0].employee_count == 10
        mock_client.get.assert_called_once()
        call_url = mock_client.get.call_args[0][0]
        assert call_url.startswith("https://env-base.url")

    def test_enrich_records_uses_env_api_key_when_not_provided(self):
        records = [LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="alpha.com")]

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"employee_count": 5, "revenue_band": "$500K"}
            mock_client.get.return_value = resp

            with patch("src.enrichment.client.load_enrichment_api_key", return_value="env-api-key"):
                result = enrich_records(records, base_url="https://api.test.com")

        assert result[0].employee_count == 5
    def test_enriches_records_by_dedup_key(self):
        records = [
            LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="alpha.com"),
            LeadRecord(company_name="Beta", website="https://beta.com", dedup_key="beta.com"),
        ]

        responses = {
            "alpha.com": {"employee_count": 50, "revenue_band": "$1M-$5M"},
            "beta.com": {"employee_count": 200, "revenue_band": "$10M-$50M"},
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client

            def get_side_effect(url, **kwargs):
                domain = kwargs.get("params", {}).get("domain", "")
                data = responses[domain]
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 200
                resp.json.return_value = data
                return resp

            mock_client.get.side_effect = get_side_effect

            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        assert result[0].employee_count == 50
        assert result[0].revenue_band == "$1M-$5M"
        assert result[1].employee_count == 200
        assert result[1].revenue_band == "$10M-$50M"

    def test_partial_enrichment(self):
        records = [
            LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="alpha.com"),
        ]

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = {"employee_count": 50, "revenue_band": None}
            mock_client.get.return_value = resp

            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        assert result[0].employee_count == 50
        assert result[0].revenue_band is None

    def test_enrich_many_with_different_responses(self):
        responses = {
            "acme.com": {"employee_count": 100, "revenue_band": "$5M-$10M"},
            "beta.com": {"employee_count": 25, "revenue_band": "$1M-$5M"},
        }

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client

            def get_side_effect(url, **kwargs):
                domain = kwargs.get("params", {}).get("domain", "")
                data = responses[domain]
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 200
                resp.json.return_value = data
                return resp

            mock_client.get.side_effect = get_side_effect

            client = EnrichmentClient(base_url="https://api.test.com", api_key="test-key")
            result = client.enrich_many(["acme.com", "beta.com", "acme.com"])

        assert mock_client.get.call_count == 2
        assert result["acme.com"] == {"employee_count": 100, "revenue_band": "$5M-$10M"}
        assert result["beta.com"] == {"employee_count": 25, "revenue_band": "$1M-$5M"}

    def test_skips_records_without_dedup_key(self):
        records = [LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key=None)]

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client

            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        mock_client.get.assert_not_called()
        assert result[0].employee_count is None
        assert result[0].revenue_band is None

    def test_skips_records_when_api_returns_empty(self):
        records = [LeadRecord(company_name="Alpha", website="https://alpha.com", dedup_key="alpha.com")]

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = enrich_records(records, base_url="https://api.test.com", api_key="test-key")

        assert result[0].employee_count is None
        assert result[0].revenue_band is None


