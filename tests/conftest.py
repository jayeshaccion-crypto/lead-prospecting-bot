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
# Must use real ModuleType instances so subpackage imports resolve
import types
_browserforge = types.ModuleType("browserforge")
_browserforge_headers = types.ModuleType("browserforge.headers")
_browserforge_headers_gen = types.ModuleType("browserforge.headers.generator")
_browserforge_headers_gen.SUPPORTED_OPERATING_SYSTEMS = ("windows", "macos", "linux")
_browserforge_headers.generator = _browserforge_headers_gen
_browserforge_headers.Browser = MagicMock()
_browserforge_headers.HeaderGenerator = MagicMock()
_browserforge.headers = _browserforge_headers
sys.modules["browserforge"] = _browserforge
sys.modules["browserforge.headers"] = _browserforge_headers
sys.modules["browserforge.headers.generator"] = _browserforge_headers_gen

# Patch patchright which may not be available
sys.modules["patchright"] = MagicMock()
sys.modules["patchright.sync_api"] = MagicMock()
