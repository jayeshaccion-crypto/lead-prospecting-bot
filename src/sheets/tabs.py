LEADS_HEADERS = [
    "company_name", "website", "email", "phone", "address",
    "industry_code", "employee_count", "revenue_band", "source_url",
    "scraped_at", "dedup_key", "lead_score",
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
        client.ensure_tab(name, headers)
    return created
