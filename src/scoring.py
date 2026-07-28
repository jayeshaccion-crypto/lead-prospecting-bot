from src.config import TARGET_INDUSTRY_LIST
from src.models import LeadRecord


def compute_lead_score(
    has_email: bool,
    has_phone: bool,
    employee_count: int | None,
    industry_code: str | None,
    target_industries: list[str] | None = None,
) -> int:
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
    return compute_lead_score(
        has_email=bool(record.email),
        has_phone=bool(record.phone),
        employee_count=record.employee_count,
        industry_code=record.industry_code,
    )


def score_all_records(records: list) -> list:
    for record in records:
        record.lead_score = score_record(record)
    return records
