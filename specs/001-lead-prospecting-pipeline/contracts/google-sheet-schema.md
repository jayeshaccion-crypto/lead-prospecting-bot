# Google Sheet Schema Contract

## Sheet Tabs

### Production Tab (`Leads`)
Fixed 12-column schema, row 1 = headers:

| Col | Header | Description |
|-----|--------|-------------|
| A | company_name | Scraped company name |
| B | website | Company website URL |
| C | email | Contact email (prefixed `UNVERIFIED:` if invalid format) |
| D | phone | Contact phone |
| E | address | Physical address |
| F | industry_code | Industry classification |
| G | employee_count | Enriched employee count |
| H | revenue_band | Enriched revenue range |
| I | source_url | URL where record was scraped |
| J | scraped_at | ISO 8601 UTC scrape timestamp |
| K | dedup_key | Normalized domain for dedup |
| L | lead_score | Computed lead score (0–100) |

### Staging Tab (`staging`)
Same 12-column schema as production. Written every run before promotion.

### Scrape Errors Tab (`scrape_errors`)

| Col | Header | Description |
|-----|--------|-------------|
| A | url | Target URL that failed |
| B | timestamp | ISO 8601 UTC |
| C | error_type | Error classification |

### Rejected Duplicates Tab (`rejected_duplicates`)

| Col | Header | Description |
|-----|--------|-------------|
| A | dedup_key | Normalized domain that collided |
| B | kept_company | company_name of the kept record |
| C | rejected_company | company_name of the discarded record |
| D | reason | Why the row was discarded |
| E | timestamp | ISO 8601 UTC |

### LinkedIn Manual Tab (`linkedin_manual`)
Freeform tab. User imports LinkedIn CSV exports here. No v1 code reads from this tab — it exists for future use and manual cross-reference. Matched by `dedup_key`.

## API Contract: Sheets Client

```python
class SheetsClient:
    def __init__(self, credentials_json: str, spreadsheet_id: str):
        """
        credentials_json: decoded GOOGLE_SA_KEY
        spreadsheet_id: ID from sheet URL
        """

    def tab_exists(self, tab_name: str) -> bool: ...

    def ensure_tab(self, tab_name: str, headers: list[str]): ...

    def read_existing_dedup_keys(self, tab_name: str) -> set[str]: ...

    def append_rows(self, tab_name: str, rows: list[list]): ...

    def get_all_rows(self, tab_name: str) -> list[list]: ...
```
