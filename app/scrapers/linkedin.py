"""
LinkedIn Scraper — Lazi-Bot Scrapers
=====================================
Refactored from scraper.py — battle-tested XPath selectors, dual-selector fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException as SeleniumTimeout,
)

from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote

from app.scrapers.base import (
    AbstractScraper,
    JobListing,
    Platform,
    RateLimiter,
)

logger = logging.getLogger(__name__)

# ── Selectors (verified against 4-of-5 bots) ───────────────────────────────
PRIMARY_XPATH = '//li[@data-occludable-job-id]'
FALLBACK_CSS = "div[class*='base-card']"

TITLE_XPATH = './/a'
COMPANY_CSS = "h4"
TIME_XPATH = ".//time"


def _build_url(positions: list[str], location: str, salary_min: int | None = None) -> str:
    keywords = ", ".join(positions)
    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={quote(keywords)}"
        f"&location={quote(location)}&trk=public_jobs_jobs-search-bar-search-submit"
    )
    if salary_min:
        url += f"&salary={salary_min}"
    return url


class LinkedInScraper(AbstractScraper):
    platform = Platform.LINKEDIN
    BASE_DELAY = 6.0

    def __init__(self, **kwargs: Any):
        kwargs.setdefault("headless", False)
        super().__init__(**kwargs)
        self._chrome_options = self._build_options()

    # ── Abstract Methods ─────────────────────────────────────────────────

    def _make_driver(self) -> webdriver.Chrome:
        svc = Service(ChromeDriverManager().install())
        options = self._chrome_options
        if self.user_data_dir:
            options.add_argument(f"--user-data-dir={self.user_data_dir}")

        proxy = self.proxy_rotator.next() if self.proxy_rotator else None
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        driver = webdriver.Chrome(service=svc, options=options)
        driver.set_page_load_timeout(self.timeout)
        driver.set_window_size(1920, 1080)
        return driver

    def _search_impl(
        self,
        position: str,
        location: str,
        max_jobs: int,
        max_days_old: int,
        require_remote: bool,
    ) -> list[JobListing]:
        url = _build_url([position], location)
        logger.info("[LinkedIn] GET %s", url)

        self._apply_rate_limit()
        self.driver.get(url)

        # Dismiss cookie banner if present
        self._dismiss_cookies()

        # Scroll to trigger lazy-load (3 scrolls × 800px)
        for _ in range(3):
            self.driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(2)

        # Primary selector → fallback
        cards = self.driver.find_elements(By.XPATH, PRIMARY_XPATH)
        if not cards:
            logger.warning("[LinkedIn] Primary XPath 0 cards — trying fallback CSS")
            cards = self.driver.find_elements(By.CSS_SELECTOR, FALLBACK_CSS)

        logger.info("[LinkedIn] Found %d job cards", len(cards))
        results: list[JobListing] = []

        for card in cards[:max_jobs]:
            try:
                job = self._parse_card(card)
                if not job:
                    continue
                if not job.matches_filter(max_days_old, require_remote):
                    continue
                results.append(job)
            except Exception as exc:
                logger.warning("[LinkedIn] Card parse error: %s", exc)
                continue

        return results

    # ── Card Parsing ─────────────────────────────────────────────────────

    def _parse_card(self, card: Any) -> JobListing | None:
        # Link + title
        try:
            link_elem = card.find_element(By.XPATH, TITLE_XPATH)
            link = link_elem.get_attribute("href") or ""
            title = link_elem.text.strip()
        except NoSuchElementException:
            return None

        if not link or not title:
            return None

        # Company
        company = ""
        try:
            company = card.find_element(By.CSS_SELECTOR, COMPANY_CSS).text.strip()
        except NoSuchElementException:
            pass

        # Posted date
        posted_days: int | None = None
        try:
            time_elem = card.find_element(By.XPATH, TIME_XPATH)
            raw_dt = time_elem.get_attribute("datetime")
            if raw_dt and len(raw_dt) >= 10:
                from datetime import datetime

                posted_date = datetime.strptime(raw_dt[:10], "%Y-%m-%d")
                posted_days = (datetime.today() - posted_date).days
        except Exception:
            pass

        # Remote detection from text
        text_lower = card.text.lower()
        remote = any(
            kw in text_lower
            for kw in ["remote", "work from home", "wfh", "anywhere"]
        )
        hybrid = "hybrid" in text_lower

        return JobListing(
            platform=Platform.LINKEDIN,
            platform_job_id=card.get_attribute("data-occludable-job-id") or "",
            title=title,
            company=company,
            location="",  # not on card, requires detail page
            link=link,
            posted_days_ago=posted_days,
            remote=remote,
            hybrid=hybrid,
            job_type="full-time" if not remote else "remote",
        )

    # ── Helpers ────────────────────────────────────────────────────────

    def _dismiss_cookies(self) -> None:
        """Try to click 'Accept cookies' if the banner is visible."""
        selectors = [
            ("xpath", '//button[contains(., "Accept")]'),
            ("css", "button[data-test-modal-dialog-btn]"),
            ("css", "button[action-type='ACCEPT']"),
        ]
        for kind, sel in selectors:
            try:
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable(
                        (getattr(By, kind.upper()), sel) if hasattr(By, kind.upper()) else (By.XPATH, sel)
                    )
                )
                btn.click()
                time.sleep(1)
                break
            except Exception:
                continue

    def _build_options(self) -> Options:
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-automation")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-popup-blocking")
        # Suppress "Save password" bubble
        opts.add_experimental_option("credentials_enable_service", False)
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        return opts

    def validate_session(self) -> bool:
        """Check if LinkedIn session is still valid."""
        try:
            self.driver.get("https://www.linkedin.com/feed/", timeout=10)
            time.sleep(2)
            if "login" in self.driver.current_url.lower():
                logger.warning("[LinkedIn] Session appears expired — redirected to login")
                return False
            return True
        except Exception as exc:
            logger.warning("[LinkedIn] Session validation error: %s", exc)
            return False
