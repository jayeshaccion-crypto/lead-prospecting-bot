import logging
from typing import NamedTuple

from src.models import LeadRecord
from src.scraper.utils import is_valid_email

logger = logging.getLogger(__name__)


class InvalidRecord(NamedTuple):
    """A record that failed validation along with the rejection reason.

    Attributes:
        record: The LeadRecord that was rejected.
        reason: A human-readable string explaining why it was rejected.
    """
    record: LeadRecord
    reason: str


def validate_record(record: LeadRecord) -> tuple[bool, str | None]:
    """Validate a single LeadRecord against business rules.

    Rules:
      - company_name must be non-empty (after stripping whitespace)
      - At least one of email/phone must be present (whitespace-only
        phone is treated as absent)

    Args:
        record: A LeadRecord instance.

    Returns:
        Tuple of (is_valid, reason). If valid, reason is None.
        If invalid, reason is a string describing the failure.
    """
    if not record.company_name or not record.company_name.strip():
        return (False, "Empty company_name")

    phone = record.phone.strip() if record.phone and record.phone.strip() else None
    if not record.email and not phone:
        return (False, "Missing both email and phone")

    return (True, None)


def filter_valid_records(
    records: list[LeadRecord],
) -> tuple[list[LeadRecord], list[InvalidRecord]]:
    """Separate records into valid and invalid lists, flagging bad emails.

    Valid records with invalid email format get their email prefixed with
    "UNVERIFIED:". Invalid records are wrapped in InvalidRecord with a
    reason string and logged as warnings.

    Args:
        records: List of LeadRecord instances.

    Returns:
        Tuple of (valid_records, invalid_records). The valid list contains
        records that passed all validation rules. The invalid list contains
        InvalidRecord tuples with the failing record and reason.
    """
    valid = []
    invalid = []
    for record in records:
        is_valid, reason = validate_record(record)
        if is_valid:
            if record.email and not is_valid_email(record.email):
                record = record.model_copy(update={"email": f"UNVERIFIED:{record.email.strip()}"})
            valid.append(record)
        else:
            invalid.append(InvalidRecord(record, reason))
            logger.warning(
                "Record '%s' rejected by validation: %s",
                record.company_name or "(no name)", reason,
            )
    logger.info(
        "Validation: %d valid, %d invalid records",
        len(valid), len(invalid),
    )
    return valid, invalid
