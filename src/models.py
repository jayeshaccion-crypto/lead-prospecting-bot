from datetime import datetime, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


def _is_valid_url(value: str | None) -> bool:
    """Check if a URL has a valid scheme and netloc. Returns True for None/empty."""
    if not value:
        return True
    try:
        result = urlparse(value)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


class LeadRecord(BaseModel):
    """A scraped, enriched, and scored lead record ready for sheet output."""

    company_name: str
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    industry_code: str | None = None
    employee_count: int | None = None
    revenue_band: str | None = None
    source_url: str | None = None
    scraped_at: datetime | None = None
    dedup_key: str | None = None
    lead_score: int | None = None

    @field_validator("company_name")
    @classmethod
    def company_name_must_not_be_empty(cls, v: str) -> str:
        """Validate that company_name is a non-empty, non-whitespace string."""
        if not v or not v.strip():
            raise ValueError("company_name must not be empty")
        return v.strip()

    @field_validator("website", "source_url")
    @classmethod
    def url_must_be_valid(cls, v: str | None) -> str | None:
        """Validate that website/source_url have a scheme and netloc when provided."""
        if v is not None and not _is_valid_url(v):
            raise ValueError(f"Invalid URL: {v}")
        return v

    @field_validator("lead_score")
    @classmethod
    def lead_score_in_range(cls, v: int | None) -> int | None:
        """Validate that lead_score is within 0-100 inclusive when provided."""
        if v is not None and not (0 <= v <= 100):
            raise ValueError("lead_score must be between 0 and 100")
        return v


class ScrapeError(BaseModel):
    """A record of a scrape failure for a specific target URL."""

    url: str
    timestamp: datetime | None = None
    error_type: str | None = None


class RejectedDuplicate(BaseModel):
    """A record of a duplicate that was rejected during deduplication."""

    dedup_key: str
    kept_company: str
    rejected_company: str
    reason: str
    timestamp: datetime | None = None


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)
