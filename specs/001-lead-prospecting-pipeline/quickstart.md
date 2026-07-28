# Quickstart: Lead Prospecting Pipeline Validation Guide

## Prerequisites

- Python 3.11+
- Google Sheet created with the required tabs and headers (see [contracts/google-sheet-schema.md](contracts/google-sheet-schema.md))
- Enrichment API key (must be validated for Indian company coverage — e.g., Clearbit, OpenCorporates)
- Google service account JSON key, base64-encoded
- Target sites configured in `config/targets.yml` (Indian directories only: Justdial, IndiaMART, TradeIndia, etc.)

## Setup

```bash
# Clone and install deps
pip install scrapling google-api-python-client google-auth pydantic httpx python-dotenv

# Set credentials
$env:GOOGLE_SA_KEY = "<base64-encoded-service-account-json>"
$env:ENRICH_API_KEY = "<your-api-key>"

# Set spreadsheet ID
$env:SHEET_ID = "<google-sheet-id>"

# Optional: set target sites config path
$env:TARGETS_CONFIG = "config/targets.yml"
```

## Validation Scenarios

### Scenario 1: Dry-Run Pipeline (Core Loop)

```bash
python -m src --dry-run
```

**Expected outcome**:
- Console logs show: scrape start per target, enrichment calls, dedup pass, score computation.
- Staging tab populated with rows containing all 12 columns.
- No rows written to production tab.
- `scrape_errors` tab is empty (if all targets succeeded).

**Pass criteria**: Every row has `company_name` populated, `dedup_key` is a valid normalized domain, `lead_score` is 0–100 integer.

### Scenario 2: Idempotency Check

```bash
python -m src --dry-run
python -m src --dry-run
```

**Expected outcome**: Second run produces zero new rows in staging tab (all dedup_keys already present).

**Pass criteria**: Staging row count is identical after both runs.

### Scenario 3: Malformed Input Handling

Create a target parser that returns a record with empty `company_name` and another with both `email` and `phone` empty.

```bash
python -m src --dry-run
```

**Expected outcome**: Both malformed rows are silently skipped (not written to staging tab). No exceptions raised.

**Pass criteria**: Console log mentions "Rejected row: company_name is empty" and "Rejected row: both email and phone empty".

### Scenario 4: Single Target Failure

Configure one target URL that is unreachable.

```bash
python -m src --dry-run
```

**Expected outcome**: The unreachable target is retried 3 times, logged to `scrape_errors`, remaining targets complete normally. Staging tab contains data from successful targets.

**Pass criteria**: `scrape_errors` tab has 1 row with the failed URL. Staging tab has rows from other targets.

## Running on Schedule

### Via Cron (Production)

```cron
0 6 * * 1 cd /path/to/project && python -m src >> /var/log/lead-prospecting.log 2>&1
```

### Via APScheduler (Development)

```bash
python -m src --scheduler --interval-days 1
```

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_SA_KEY` | Yes | Base64-encoded service account JSON |
| `ENRICH_API_KEY` | Yes | Enrichment provider API key |
| `SHEET_ID` | Yes | Google Spreadsheet ID |
| `TARGETS_CONFIG` | No | Path to target sites YAML config (default: `config/targets.yml`) |
| `LOG_LEVEL` | No | Python log level (default: `INFO`) |
