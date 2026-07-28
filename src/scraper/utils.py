import re
import time
from functools import wraps
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

RFC_5322_LITE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_robots_cache: dict[str, RobotFileParser] = {}


def is_robots_allowed(url: str, user_agent: str = "LeadProspectingBot") -> bool:
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
    if not website:
        return None
    domain = website.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.rstrip("/")


def is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(RFC_5322_LITE.match(email.strip()))


def flag_invalid_email(email: str | None) -> str | None:
    if not email:
        return None
    if is_valid_email(email):
        return email.strip()
    return f"UNVERIFIED:{email.strip()}"


def retry(max_attempts: int = 3, base_delay: float = 1.0, backoff: float = 4.0):
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
