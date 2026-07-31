"""Tab management functions for the SQLite database client."""

import logging

logger = logging.getLogger(__name__)

LEADS_HEADERS = [
    "company_name", "website", "email", "phone", "address",
    "industry_code", "employee_count", "revenue_band", "source_url",
    "scraped_at", "dedup_key", "lead_score", "lead_score_breakdown",
    "city_slug",
]

SCRAPE_ERRORS_HEADERS = ["url", "timestamp", "error_type"]

REJECTED_DUPLICATES_HEADERS = [
    "dedup_key", "kept_company", "rejected_company", "reason", "timestamp",
]

STAGING_HEADERS = LEADS_HEADERS


def ensure_all_tabs(client) -> dict[str, bool]:
    tabs = {
        "Leads": LEADS_HEADERS,
        "staging": STAGING_HEADERS,
        "scrape_errors": SCRAPE_ERRORS_HEADERS,
        "rejected_duplicates": REJECTED_DUPLICATES_HEADERS,
    }
    created = {}
    for name, headers in tabs.items():
        created[name] = client.ensure_tab(name, headers)
    newly_created = [k for k, v in created.items() if v]
    if newly_created:
        logger.info("Created database tables: %s", ", ".join(newly_created))
    return created


def write_staging(client, lead_rows: list[list]):
    client.clear_tab("staging")
    rows = [STAGING_HEADERS, *lead_rows]
    client.append_rows("staging", rows)
    logger.info("Wrote %d rows (including header) to staging tab", len(rows))
