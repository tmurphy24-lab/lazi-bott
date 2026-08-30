"""
Lazi-Bot Scrapers — Cross-Platform Job Discovery
================================================
scrapers/
    __init__.py       — registry + factory (get_scraper())
    base.py           — AbstractScraper, JobListing, RateLimiter, ProxyRotator
    linkedin.py       — LinkedIn scraper (refactored from scraper.py)
    indeed.py         — Indeed scraper
    glassdoor.py     — Glassdoor scraper
    remoteok.py       — RemoteOK scraper
    utils.py          — shared utilities (user-agent rotation, retry logic, etc.)

Usage:
    from app.scrapers import get_scraper

    scraper = get_scraper("linkedin", headless=True)
    jobs = scraper.search(positions=["Supply Chain Manager"], location="Chicago, IL")

    for scraper_name in ["linkedin", "indeed", "glassdoor", "remoteok"]:
        s = get_scraper(scraper_name)
        jobs.extend(s.search(positions=["Director of Operations"], location="Remote"))
"""

from __future__ import annotations

from app.scrapers.base import (
    AbstractScraper,
    JobListing,
    RateLimiter,
    ProxyRotator,
    Platform,
)
from app.scrapers.linkedin import LinkedInScraper
from app.scrapers.indeed import IndeedScraper
from app.scrapers.glassdoor import GlassdoorScraper
from app.scrapers.remoteok import RemoteOKScraper

__all__ = [
    "AbstractScraper",
    "JobListing",
    "RateLimiter",
    "ProxyRotator",
    "Platform",
    "LinkedInScraper",
    "IndeedScraper",
    "GlassdoorScraper",
    "RemoteOKScraper",
    "get_scraper",
]

_SCRAPER_REGISTRY: dict[str, type[AbstractScraper]] = {
    "linkedin": LinkedInScraper,
    "indeed": IndeedScraper,
    "glassdoor": GlassdoorScraper,
    "remoteok": RemoteOKScraper,
}


def get_scraper(
    platform: str,
    *,
    headless: bool = False,
    user_data_dir: str | None = None,
    timeout: int = 30,
    max_retries: int = 3,
) -> AbstractScraper:
    """
    Factory: instantiate the correct scraper by platform name.

    Args:
        platform: One of "linkedin", "indeed", "glassdoor", "remoteok"
        headless: Run browser headless
        user_data_dir: Optional Chrome profile dir (LinkedIn only)
        timeout: Page-load timeout in seconds
        max_retries: Retry attempts on failure

    Returns:
        An AbstractScraper subclass instance

    Raises:
        ValueError: Unknown platform
    """
    platform = platform.lower().strip()
    scraper_cls = _SCRAPER_REGISTRY.get(platform)
    if scraper_cls is None:
        available = ", ".join(sorted(_SCRAPER_REGISTRY))
        raise ValueError(
            f"Unknown platform: {platform!r}. Available: {available}"
        )
    return scraper_cls(
        headless=headless,
        user_data_dir=user_data_dir,
        timeout=timeout,
        max_retries=max_retries,
    )


def all_platforms() -> list[str]:
    """Return sorted list of supported platform names."""
    return sorted(_SCRAPER_REGISTRY)
