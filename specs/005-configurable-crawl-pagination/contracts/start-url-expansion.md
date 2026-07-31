# Contract: start-url-expansion

**Feature**: 005-configurable-crawl-pagination | **Spec**: [spec.md](../spec.md) FR-001, FR-003, FR-004 | **Date**: 2026-07-31

## 1. Purpose

Generate exactly one start URL per category × city combination for IndiaMART and TradeIndia, deterministically, from the top-level `categories`, `cities`, and `url_templates` keys of `config/targets.yaml`. JustDial is excluded (FR-004 — its URL generation and depth remain under Phase 2 mode logic).

## 2. Function contract

New pure function in `src/scraper/targets.py`:

```python
@dataclass(frozen=True)
class CrawlCombo:
    site: str            # "indiamart" | "tradeindia"
    category_slug: str
    city_slug: str
    url: str

def expand_start_urls(
    categories: list[dict],
    cities: list[dict],
    url_templates: dict[str, str],
    sites: tuple[str, ...] = ("indiamart", "tradeindia"),
) -> list[CrawlCombo]:
```

### Behavior

- Iterate `sites` in order; for each site iterate `categories` (list order) then `cities` (list order) → **category-major, city-minor** deterministic order: for N categories × M cities, exactly N×M combos per site (SC-001).
- Resolve labels exactly as `_build_source_url`/`_site_label` do today: `category = labels[site]`, `city = labels[site]`; format the site template with `category=`, `city=`, and for TradeIndia `code=city.get("tradeindia_code", "")`.
- Skip (log warning) any category or city missing a label for that site; do not emit a broken URL.
- Return `[]` with an explicit warning when `categories` or `cities` is empty (spec Edge Case).

### Invariants

- Pure: same config → same `list[CrawlCombo]` (no dict-ordering surprises; labels read via explicit `.get`).
- `CrawlCombo.url` is always the **page-1** URL (pagination is appended by `_build_page_url` later).
- Does not consult the daily cap, robots state, or proxies — scheduling concerns live in the spider.

## 3. Example (starter config)

For `software-development` (tradeindia label `software-development`) × `new-delhi` (tradeindia label `new-delhi`, code `228067`):

```
indiamart:  https://dir.indiamart.com/new-delhi/software-development-services.html
tradeindia: https://www.tradeindia.com/new-delhi/software-development-city-228067.html
```

## 4. Integration with `LeadSpider.start_requests` (src/scraper/spider.py)

- `__init__` reads top-level `categories` / `cities` / `url_templates` from `load_full_config()` (replacing the `expansion` reads).
- `start_requests` calls `expand_start_urls(...)` once; for each `CrawlCombo` of an enabled site: resolve `sid = SID_BY_NAME[combo.site]`, then run the existing per-request gates in the current code order (**robots check → cap check → proxy resolution** — robots first, so disallowed combos never consume the cap), then **yield only the page-1 `Request`** carrying `sid=` plus `_make_session_kwargs(sid, ...)` session kwargs. Carrying the sid/session kwargs is mandatory: it is how `DOMAIN_DELAYS` per-domain throttling and the stealth-vs-plain session split keep applying across the expanded target set (see Findings U1/I2 in analysis). Proxy eligibility stays site-derived as today (`use_proxy` for justdial/indiamart only; tradeindia never proxies). Lazy pagination — page 2+ comes from `parse`, see [pagination-early-stop.md](./pagination-early-stop.md).
- JustDial keeps its current `entry_url`/probe-based request flow unchanged.

## 5. Acceptance

- 2 categories × 2 cities → exactly 4 IndiaMART + 4 TradeIndia combos; growth to 10×10 → 100 + 100 with no code change (spec User Story 1 Independent Test; SC-001).
- `{code}` renders the per-city `tradeindia_code`; Bangalore's TradeIndia URL uses `bengaluru` (label differs from `bangalore` slug).
