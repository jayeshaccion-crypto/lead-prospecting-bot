# Contract: JustDial Mode Selection (FR-001)

**Purpose**: Define the exact env-var reading logic and mode precedence.

## Env inputs

| Env var | Role | Source |
|---------|------|--------|
| `RESIDENTIAL_PROXY_URL_JUSTDIAL` | Residential trigger + residential request proxy | Existing (spider.py:218,233,466) |
| `WEBSHARE_PROXY_URL` / `WEBSHARE_PROXY_LIST` / `WEBSHARE_API_KEY` | Datacenter pool source (via `_init_proxy_pool`) | Existing (engine.py:43-65) |

No `PROXY_URL_JUSTDIAL` variable exists or is introduced.

## Mode resolution

```python
def _determine_jd_mode(self) -> str:
    from src.scraper import engine as _engine_mod
    _engine_mod._init_proxy_pool()
    if os.environ.get("RESIDENTIAL_PROXY_URL_JUSTDIAL", "").strip():
        return "residential"
    if _engine_mod._PROXY_POOL:
        return "datacenter"
    return "no_proxy"
```

**Precedence** (first match wins):

| # | Condition | Mode |
|---|-----------|------|
| 1 | `RESIDENTIAL_PROXY_URL_JUSTDIAL` non-empty after `strip()` | `residential` |
| 2 | `_PROXY_POOL` non-empty | `datacenter` |
| 3 | otherwise | `no_proxy` |

**Rules**:
- Residential takes priority when both residential var and datacenter pool are set.
- Whitespace-only residential value is treated as unset.
- Mode is resolved once per run (`on_start`) and fixed for the run.

## Mode → behavior mapping

| Mode | JustDial behavior | Requests issued |
|------|-------------------|-----------------|
| `residential` | Full crawl at configured page depth via residential proxy | Category/city/page crawl requests (same depth as IndiaMart/TradeIndia) |
| `datacenter` | ASN confirmation test only (once per calendar day) | ≤ 10 probe requests; zero crawl requests |
| `no_proxy` | Skipped with explicit warning + `ScrapeError("ProxyNotConfigured")` | zero |

**Errors**:
- Webshare API fetch failure → pool empty → mode degrades to `no_proxy` (warning logged by `_init_proxy_pool`, never a crash).
