# Enrichment API Contract

## Configuration
- Base URL and API key are configurable via environment variables.
- One fixed provider per run — no silent provider fallback.
- API key sent as `Authorization: Bearer <ENRICH_API_KEY>` header.

## Request
```
GET /enrich?domain={normalized_domain}
Authorization: Bearer <ENRICH_API_KEY>
```

## Response (200 OK)
```json
{
  "domain": "example.com",
  "company_name": "Example Corp",
  "employee_count": 250,
  "revenue_band": "$10M-$50M"
}
```

All fields except `domain` may be null if the provider lacks data.

## Error Handling
- Non-200 responses → log warning, leave enrichment fields as null, continue.
- Timeout/network error → log warning, leave enrichment fields as null, continue.
- No retry for enrichment failures (scrape retries are for target fetches only).
