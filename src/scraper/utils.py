import re
import time
from functools import wraps
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

RFC_5322_LITE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_robots_cache: dict[str, RobotFileParser] = {}


def is_robots_allowed(url: str, user_agent: str = "LeadProspectingBot") -> bool:
    """Check robots.txt for the given URL, with caching per domain.

    Args:
        url: The URL to check.
        user_agent: The user agent string to use for the check.

    Returns:
        True if scraping is allowed, False if disallowed.
        Returns True if robots.txt is unreachable.
    """
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    if domain not in _robots_cache:
        robots_url = f"{domain}/robots.txt"
        rp = RobotFileParser(robots_url)
        try:
            rp.read()
        except Exception:
            return True
        _robots_cache[domain] = rp
    return _robots_cache[domain].can_fetch(user_agent, url)


def normalize_domain(website: str | None) -> str | None:
    """Normalize a website URL to a canonical domain string.

    Strips 'www.' prefix, trailing slash, lowercases, and trims whitespace.

    Args:
        website: A URL string or None.

    Returns:
        Normalized domain string, or None if input is None/empty.
    """
    if not website:
        return None
    domain = website.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.rstrip("/")


def is_valid_email(email: str | None) -> bool:
    """Check if an email matches the RFC 5322-lite pattern.

    Args:
        email: An email string or None.

    Returns:
        True if the email matches the pattern, False otherwise.
    """
    if not email:
        return False
    return bool(RFC_5322_LITE.match(email.strip()))


def flag_invalid_email(email: str | None) -> str | None:
    """Return a trimmed email, or prefix with 'UNVERIFIED:' if invalid.

    Args:
        email: An email string or None.

    Returns:
        None if email is None/empty.
        The trimmed email if valid.
        'UNVERIFIED:<trimmed_email>' if the format is invalid.
    """
    if not email:
        return None
    if is_valid_email(email):
        return email.strip()
    return f"UNVERIFIED:{email.strip()}"


def retry(max_attempts: int = 3, base_delay: float = 1.0, backoff: float = 4.0):
    """Decorator that retries a function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (default 3).
        base_delay: Initial delay in seconds (default 1.0).
        backoff: Multiplier applied to delay each attempt (default 4.0).

    Returns:
        The decorator function.

    Raises:
        The last exception caught after all attempts are exhausted.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = base_delay * (backoff ** attempt)
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
