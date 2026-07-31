# Contract: JustDial End-of-Run Summary Lines (FR-005, FR-006, FR-008)

**Purpose**: Exact log strings for the ASN verdict, the CONCLUSION line, and the per-mode end-of-run summary. Wording MUST match the spec precisely.

## FR-008 — Mode summary (all three modes)

Emitted in the end-of-run summary (spider.py `on_close`, existing `JustDial mode:` line). Display labels:

| Mode (internal) | Summary line (exact) |
|-----------------|----------------------|
| `residential` | `JustDial mode: residential` |
| `datacenter` | `JustDial mode: datacenter-ASN-test` |
| `no_proxy` | `JustDial mode: no_proxy` |

The summary line MUST appear for every run, regardless of mode. The display label for datacenter is `datacenter-ASN-test` (per FR-008 labels), mapped from the internal `datacenter` value.

## FR-005 — ASN verdict line (datacenter mode only)

Exact string, after the probe completes:

```
JustDial: X/10 distinct proxy IPs attempted, Y blocked (body<500B), Z succeeded.
```

Where `X` = distinct IPs attempted (≤ 10), `Y` = blocked (body < 500B or error), `Z` = succeeded (body ≥ 500B). `X` is written literally (e.g. `3/10` when only 3 distinct IPs were available).

## FR-006 — CONCLUSION line (only when Y == X)

Appended immediately after the verdict line when every attempted IP was blocked:

```
CONCLUSION: JustDial block is ASN-level — datacenter proxies cannot bypass regardless of specific IP. Residential proxy required.
```

- Emitted **only** when `Y == X` (all attempted IPs blocked).
- Must NOT be emitted when `Z > 0`.
- Wording: "Residential proxy required." (per spec) — not "Residential proxy tier required." (the old spider.py:581-583 text); align to the spec wording.

## no_proxy mode — explicit warning (FR-007)

Emit a warning naming the specific missing env var(s), then log + record the error on skip:

```
Justdial requires a proxy but none configured (RESIDENTIAL_PROXY_URL_JUSTDIAL and WEBSHARE_PROXY_URL / WEBSHARE_PROXY_LIST / WEBSHARE_API_KEY) — skipping
```

plus `ScrapeError("ProxyNotConfigured")` appended to `scrape_errors` (existing behavior, spider.py:272-279).

The warning MUST name the actual vars that are missing (all of the above when none are set; only the residential var when the Webshare pool is also absent but its vars are set). Never a generic "none configured" without naming the vars.

## Credential redaction (constitution III)

Any proxy host logged (e.g. in blocked-IP sets or retry logs) MUST use the redacted form `str(proxy).partition("@")[-1]` (host:port, no credentials) — reuse the pattern at spider.py:480. Never log the full proxy URL with embedded `user:pass`.
