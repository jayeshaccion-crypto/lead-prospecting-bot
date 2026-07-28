# Scraper Interface Contract

## Target Scraper Protocol

Each target site implements this interface:

```python
@dataclass
class ScrapeTarget:
    name: str              # Human-readable target name
    entry_url: str         # Starting URL
    parser: Callable       # Function: (html: str, source_url: str) -> list[RawRecord]
    fetch_kwargs: dict     # Extra kwargs for StealthyFetcher.fetch (e.g., pagination)

@dataclass
class RawRecord:
    company_name: str
    website: str | None
    email: str | None
    phone: str | None
    address: str | None
    industry_code: str | None
```

## Retry Policy
- 3 attempts per target: 1s, 4s, 16s exponential backoff.
- All attempts use same target URL.
- If all 3 fail → log to `scrape_errors`, continue to next target.

## Scrapling Configuration
```python
fetcher = StealthyFetcher(
    adaptive=True,
    robots_txt_obey=True,
)
```
