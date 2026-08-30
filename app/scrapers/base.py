"""
Base Scraper Framework — Lazi-Bot Scrapers
==========================================
Abstract base class + shared data models + infrastructure.
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Platform Enum
# ══════════════════════════════════════════════════════════════════════════════


class Platform(str, Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    REMOTEOK = "remoteok"
    UNKNOWN = "unknown"


# ══════════════════════════════════════════════════════════════════════════════
#  Job Listing Model
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class JobListing:
    """
    Universal job listing — platform-agnostic.
    Every field is optional; scrapers populate what they can.
    """

    # Identity
    platform: Platform = Platform.UNKNOWN
    platform_job_id: str = ""

    # Core fields
    title: str = ""
    company: str = ""
    location: str = ""
    link: str = ""

    # Compensation
    salary_min: int | None = None
    salary_max: int | None = None
    salary_text: str = ""

    # Metadata
    description: str = ""
    posted_at: datetime | None = None  # aware UTC datetime
    posted_days_ago: int | None = None
    job_type: str = ""  # "full-time", "contract", "part-time", "internship"

    # Tags
    remote: bool = False
    hybrid: bool = False
    keywords: list[str] = field(default_factory=list)

    # Scraping provenance
    scraped_at: str = ""  # ISO UTC
    scraper_version: str = "1.0.0"
    search_position: str = ""  # e.g. "Director of Supply Chain"
    search_location: str = ""

    # Internal
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = _utcnow()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["platform"] = self.platform.value if isinstance(self.platform, Platform) else self.platform
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return d

    @property
    def platform_display(self) -> str:
        return self.platform.value.capitalize()

    @property
    def salary_display(self) -> str:
        if self.salary_text:
            return self.salary_text
        if self.salary_min and self.salary_max:
            return f"${self.salary_min:,} – ${self.salary_max:,}"
        if self.salary_min:
            return f"${self.salary_min:,}+"
        return "Not disclosed"

    @property
    def is_recent(self) -> bool:
        if self.posted_days_ago is None:
            return True
        return self.posted_days_ago <= 14

    def matches_filter(self, max_days_old: int = 30, require_remote: bool = False) -> bool:
        if require_remote and not self.remote:
            return False
        if self.posted_days_ago is not None and self.posted_days_ago > max_days_old:
            return False
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  Rate Limiter
# ══════════════════════════════════════════════════════════════════════════════


class RateLimiter:
    """
    Per-domain request throttler with jitter.

    Usage:
        limiter = RateLimiter(min_delay=5.0, jitter=2.0)
        limiter.wait("linkedin.com")   # sleeps 5-7 seconds
    """

    DEFAULT_DELAYS: dict[str, float] = {
        "linkedin.com": 6.0,
        "indeed.com": 4.0,
        "glassdoor.com": 5.0,
        "remoteok.com": 3.0,
    }

    def __init__(self, min_delay: float = 5.0, jitter: float = 2.0):
        self.min_delay = min_delay
        self.jitter = jitter
        self._last_request: dict[str, float] = {}

    def wait(self, domain: str) -> None:
        """Block until the rate-limit delay for the given domain has elapsed."""
        import random

        base_delay = self.DEFAULT_DELAYS.get(domain, self.min_delay)
        total_delay = base_delay + random.uniform(0, self.jitter)

        last = self._last_request.get(domain, 0)
        elapsed = time.monotonic() - last
        sleep_time = max(0, total_delay - elapsed)

        if sleep_time > 0:
            logger.debug("[RateLimiter] Sleeping %.1fs for %s", sleep_time, domain)
            time.sleep(sleep_time)

        self._last_request[domain] = time.monotonic()

    def reset(self, domain: str) -> None:
        """Reset the last-request timestamp for a domain."""
        self._last_request[domain] = 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  Proxy Rotator
# ══════════════════════════════════════════════════════════════════════════════


class ProxyRotator:
    """
    Rotates through a list of HTTP(S) proxies.

    Usage:
        rotator = ProxyRotator(["http://p1:3128", "http://p2:3128"])
        proxy = rotator.next()

    If no proxies are configured, next() returns None (direct connection).
    """

    def __init__(self, proxies: list[str] | None = None):
        self._proxies = proxies or []
        self._index = 0

    def next(self) -> str | None:
        if not self._proxies:
            return None
        proxy = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return proxy

    def add(self, proxy: str) -> None:
        if proxy not in self._proxies:
            self._proxies.append(proxy)

    @property
    def count(self) -> int:
        return len(self._proxies)


# ══════════════════════════════════════════════════════════════════════════════
#  Abstract Scraper
# ══════════════════════════════════════════════════════════════════════════════


class AbstractScraper(ABC):
    """
    Abstract base for all platform scrapers.

    Subclasses MUST implement:
        _search_impl()   — core scraping logic, returns list[JobListing]
        platform          — Platform enum value

    Subclasses SHOULD override:
        _login()         — authenticate if needed
        _build_url()     — build search URL from positions + location
        validate_session() — verify session is still valid
    """

    platform: Platform = Platform.UNKNOWN
    BASE_DELAY = 5.0  # seconds between requests

    def __init__(
        self,
        *,
        headless: bool = False,
        user_data_dir: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        rate_limiter: RateLimiter | None = None,
        proxy_rotator: ProxyRotator | None = None,
        driver: Any = None,  # selenium WebDriver, injected for testing
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = rate_limiter or RateLimiter(min_delay=self.BASE_DELAY)
        self.proxy_rotator = proxy_rotator
        self._driver = driver
        self._logged_in = False

    # ── Public API ─────────────────────────────────────────────────────────

    def search(
        self,
        positions: list[str],
        location: str,
        max_jobs: int = 25,
        max_days_old: int = 30,
        require_remote: bool = False,
    ) -> list[JobListing]:
        """
        Main entry point. Searches for jobs across all positions.

        Args:
            positions: List of job titles to search (joined with OR on most platforms)
            location: Location string
            max_jobs: Maximum number of jobs to return
            max_days_old: Skip jobs older than this
            require_remote: Only return remote jobs

        Returns:
            List of JobListing objects
        """
        results: list[JobListing] = []
        seen_links: set[str] = set()

        for position in positions:
            try:
                listings = self._search_with_retry(
                    position=position,
                    location=location,
                    max_jobs=max_jobs,
                    max_days_old=max_days_old,
                    require_remote=require_remote,
                )
                for job in listings:
                    if job.link and job.link not in seen_links:
                        seen_links.add(job.link)
                        results.append(job)
            except Exception as exc:
                logger.warning(
                    "[%s] Search failed for position %r: %s",
                    self.platform.value,
                    position,
                    exc,
                )

        logger.info(
            "[%s] search(%r, %r) → %d jobs",
            self.platform.value,
            positions,
            location,
            len(results),
        )
        return results

    def search_one(
        self,
        position: str,
        location: str,
        max_days_old: int = 30,
    ) -> list[JobListing]:
        """Single-position search shorthand."""
        return self.search(
            positions=[position],
            location=location,
            max_days_old=max_days_old,
        )

    @property
    def driver(self) -> Any:
        """Lazy WebDriver initialization."""
        if self._driver is None:
            self._driver = self._make_driver()
        return self._driver

    def quit(self) -> None:
        """Close the WebDriver if we own it."""
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
            self._logged_in = False

    def __enter__(self) -> "AbstractScraper":
        return self

    def __exit__(self, *args: Any) -> None:
        self.quit()

    # ── Abstract Methods ──────────────────────────────────────────────────

    @abstractmethod
    def _search_impl(
        self,
        position: str,
        location: str,
        max_jobs: int,
        max_days_old: int,
        require_remote: bool,
    ) -> list[JobListing]:
        """Platform-specific scraping logic. Override in subclass."""
        ...

    @abstractmethod
    def _make_driver(self) -> Any:
        """Create and return a selenium WebDriver. Override in subclass."""
        ...

    # ── Protected Helpers ────────────────────────────────────────────────

    def _search_with_retry(
        self,
        position: str,
        location: str,
        max_jobs: int,
        max_days_old: int,
        require_remote: bool,
    ) -> list[JobListing]:
        """Wrapper that retries on transient failures."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                listings = self._search_impl(
                    position, location, max_jobs, max_days_old, require_remote
                )
                # Tag every listing with search provenance
                for job in listings:
                    job.search_position = position
                    job.search_location = location
                return listings
            except Exception as exc:
                last_exc = exc
                wait = (attempt + 1) * 3.0
                logger.warning(
                    "[%s] Attempt %d/%d failed for %r: %s — retrying in %.0fs",
                    self.platform.value,
                    attempt + 1,
                    self.max_retries,
                    position,
                    exc,
                    wait,
                )
                time.sleep(wait)

        # All retries exhausted — return empty with logged failure
        logger.error(
            "[%s] All %d attempts failed for %r: %s",
            self.platform.value,
            self.max_retries,
            position,
            last_exc,
        )
        return []

    def _apply_rate_limit(self) -> None:
        """Apply per-domain rate limiting."""
        domain = self.platform.value
        self.rate_limiter.wait(domain)

    def validate_session(self) -> bool:
        """
        Verify the session is still valid.
        Default: always returns True.
        Subclasses should override if they can detect session expiry.
        """
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  Utilities
# ══════════════════════════════════════════════════════════════════════════════


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_salary_range(raw: str) -> tuple[int | None, int | None, str]:
    """
    Parse a salary string like '$120,000 - $150,000 a year' into min/max.

    Returns (min, max, original_text)
    """
    import re

    if not raw:
        return None, None, ""

    cleaned = raw.strip()
    numbers: list[int] = []

    # Match numbers with optional K/k suffix
    for match in re.finditer(r"\$?([\d,]+)(?:K|k)?", raw):
        raw_num = match.group(1).replace(",", "")
        try:
            value = int(raw_num)
            # Treat as thousands if it looks like it (e.g. $150K → 150000)
            if value < 10000 and "K" in raw[max(0, match.start() - 2) : match.end() + 1]:
                value *= 1000
            numbers.append(value)
        except ValueError:
            continue

    if len(numbers) >= 2:
        return min(numbers), max(numbers), cleaned
    if len(numbers) == 1:
        return numbers[0], None, cleaned
    return None, None, cleaned
