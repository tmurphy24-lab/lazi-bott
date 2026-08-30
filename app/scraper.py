"""
Shared LinkedIn scraper for linkedin-autopilot.

Discovers job listings using the most battle-tested XPath across the five bots:
    li[@data-occludable-job-id]   (used by EasyApplyJobsBot, auto-job-applier)

with a fallback to the base-card class selector used by Job-apply-AI-agent:
    [class*="base-card"]

Returns structured dicts: {title, company, link, posted_days_ago}

Pure Selenium (no undetected-chromedriver) so the dependency graph matches the
4-of-5 bots that already use stock selenium.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    title: str
    company: str
    link: str
    posted_days_ago: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --- selectors reused from the bots (investigation-confirmed) ---
PRIMARY_JOB_CARD_XPATH = '//li[@data-occludable-job-id]'
FALLBACK_JOB_CARD_CSS = 'div[class*="base-card"]'

LINKEDIN_JOB_SEARCH_URL = "https://www.linkedin.com/jobs/search/"


def build_search_url(positions: List[str], location: str, salary_min: Optional[int] = None) -> str:
    """
    Build a LinkedIn job-search URL from a list of title strings.

    LinkedIn ORs multiple keywords when separated by commas. We join the
    persona titles into one keywords param so the search matches ANY of them.
    """
    keywords = ", ".join(positions)
    url = f"{LINKEDIN_JOB_SEARCH_URL}?keywords={quote(keywords)}&location={quote(location)}"
    if salary_min:
        url += f"&salary={salary_min}"
    return url


def make_driver(user_data_dir: Optional[str] = None, headless: bool = False) -> webdriver.Chrome:
    """Create a Chrome driver, optionally persisted via user-data-dir."""
    options = Options()
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-automation")
    options.add_argument("--window-size=1920,1080")
    # match user agent to avoid trivial bot flags
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=options)
    driver.set_page_load_timeout(30)
    return driver


def _extract_posted_days(card) -> Optional[int]:
    """Try to parse a 'posted X days ago' figure from a job card."""
    today = datetime.today()
    # <time datetime="2024-01-15">  or  class-based selectors
    selectors = [
        ("xpath", ".//time"),
        ("xpath", ".//*[contains(@class, 'job-card-list__entity-date')]"),
    ]
    for kind, sel in selectors:
        try:
            elem = card.find_element(getattr(By, kind.upper()), sel)
            raw = elem.get_attribute("datetime") or elem.text.strip()
            if raw:
                posted_date = datetime.strptime(raw[:10], "%Y-%m-%d")
                return (today - posted_date).days
        except (NoSuchElementException, ValueError):
            continue
    return None


def scrape_jobs(
    driver: webdriver.Chrome,
    positions: List[str],
    location: str,
    max_jobs: int = 25,
    max_days_old: int = 7,
    salary_min: Optional[int] = None,
) -> List[JobResult]:
    """
    Navigate LinkedIn Jobs, scroll to load results, return up to max_jobs
    JobResult dicts.

    Uses PRIMARY_JOB_CARD_XPATH first; falls back to FALLBACK_JOB_CARD_CSS
    if the primary returns zero elements (LinkedIn's DOM changes periodically).
    """
    url = build_search_url(positions, location, salary_min)
    logger.info("Scraping: %s", url)
    driver.get(url)
    time.sleep(3)

    # scroll to trigger lazy-load (mirrors easy-apply.py and Job-apply-AI-agent)
    for _ in range(3):
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(2)

    # try primary XPath
    cards = driver.find_elements(By.XPATH, PRIMARY_JOB_CARD_XPATH)
    if not cards:
        logger.warning("Primary XPath returned 0 cards; falling back to %s", FALLBACK_JOB_CARD_CSS)
        cards = driver.find_elements(By.CSS_SELECTOR, FALLBACK_JOB_CARD_CSS)

    logger.info("Found %d job cards", len(cards))
    results: List[JobResult] = []

    for card in cards[:max_jobs]:
        try:
            # title and link: title is usually in an <a> child
            link_elem = card.find_element(By.XPATH, ".//a")
            link = link_elem.get_attribute("href")
            title = link_elem.text.strip() or card.text.strip()

            # company: next sibling or a known class
            try:
                company = card.find_element(
                    By.CSS_SELECTOR, "h4"
                ).text.strip()
            except NoSuchElementException:
                company = ""

            days = _extract_posted_days(card)
            if days is not None and days > max_days_old:
                continue

            results.append(JobResult(title=title, company=company, link=link, posted_days_ago=days))
        except Exception as e:
            logger.warning("Skipping a card: %s", e)
            continue

    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    demo_positions = sys.argv[1:] or ["Director of Supply Chain", "Director of Procurement"]
    d = make_driver(headless=True)
    try:
        jobs = scrape_jobs(d, demo_positions, "United States", max_jobs=10)
        for j in jobs[:5]:
            print(j.to_dict())
        print(f"... total {len(jobs)}")
    finally:
        d.quit()
