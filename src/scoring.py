from src.config import TARGET_INDUSTRY_LIST
from src.models import LeadRecord


def compute_lead_score(
    has_email: bool,
    has_phone: bool,
    employee_count: int | None,
    industry_code: str | None,
    target_industries: list[str] | None = None,
) -> int:
    """Compute a deterministic lead score (0-100) from record attributes.

    Scoring formula:
      - +40 if email is present
      - +20 if phone is present
      - +20 if employee_count is between 10 and 500 (inclusive)
      - +20 if industry_code is in the target industry list

    Args:
        has_email: Whether the record has an email address.
        has_phone: Whether the record has a phone number.
        employee_count: Employee count (may be None).
        industry_code: Industry classification code (may be None).
        target_industries: List of target industry codes. Defaults to
                          TARGET_INDUSTRY_LIST from config.

    Returns:
        Integer score between 0 and 100.
    """
    score = 0
    if has_email:
        score += 40
    if has_phone:
        score += 20
    if employee_count is not None and 10 <= employee_count <= 500:
        score += 20
    target_list = target_industries if target_industries is not None else TARGET_INDUSTRY_LIST
    if industry_code and industry_code in target_list:
        score += 20
    return min(score, 100)


def score_record(record: LeadRecord) -> int:
    """Compute the lead score for a single LeadRecord.

    Args:
        record: A LeadRecord instance.

    Returns:
        Integer score between 0 and 100.
    """
    return compute_lead_score(
        has_email=bool(record.email),
        has_phone=bool(record.phone),
        employee_count=record.employee_count,
        industry_code=record.industry_code,
    )


def score_all_records(records: list) -> list:
    """Compute and set lead_score on every record in the list (in-place).

    Args:
        records: List of LeadRecord instances.

    Returns:
        The same list with lead_score populated on each record.
    """
    for record in records:
        record.lead_score = score_record(record)
    return records
