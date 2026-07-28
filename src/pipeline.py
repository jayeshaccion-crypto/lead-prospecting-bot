import logging
import sys
import time
from collections import defaultdict

from src.config import load_targets_config
from src.models import LeadRecord, RejectedDuplicate, ScrapeError, now_utc
from src.validation import filter_valid_records

logger = logging.getLogger(__name__)

ENRICHMENT_FIELDS = ["employee_count", "revenue_band"]


class PipelineThresholdError(Exception):
    """Raised when the failure threshold check fails during pipeline run."""


def _enrichment_field_count(record: LeadRecord) -> int:
    """Count how many enrichment fields are populated on a record.

    Args:
        record: A LeadRecord instance.

    Returns:
        Number of populated enrichment fields (0-2).
    """
    return sum(
        1 for field in ENRICHMENT_FIELDS if getattr(record, field, None) is not None
    )


def deduplicate_records(
    records: list[LeadRecord],
) -> tuple[list[LeadRecord], list[RejectedDuplicate]]:
    """Deduplicate records by dedup_key, keeping the richer record on collision.

    Groups records by dedup_key. For single-record groups the record is kept
    as-is. For collisions, the record with more populated enrichment fields
    (employee_count, revenue_band) is kept; ties are broken alphabetically.
    Records without a dedup_key are passed through as-is.

    Args:
        records: List of LeadRecord instances.

    Returns:
        Tuple of (kept_records, rejected_duplicates).
    """
    groups: dict[str, list[LeadRecord]] = defaultdict(list)
    records_without_key: list[LeadRecord] = []

    for record in records:
        if record.dedup_key and record.dedup_key.strip():
            groups[record.dedup_key].append(record)
        else:
            if record.dedup_key is not None and record.dedup_key != "":
                logger.warning(
                    "Record '%s' has empty dedup_key, included as-is",
                    record.company_name,
                )
            records_without_key.append(record)

    kept: list[LeadRecord] = []
    rejected: list[RejectedDuplicate] = []

    for dedup_key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
        else:
            group.sort(
                key=lambda r: (-_enrichment_field_count(r), r.company_name),
            )
            keeper = group[0]
            keeper_count = _enrichment_field_count(keeper)
            kept.append(keeper)
            for loser in group[1:]:
                loser_count = _enrichment_field_count(loser)
                if loser_count < keeper_count:
                    reason = f"Fewer enrichment fields ({loser_count} vs {keeper_count})"
                else:
                    reason = f"Tied at {loser_count} enrichment fields, rejected alphabetically"
                rejected.append(
                    RejectedDuplicate(
                        dedup_key=dedup_key,
                        kept_company=keeper.company_name,
                        rejected_company=loser.company_name,
                        reason=reason,
                        timestamp=now_utc(),
                    )
                )

    kept.extend(records_without_key)

    return kept, rejected


def record_to_row(record: LeadRecord) -> list:
    """Convert a LeadRecord to a flat row list matching the sheet schema.

    None fields are replaced with empty strings. Numeric fields
    (employee_count, lead_score) are converted to strings.

    Returns:
        A 12-element list matching the sheet column order.
    """

    return [
        record.company_name,
        record.website or "",
        record.email or "",
        record.phone or "",
        record.address or "",
        record.industry_code or "",
        str(record.employee_count) if record.employee_count is not None else "",
        record.revenue_band or "",
        record.source_url or "",
        record.scraped_at.isoformat() if record.scraped_at else "",
        record.dedup_key or "",
        str(record.lead_score) if record.lead_score is not None else "",
    ]


def rejected_to_row(rejected: RejectedDuplicate) -> list:
    """Convert a RejectedDuplicate to a flat row list for the sheet.

    None fields are replaced with empty strings.

    Returns:
        A 5-element list: dedup_key, kept_company, rejected_company,
        reason, and timestamp (isoformat).
    """

    return [
        rejected.dedup_key,
        rejected.kept_company,
        rejected.rejected_company,
        rejected.reason,
        rejected.timestamp.isoformat() if rejected.timestamp else "",
    ]


def write_rejected_duplicates(
    client, rejected: list[RejectedDuplicate], tab: str = "rejected_duplicates"
):
    """Write rejected duplicate records to the specified sheet tab.

    Args:
        client: A SheetsClient instance.
        rejected: List of RejectedDuplicate instances.
        tab: Target sheet tab name.
    """
    if not rejected:
        return
    rows = [rejected_to_row(r) for r in rejected]
    client.append_rows(tab, rows)
    logger.info("Wrote %d rejected duplicate rows to %s tab", len(rejected), tab)


def scrape_error_to_row(error: ScrapeError) -> list:
    """Convert a ScrapeError to a flat row list for the sheet."""

    return [
        error.url,
        error.timestamp.isoformat() if error.timestamp else "",
        error.error_type or "",
    ]


def check_failure_threshold(
    errors: list | int, total_targets: int | None = None
) -> bool:
    """Check if error rate exceeds 30% threshold.

    Args:
        errors: A list of error objects (uses len()) or an integer error count.
        total_targets: Total number of scrape targets. If None, loaded from config.

    Returns:
        True if failure rate is within threshold (<=30%), False otherwise.
        Also returns True if total_targets is 0 (no targets configured).
    """
    if total_targets is None:
        total_targets = len(load_targets_config())
    if total_targets == 0:
        return True
    error_count = len(errors) if not isinstance(errors, int) else errors
    failure_rate = error_count / total_targets
    if failure_rate > 0.3:
        logger.critical(
            "Failure rate %.0f%% (%d/%d targets) exceeds 30%% threshold. Aborting promotion.",
            failure_rate * 100, error_count, total_targets,
        )
        return False
    logger.info(
        "Failure rate %.0f%% (%d/%d targets) — within threshold.",
        failure_rate * 100, error_count, total_targets,
    )
    return True


def promote_to_production(client=None, skip_threshold_check=False):
    """Copy staging rows to the Leads tab with dedup and threshold check.

    When called without skip_threshold_check (e.g. standalone --promote),
    reads scrape_errors from the sheet and checks the failure threshold
    before promoting. When called from main_pipeline, the caller already
    performed the check so set skip_threshold_check=True.
    """
    from src.database.client import DatabaseClient

    if client is None:
        client = DatabaseClient()

    if not skip_threshold_check:
        try:
            error_rows = client.get_all_rows("scrape_errors")
            if error_rows and len(error_rows) > 1:
                urls = {row[0].strip() for row in error_rows[1:] if row and len(row) > 0 and row[0].strip()}
                error_count = len(urls)
            else:
                error_count = 0
        except Exception:
            error_count = 0
        total_targets = len(load_targets_config())
        if not check_failure_threshold(error_count, total_targets=total_targets):
            logger.critical("Promotion aborted — failure rate exceeds 30%% threshold")
            return

    try:
        staging_rows = client.get_all_rows("staging")
    except Exception:
        logger.info("Staging tab not found — nothing to promote")
        return
    if len(staging_rows) <= 1:
        logger.info("Nothing to promote — staging tab is empty or has only headers")
        return
    data_rows = [row for row in staging_rows[1:] if any(cell.strip() for cell in row)]
    if not data_rows:
        logger.info("Nothing to promote — staging tab has no data rows")
        return
    written = client.append_if_not_duplicate("Leads", data_rows)
    logger.info(
        "Promoted %d rows from staging to Leads (skipped %d duplicates)",
        len(written), len(data_rows) - len(written),
    )


def run_summary(
    raw_count: int,
    enriched_count: int,
    kept_count: int,
    rejected_dup_count: int,
    error_count: int,
    invalid_count: int,
) -> dict:
    """Build a structured summary dict for the pipeline run.

    Args:
        raw_count: Number of raw scraped records.
        enriched_count: Number of records with at least one enrichment field.
        kept_count: Number of records that passed dedup and validation.
        rejected_dup_count: Number of duplicates rejected by dedup.
        error_count: Number of scrape target errors.
        invalid_count: Number of records rejected by validation.

    Returns:
        Dict with string keys and integer values.
    """
    return {
        "scraped": raw_count,
        "enriched_count": enriched_count,
        "kept_after_validation": kept_count,
        "rejected_duplicates": rejected_dup_count,
        "errors": error_count,
        "invalid_records": invalid_count,
    }


def raw_record_to_lead(record) -> "LeadRecord":
    """Convert a RawRecord to a LeadRecord with computed dedup_key and timestamp."""
    from urllib.parse import urlparse

    from src.models import LeadRecord, now_utc

    existing_dedup = getattr(record, "dedup_key", None) or ""
    web = record.website or ""
    dedup_key = ""
    if existing_dedup:
        dedup_key = existing_dedup
    elif web:
        try:
            parsed = urlparse(web)
            host = parsed.netloc.lower() or web.lower()
            host = host.removeprefix("www.").split("/")[0]
            dedup_key = host
        except Exception:
            dedup_key = web.lower()

    return LeadRecord.model_construct(
        company_name=record.company_name,
        website=record.website,
        email=record.email,
        phone=record.phone,
        address=record.address,
        industry_code=record.industry_code,
        employee_count=getattr(record, "employee_count", None),
        revenue_band=getattr(record, "revenue_band", None),
        source_url=record.source_url,
        scraped_at=now_utc(),
        dedup_key=dedup_key,
    )


def main_pipeline(dry_run: bool = False) -> dict:
    """Run the full lead prospecting pipeline.

    Orchestrates: scrape → enrich → dedup → validate → score → write staging.
    On non-dry-run, checks failure threshold and promotes to production.
    Logs elapsed time at each phase.

    Args:
        dry_run: If True, writes only to staging tab; skips promotion.

    Returns:
        Summary dict with pipeline run counts.

    Raises:
        PipelineThresholdError: If failure rate exceeds 30% on non-dry-run.
    """
    from src.database.client import DatabaseClient
    from src.database.tabs import ensure_all_tabs, write_staging
    from src.scraper.engine import scrape_all_targets
    from src.scoring import score_all_records

    _start = time.perf_counter()
    logger.info("Pipeline started (dry_run=%s)", dry_run)

    client = DatabaseClient()
    ensure_all_tabs(client)
    logger.info("Setup complete (%.1fs)", time.perf_counter() - _start)

    raw_records, errors = scrape_all_targets()
    logger.info("Scraped %d raw records, %d target errors (%.1fs)", len(raw_records), len(errors), time.perf_counter() - _start)

    lead_records = [raw_record_to_lead(r) for r in raw_records]

    enriched_count = sum(
        1 for r in lead_records
        if r.employee_count is not None or r.revenue_band is not None
    )

    kept, rejected_dups = deduplicate_records(lead_records)
    logger.info(
        "After dedup: %d kept, %d rejected duplicates (%.1fs)",
        len(kept), len(rejected_dups), time.perf_counter() - _start,
    )

    valid_records, invalid_rejected = filter_valid_records(kept)
    score_all_records(valid_records)

    lead_rows = [record_to_row(r) for r in valid_records]
    error_rows = [scrape_error_to_row(e) for e in errors]
    rejected_rows = [rejected_to_row(r) for r in rejected_dups]

    write_staging(client, lead_rows)

    if error_rows:
        client.append_rows("scrape_errors", error_rows)
        logger.info("Wrote %d scrape errors", len(error_rows))
    if rejected_rows:
        write_rejected_duplicates(client, rejected_dups)

    summary = run_summary(
        raw_count=len(raw_records),
        enriched_count=enriched_count,
        kept_count=len(valid_records),
        rejected_dup_count=len(rejected_dups),
        error_count=len(errors),
        invalid_count=len(invalid_rejected),
    )
    logger.info(
        "Pipeline complete — scraped=%(scraped)d enriched=%(enriched_count)d "
        "kept=%(kept_after_validation)d rejected_dups=%(rejected_duplicates)d "
        "errors=%(errors)d invalid=%(invalid_records)d (elapsed=%(elapsed).1fs)",
        {**summary, "elapsed": time.perf_counter() - _start},
    )

    if not dry_run:
        if check_failure_threshold(errors):
            promote_to_production(client, skip_threshold_check=True)
            logger.info("Pipeline promoted to production")
        else:
            logger.warning("Pipeline failed threshold check — promotion aborted")
            logger.info("Pipeline summary before abort: %s", summary)
            raise PipelineThresholdError(
                "Threshold check failed with %d errors" % len(errors),
            )

    summary["elapsed"] = round(time.perf_counter() - _start, 1)
    return summary
