# Contract: targets-config-schema

**Feature**: 005-configurable-crawl-pagination | **Spec**: [spec.md](../spec.md) FR-001, FR-002, FR-005, FR-007 | **Date**: 2026-07-31

## 1. File location and loading

- File: `config/targets.yaml` (renamed from `config/targets.yml`).
- Loaded via `src/config.py:load_full_config()`; default path changes to `config/targets.yaml`.
- `TARGETS_CONFIG` env var overrides the path (as today). `.github/workflows/daily.yml` and `.github/workflows/scrape.yml` must set `TARGETS_CONFIG: config/targets.yaml`.

## 2. Top-level schema

```yaml
targets:            # list[dict] — per-site crawl config (see Target table)
categories:         # list[dict] — {slug, labels{justdial,indiamart,tradeindia}}
cities:             # list[dict] — {slug, labels{...}, tradeindia_code}
url_templates:      # dict[str,str] — justdial / indiamart / tradeindia format strings
icp_categories:     # list[str] — allowlist, DEFAULT EMPTY (Phase 6 scoring)
icp_cities:         # list[str] — allowlist, DEFAULT EMPTY (Phase 6 scoring)
```

Legacy keys `expansion.categories`, `expansion.cities`, `icp.categories`, `icp.cities` are removed; their values move to the top level unchanged.

## 3. Per-target keys

| Target key | Type | Default | Applies to |
|-----------|------|---------|-----------|
| `name` | str | required | all |
| `enabled` | bool | false | all |
| `parser` | str | required | all |
| `max_pages` | int | `10` | IndiaMART, TradeIndia — SOLE pagination control (FR-005; `SCRAPE_FULL_PAGES` retired) |
| `pages` | int | `3` | JustDial only — unchanged (FR-004) |
| `max_requests_per_day` | int | required | all — per-domain daily cap (FR-007) |
| `fetch_kwargs` | dict | required | all — unchanged |

## 4. url_templates

```yaml
url_templates:
  justdial:  "https://www.justdial.com/{city}/{category}/nct-10278073"
  indiamart: "https://dir.indiamart.com/{city}/{category}.html"
  tradeindia: "https://www.tradeindia.com/{city}/{category}-city-{code}.html"
```

Format placeholders: `{category}` (site category label), `{city}` (site city label), `{code}` (city `tradeindia_code`, TradeIndia only). `_build_source_url` must now supply `code=`.

## 5. Sample starter file (pre-populated; runnable without operator edits — Q1)

```yaml
targets:
  - name: "Justdial"
    enabled: false
    entry_url: "https://www.justdial.com/Delhi/IT-Services/nct-10278073"
    parser: "parse_justdial"
    pages: 3
    max_requests_per_day: 40
    fetch_kwargs:
      timeout: 90000
      max_detail_pages: 0
      page_delay: 4.0
      target_delay: 3.0
      disable_resources: true
      wait_selector: "[class*='listing'], [class*='card'], .jf-listing-card"

  - name: "IndiaMART"
    enabled: true
    parser: "parse_indiamart"
    max_pages: 10
    max_requests_per_day: 40
    fetch_kwargs:
      timeout: 120000
      max_detail_pages: 0
      page_delay: 8.0
      target_delay: 8.0
      disable_resources: true
      wait_selector: ".card, [class*='product'], [class*='listing'], .lcard"

  - name: "TradeIndia"
    enabled: true
    parser: "parse_tradeindia"
    max_pages: 10
    max_requests_per_day: 100
    fetch_kwargs:
      timeout: 90000
      max_detail_pages: 20
      page_delay: 3.0
      target_delay: 3.0
      disable_resources: true
      wait_selector: ".top-cont, [class*='company-card'], .card-list"

categories:
  - slug: software-development
    labels:
      justdial: "IT-Services"
      indiamart: "software-development-services"
      tradeindia: "software-development"
  - slug: web-design
    labels:
      justdial: "Web-Design"
      indiamart: "web-design-services"
      tradeindia: "web-design"
  - slug: app-development
    labels:
      justdial: "App-Development"
      indiamart: "app-development-services"
      tradeindia: "app-development"
  - slug: it-consultancy
    labels:
      justdial: "IT-Consultancy"
      indiamart: "it-consultancy-services"
      tradeindia: "it-consultancy"
  - slug: digital-marketing
    labels:
      justdial: "Digital-Marketing"
      indiamart: "digital-marketing-services"
      tradeindia: "digital-marketing"
  - slug: cloud-services
    labels:
      justdial: "Cloud-Services"
      indiamart: "cloud-computing-services"
      tradeindia: "cloud-computing"
  - slug: seo-services
    labels:
      justdial: "SEO-Services"
      indiamart: "seo-services"
      tradeindia: "seo-services"
  - slug: erp-solutions
    labels:
      justdial: "ERP-Solutions"
      indiamart: "erp-software-solutions"
      tradeindia: "erp-software"
  - slug: cybersecurity
    labels:
      justdial: "Cyber-Security"
      indiamart: "cyber-security-services"
      tradeindia: "cyber-security"
  - slug: data-analytics
    labels:
      justdial: "Data-Analytics"
      indiamart: "data-analytics-services"
      tradeindia: "data-analytics"

cities:
  - slug: new-delhi
    labels:
      justdial: "Delhi"
      indiamart: "new-delhi"
      tradeindia: "new-delhi"
    tradeindia_code: "228067"
  - slug: mumbai
    labels:
      justdial: "Mumbai"
      indiamart: "mumbai"
      tradeindia: "mumbai"
    tradeindia_code: "207486"
  - slug: bangalore
    labels:
      justdial: "Bangalore"
      indiamart: "bangalore"
      tradeindia: "bengaluru"
    tradeindia_code: "183339"
  - slug: pune
    labels:
      justdial: "Pune"
      indiamart: "pune"
      tradeindia: "pune"
    tradeindia_code: "213577"
  - slug: hyderabad
    labels:
      justdial: "Hyderabad"
      indiamart: "hyderabad"
      tradeindia: "hyderabad"
    tradeindia_code: "196467"
  - slug: chennai
    labels:
      justdial: "Chennai"
      indiamart: "chennai"
      tradeindia: "chennai"
    tradeindia_code: "187278"
  - slug: kolkata
    labels:
      justdial: "Kolkata"
      indiamart: "kolkata"
      tradeindia: "kolkata"
    tradeindia_code: "200579"
  - slug: ahmedabad
    labels:
      justdial: "Ahmedabad"
      indiamart: "ahmedabad"
      tradeindia: "ahmedabad"
    tradeindia_code: "178823"
  - slug: jaipur
    labels:
      justdial: "Jaipur"
      indiamart: "jaipur"
      tradeindia: "jaipur"
    tradeindia_code: "197559"
  - slug: surat
    labels:
      justdial: "Surat"
      indiamart: "surat"
      tradeindia: "surat"
    tradeindia_code: "220891"

url_templates:
  justdial: "https://www.justdial.com/{city}/{category}/nct-10278073"
  indiamart: "https://dir.indiamart.com/{city}/{category}.html"
  tradeindia: "https://www.tradeindia.com/{city}/{category}-city-{code}.html"

icp_categories: []
icp_cities: []
```

## 6. Validation rules (enforced at load; fail loudly)

- `categories` and `cities` MUST each be non-empty for IndiaMART/TradeIndia expansion; if empty, `expand_start_urls` returns `[]` and an explicit warning is logged (spec Edge Case).
- Every `cities` entry MUST carry `tradeindia_code` when the TradeIndia target is enabled; a missing code for an enabled TradeIndia target fails loudly at load (missing codes are not silently skipped — spec fail-loud ethos).
- `icp_categories`/`icp_cities` MUST NOT influence crawl behavior in this phase (Phase 6 scoring only).
- `max_pages` MUST be ≥ 1 when present; `SCRAPE_FULL_PAGES` env is ignored entirely (FR-005/Q5).
