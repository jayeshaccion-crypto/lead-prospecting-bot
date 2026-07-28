"""Shared fixtures and patches for all tests.

Google API modules are patched at import time since they may not be installed
in CI. Scrapling's StealthyFetcher is mocked to avoid browser dependency.
"""

import sys
from unittest.mock import MagicMock

# Patch scrapling modules that require browser dependencies
_stealth_module = MagicMock()
_stealth_module.StealthySession = MagicMock()
_stealth_module.AsyncStealthySession = MagicMock()
sys.modules["scrapling.engines._browsers._stealth"] = _stealth_module

_stealth_chrome = MagicMock()
sys.modules["scrapling.fetchers.stealth_chrome"] = _stealth_chrome
sys.modules["scrapling.fetchers.StealthyFetcher"] = MagicMock()

import scrapling.fetchers
scrapling.fetchers.StealthyFetcher = MagicMock()
import scrapling
scrapling.StealthyFetcher = MagicMock()
scrapling.Fetcher = MagicMock()

# Patch browserforge which may not be available
sys.modules["browserforge"] = MagicMock()
sys.modules["browserforge.headers"] = MagicMock()
sys.modules["browserforge.headers.Browser"] = MagicMock()
sys.modules["browserforge.headers.HeaderGenerator"] = MagicMock()

# Patch patchright which may not be available
sys.modules["patchright"] = MagicMock()
sys.modules["patchright.sync_api"] = MagicMock()
