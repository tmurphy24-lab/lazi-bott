"""
Glassdoor Scraper — Lazi-Bot Scrapers
======================================
Scrapes Glassdoor.com job listings.
Note: Glassdoor has strong anti-bot protection; login may be required.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote

from app.scrapers.base import (
    AbstractScraper,
    JobListing,
    Platform,
)

logger = logging.getLogger(__name__)

JOB_CARD_CSS = "li[data-test='job-listing']"
TITLE_CSS = "[data-test='job-title']"
COMPANY_CSS = "[data-test='employer-name']"
LOCATION_CSS = "[data-test='job-location']"
SALARY_CSS = "[data-test='job-salary']"
LINK_CSS = "a[data-test='job-link']"


class GlassdoorScraper(AbstractScraper):
    platform = Platform.GLASSDOOR
    BASE_DELAY = 5.0

    def _make_driver(self) -> webdriver.Chrome:
        opts = self._build_options()
        proxy = self.proxy_rotator.next() if self.proxy_rotator else None
        if proxy:
            opts.add_argument(f"--proxy-server={proxy}")
        svc = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.set_page_load_timeout(self.timeout)
        driver.set_window_size(1920, 1080)
        return driver

    def _build_url(self, position: str, location: str) -> str:
        q = quote(position)
        l = quote(location)
        return f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&sc.location={l}"

    def _search_impl(
        self,
        position: str,
        location: str,
        max_jobs: int,
        max_days_old: int,
        require_remote: bool,
    ) -> list[JobListing]:
        url = self._build_url(position, location)
        logger.info("[Glassdoor] GET %s", url)

        self._apply_rate_limit()
        self.driver.get(url)
        time.sleep(3)

        results: list[JobListing] = []

        # Scroll to load results
        for _ in range(3):
            self.driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1.5)

        cards = self.driver.find_elements(By.CSS_SELECTOR, JOB_CARD_CSS)
        logger.info("[Glassdoor] Found %d job cards", len(cards))

        for card in cards[:max_jobs]:
            job = self._parse_card(card)
            if not job:
                continue
            if not job.matches_filter(max_days_old, require_remote):
                continue
            results.append(job)

        return results

    def _parse_card(self, card: Any) -> JobListing | None:
        try:
            link_elem = card.find_element(By.CSS_SELECTOR, LINK_CSS)
            link = link_elem.get_attribute("href") or ""
            title = link_elem.find_element(By.CSS_SELECTOR, TITLE_CSS).text.strip()
        except NoSuchElementException:
            return None

        if not link or not title:
            return None

        company = ""
        try:
            company = card.find_element(By.CSS_SELECTOR, COMPANY_CSS).text.strip()
        except NoSuchElementException:
            pass

        location = ""
        try:
            location = card.find_element(By.CSS_SELECTOR, LOCATION_CSS).text.strip()
        except NoSuchElementException:
            pass

        salary_text = ""
        try:
            salary_text = card.find_element(By.CSS_SELECTOR, SALARY_CSS).text.strip()
        except NoSuchElementException:
            pass

        text_lower = (title + " " + company + " " + location).lower()
        remote = any(k in text_lower for k in ["remote", "work from home", "anywhere"])
        hybrid = "hybrid" in text_lower

        return JobListing(
            platform=Platform.GLASSDOOR,
            title=title,
            company=company,
            location=location,
            link=link,
            salary_text=salary_text,
            remote=remote,
            hybrid=hybrid,
        )

    def _build_options(self) -> Options:
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        return opts
