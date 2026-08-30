"""
RemoteOK Scraper — Lazi-Bot Scrapers
=====================================
Scrapes RemoteOK.com — great for remote-only positions.
Uses both Selenium (headful) and HTTP fallback (lightweight).
"""

from __future__ import annotations

import json
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
    parse_salary_range,
)

logger = logging.getLogger(__name__)

# RemoteOK uses JSON embedded in HTML for initial render
JOB_ITEM_CSS = "tr.job-listings-item"
TITLE_CSS = "a.job-link"
COMPANY_CSS = "td.company span.name"
LOCATION_CSS = "td.location"
SALARY_CSS = "td.salary"
TAGS_CSS = "div.tags span.tag"


class RemoteOKScraper(AbstractScraper):
    platform = Platform.REMOTEOK
    BASE_DELAY = 3.0

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

    def _build_url(self, position: str) -> str:
        q = quote(position)
        return f"https://remoteok.com/remote-{q}-jobs"

    def _search_impl(
        self,
        position: str,
        location: str,  # noqa: ARG002 — RemoteOK is always remote
        max_jobs: int,
        max_days_old: int,
        require_remote: bool,  # noqa: ARG002 — always remote
    ) -> list[JobListing]:
        url = self._build_url(position)
        logger.info("[RemoteOK] GET %s", url)

        self._apply_rate_limit()
        self.driver.get(url)
        time.sleep(2)

        results: list[JobListing] = []

        # Try JSON API first (RemoteOK embeds a JSON feed)
        json_jobs = self._scrape_json_feed(position)
        if json_jobs:
            logger.info("[RemoteOK] Got %d jobs from JSON feed", len(json_jobs))
            for job in json_jobs[:max_jobs]:
                if job.matches_filter(max_days_old, require_remote=False):
                    job.search_position = position
                    results.append(job)
            return results

        # Fallback to DOM scraping
        cards = self.driver.find_elements(By.CSS_SELECTOR, JOB_ITEM_CSS)
        logger.info("[RemoteOK] Found %d job rows", len(cards))

        for card in cards[:max_jobs]:
            job = self._parse_card(card)
            if not job:
                continue
            if not job.matches_filter(max_days_old, require_remote=False):
                continue
            results.append(job)

        return results

    def _scrape_json_feed(self, position: str) -> list[JobListing]:
        """
        RemoteOK embeds jobs as JSON in a <script id="json-jobs"> tag.
        This is faster and more reliable than DOM scraping.
        """
        try:
            script_elem = self.driver.find_element(By.ID, "json-jobs")
            raw = script_elem.get_attribute("textContent") or ""
            data = json.loads(raw)
            if not isinstance(data, list):
                return []

            results: list[JobListing] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                try:
                    job = JobListing(
                        platform=Platform.REMOTEOK,
                        platform_job_id=str(item.get("id", "")),
                        title=item.get("position", "") or item.get("title", ""),
                        company=item.get("company", "").get("name", ""),
                        location=item.get("location", "") or "Remote",
                        link=item.get("url", "") or f"https://remoteok.com{item.get('href', '')}",
                        salary_text=item.get("salary", ""),
                        description=item.get("description", "")[:500],
                        remote=True,
                        job_type=item.get("job_type", "full-time"),
                        keywords=[t.get("name", "") for t in item.get("tags", []) if isinstance(t, dict)],
                    )
                    salary_min, salary_max, _ = parse_salary_range(job.salary_text)
                    job.salary_min = salary_min
                    job.salary_max = salary_max
                    results.append(job)
                except Exception:
                    continue
            return results
        except Exception as exc:
            logger.debug("[RemoteOK] JSON feed parse failed: %s", exc)
            return []

    def _parse_card(self, row: Any) -> JobListing | None:
        try:
            link_elem = row.find_element(By.CSS_SELECTOR, TITLE_CSS)
            link = link_elem.get_attribute("href") or ""
            title = link_elem.text.strip()
        except NoSuchElementException:
            return None

        if not link or not title:
            return None

        company = ""
        try:
            company = row.find_element(By.CSS_SELECTOR, COMPANY_CSS).text.strip()
        except NoSuchElementException:
            pass

        location = ""
        try:
            location = row.find_element(By.CSS_SELECTOR, LOCATION_CSS).text.strip()
        except NoSuchElementException:
            location = "Remote"

        salary_text = ""
        try:
            salary_text = row.find_element(By.CSS_SELECTOR, SALARY_CSS).text.strip()
        except NoSuchElementException:
            pass

        salary_min, salary_max, _ = parse_salary_range(salary_text)

        # Tags as keywords
        keywords: list[str] = []
        try:
            tags = row.find_elements(By.CSS_SELECTOR, TAGS_CSS)
            keywords = [t.text.strip() for t in tags if t.text.strip()]
        except NoSuchElementException:
            pass

        return JobListing(
            platform=Platform.REMOTEOK,
            title=title,
            company=company,
            location=location,
            link=link,
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            remote=True,
            hybrid=False,
            keywords=keywords,
            job_type="full-time",
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
