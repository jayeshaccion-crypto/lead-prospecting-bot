from datetime import datetime, timezone

from src.models import LeadRecord


def compute_lead_score(
    has_phone: bool = False,
    has_email: bool = False,
    has_website: bool = False,
    multi_source_count: int = 0,
    first_seen: datetime | None = None,
    is_icp_category: bool = False,
    is_icp_city: bool = False,
) -> tuple[int, dict]:
    """Compute a deterministic lead score (0-100) with full breakdown.

    Scoring formula (exact — do not change weights without approval):
      has_phone:                          +25
      has_email:                          +15
      has_website:                        +15
      multi_source appears on 2+ sites:   +25
      multi_source appears on all 3:      +35   (pick higher tier only, not additive)
      recency: first_seen == today        +10
              within last 7 days           +5
              else                         +0
      ICP match: category or city matched +10   (if either configured)

    Args:
        has_phone: Whether the record has a phone number.
        has_email: Whether the record has an email address.
        has_website: Whether the record has a website URL.
        multi_source_count: Number of distinct source sites (0-3).
        first_seen: Date the company was first seen (None for new records).
        is_icp_category: Whether category is in ICP list.
        is_icp_city: Whether city is in ICP list.

    Returns:
        Tuple of (total_score, breakdown_dict).
    """
    breakdown = {}

    contact_score = 0
    if has_phone:
        contact_score += 25
        breakdown["has_phone"] = 25
    if has_email:
        contact_score += 15
        breakdown["has_email"] = 15
    if has_website:
        contact_score += 15
        breakdown["has_website"] = 15
    breakdown["contact"] = contact_score

    if multi_source_count >= 3:
        source_score = 35
        breakdown["multi_source"] = "all_3"
    elif multi_source_count >= 2:
        source_score = 25
        breakdown["multi_source"] = "2_sites"
    else:
        source_score = 0
        breakdown["multi_source"] = "single"
    breakdown["source_score"] = source_score

    if first_seen is None:
        recency_score = 10
        breakdown["recency"] = "new"
    else:
        now = datetime.now(timezone.utc)
        if first_seen.date() == now.date():
            recency_score = 10
            breakdown["recency"] = "today"
        elif (now - first_seen).days <= 7:
            recency_score = 5
            breakdown["recency"] = "last_7_days"
        else:
            recency_score = 0
            breakdown["recency"] = "older"
    breakdown["recency_score"] = recency_score

    icp_score = 10 if (is_icp_category or is_icp_city) else 0
    breakdown["icp_match"] = icp_score

    total = contact_score + source_score + recency_score + icp_score
    total = min(total, 100)
    breakdown["total"] = total

    return total, breakdown


def score_record(record: LeadRecord, is_icp_cat: bool = False, is_icp_city: bool = False) -> tuple[int, dict]:
    """Compute lead score + breakdown for a single LeadRecord.

    Args:
        record: A LeadRecord instance.
        is_icp_cat: Whether the record's category is in the ICP list.
        is_icp_city: Whether the record's city is in the ICP list.

    Returns:
        Tuple of (score, breakdown_dict).
    """
    sources = record.sources or []
    multi_source_count = len(sources) if sources else 0
    return compute_lead_score(
        has_phone=bool(record.phone),
        has_email=bool(record.email),
        has_website=bool(record.website),
        multi_source_count=multi_source_count,
        first_seen=record.first_seen,
        is_icp_category=is_icp_cat,
        is_icp_city=is_icp_city,
    )


def score_all_records(records: list, icp_categories: set | None = None, icp_cities: set | None = None) -> list:
    """Compute and set lead_score + breakdown on every record in-place.

    Args:
        records: List of LeadRecord instances.
        icp_categories: Set of ICP category slugs.
        icp_cities: Set of ICP city slugs.

    Returns:
        The same list with lead_score and lead_score_breakdown populated.
    """
    icp_categories = icp_categories or set()
    icp_cities = icp_cities or set()
    for record in records:
        is_icp_cat = (record.category_slug or "") in icp_categories
        is_icp_city = (record.city_slug or "") in icp_cities
        score, breakdown = score_record(record, is_icp_cat, is_icp_city)
        record.lead_score = score
        record.lead_score_breakdown = breakdown
    return records
