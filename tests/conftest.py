import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock heavy Scrapling browser dependencies so unit tests don't need
# patchright / playwright / curl_cffi installed at collection time.
# ---------------------------------------------------------------------------
_stealth_module = MagicMock()
_stealth_module.StealthySession = MagicMock()
_stealth_module.AsyncStealthySession = MagicMock()
sys.modules["scrapling.engines._browsers._stealth"] = _stealth_module

_stealth_chrome = MagicMock()
sys.modules["scrapling.fetchers.stealth_chrome"] = _stealth_chrome

# Replace StealthyFetcher with a plain MagicMock in the public namespace
import scrapling.fetchers
scrapling.fetchers.StealthyFetcher = MagicMock()
import scrapling
scrapling.StealthyFetcher = MagicMock()
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_html():
    return """
    <html>
    <body>
        <div class="listing">
            <h2 class="company-name">Acme Corp</h2>
            <a class="website" href="https://acme.com">acme.com</a>
            <span class="email">contact@acme.com</span>
            <span class="phone">+1-555-0100</span>
            <span class="address">123 Main St, Springfield, USA</span>
            <span class="industry">Software</span>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def mock_enrichment_response():
    return {
        "domain": "acme.com",
        "company_name": "Acme Corp",
        "employee_count": 250,
        "revenue_band": "$10M-$50M",
    }


@pytest.fixture
def mock_sheets_service(mocker):
    mock = mocker.patch("src.sheets.client.SheetsClient")
    mock.tab_exists.return_value = True
    mock.read_existing_dedup_keys.return_value = set()
    return mock
