import os

import pytest

from src.config import load_enrichment_base_url


class TestLoadEnrichmentBaseUrl:
    def test_returns_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("ENRICHMENT_BASE_URL", "https://custom-env.url")
        assert load_enrichment_base_url() == "https://custom-env.url"

    def test_returns_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("ENRICHMENT_BASE_URL", raising=False)
        assert load_enrichment_base_url() == "https://api.example.com"

    def test_returns_empty_string_when_set_empty(self, monkeypatch):
        monkeypatch.setenv("ENRICHMENT_BASE_URL", "")
        assert load_enrichment_base_url() == ""
