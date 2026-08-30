"""
Resume parser for linkedin-autopilot.

Accepts a path to a resume file (.txt, .md, .docx, .pdf) and returns a
structured dict that the auto-filler and persona profile both consume.

The parser uses a hybrid strategy:
  1. Try known open-source resume parsers (python-docx for .docx,
     pdfplumber for .pdf, plain read for .txt/.md).
  2. Fall back to a heuristic regex-based extractor (email, phone,
     years-of-experience, skill keywords, education).

Schema (matches profile.yaml personal_info + experience + education + skills):
  {
    "personal_info": {first_name, last_name, email, phone, linkedin_url, city, state, country},
    "skills": [...],
    "experience": [{"title": ..., "company": ..., "start": ..., "end": ..., "summary": ...}],
    "education": [{"degree": ..., "school": ..., "year": ...}],
    "raw_text": "..."
  }
"""

from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# --- low-level extractors ---

EMAIL_RE   = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE   = re.compile(r"(\+?\d{1,3}[\s\-\.]?)?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}")
LINKEDIN_RE = re.compile(r"(https?://)?(www\.)?linkedin\.com/in/[\w\-\.%/]+", re.IGNORECASE)
YEARS_RE   = re.compile(r"\b(19|20)\d{2}\b")
SKILL_KEYWORDS = [
    "Python","Java","SQL","Excel","Power BI","Tableau","SAP","Oracle","NetSuite",
    "Supply Chain","Procurement","Logistics","Planning","S&OP","Forecasting",
    "ERP","WMS","TMS","Six Sigma","Lean","Kaizen","PMP","MBA","Bachelors","Masters",
    "Project Management","Vendor Management","Contract Negotiation","Sourcing",
    "Inventory","Demand Planning","Supplier","Category Management","Negotiation",
    "Leadership","Strategy","Operations","Manufacturing","Distribution",
    "Auto","Automation","PowerApps","Power Automate","SharePoint","Salesforce",
    "Jira","Confluence","Agile","Scrum","Kanban","Git","Docker","Kubernetes",
]

EDUCATION_DEGREES = ["PhD","MBA","Masters","Bachelor","Associate","Diploma","High School","GED"]


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".text"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.warning("python-docx failed (%s); falling back to raw read", e)
            return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or "")
            return "\n".join(text_parts)
        except ImportError:
            logger.warning("pdfplumber not installed; skipping PDF text")
        except Exception as e:
            logger.warning("pdfplumber failed (%s); skipping", e)
        return ""
    # last resort
    return path.read_text(encoding="utf-8", errors="ignore")


def _split_name(full_line: str) -> tuple[str, str]:
    parts = full_line.strip().split()
    if len(parts) == 1:
        return parts[0], ""
    if len(parts) == 2:
        return parts[0], parts[1]
    # assume first + last (skip middle)
    return parts[0], parts[-1]


def _guess_country(text: str) -> str:
    if re.search(r"\bUSA\b|United States|US\b", text):
        return "United States"
    return ""


def parse_resume(path: str | Path) -> Dict[str, Any]:
    """
    Parse a resume file and return structured data.
    Never raises — returns whatever it can extract, with empty fields for the rest.
    """
    p = Path(path)
    if not p.exists():
        logger.error("Resume not found: %s", p)
        return _empty()

    text = _read_text(p)
    if not text:
        return _empty()

    return _extract_heuristic(text, raw_path=str(p))


def _empty() -> Dict[str, Any]:
    return {
        "personal_info": {"first_name":"","last_name":"","email":"","phone":"","linkedin_url":"","city":"","state":"","country":""},
        "skills": [],
        "experience": [],
        "education": [],
        "raw_text": "",
    }


def _extract_heuristic(text: str, raw_path: str = "") -> Dict[str, Any]:
    result = _empty()
    result["raw_text"] = text[:5000]
    if raw_path:
        result["resume_path"] = raw_path

    # Email
    if m := EMAIL_RE.search(text):
        result["personal_info"]["email"] = m.group(0)

    # Phone
    if m := PHONE_RE.search(text):
        result["personal_info"]["phone"] = m.group(0).strip()

    # LinkedIn
    if m := LINKEDIN_RE.search(text):
        url = m.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        result["personal_info"]["linkedin_url"] = url

    # Name: first non-empty line that doesn't look like contact info
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if EMAIL_RE.search(s) or PHONE_RE.search(s) or LINKEDIN_RE.search(s):
            continue
        if len(s) < 3 or len(s) > 60:
            continue
        # heuristic: contains only letters/spaces/apostrophes/hyphens
        if re.match(r"^[A-Za-z][A-Za-z\s\.'\-]+$", s):
            first, last = _split_name(s)
            result["personal_info"]["first_name"] = first
            result["personal_info"]["last_name"]  = last
            break

    # Skills
    found_skills = []
    text_lower = text.lower()
    for kw in SKILL_KEYWORDS:
        if kw.lower() in text_lower:
            found_skills.append(kw)
    result["skills"] = sorted(set(found_skills))

    # Education
    for line in text.splitlines():
        s = line.strip()
        for deg in EDUCATION_DEGREES:
            if deg.lower() in s.lower():
                # year?
                yrs = YEARS_RE.findall(s)
                year = ""
                if yrs:
                    year = yrs[0][0] + yrs[0][1] if isinstance(yrs[0], tuple) else str(yrs[0])
                result["education"].append({"degree": deg, "school": s, "year": year})
                break

    # Experience: scan for year ranges like "2018 - 2023" or "2020 - Present"
    for line in text.splitlines():
        s = line.strip()
        m = re.search(r"(19|20)\d{2}\s*[\-–—to]+\s*((19|20)\d{2}|Present|Current|Now)", s, re.IGNORECASE)
        if m:
            # extract the first year as start, last year (or "Present") as end
            years = re.findall(r"(19|20)\d{2}", s)
            start_year = years[0] + (years[1] if len(years) > 1 else "") if years else ""
            if years:
                start_year = years[0][0] + years[0][1] if isinstance(years[0], tuple) else str(years[0])
            end_part = s.split("–")[-1].strip() if "–" in s else s.split("-")[-1].strip()
            # extract just the year if present
            end_years = re.findall(r"(19|20)\d{2}", end_part)
            end_year = end_years[0][0] + end_years[0][1] if end_years and isinstance(end_years[0], tuple) else (str(end_years[0]) if end_years else end_part)
            result["experience"].append({
                "title": s, "company": "", "start": start_year, "end": end_year, "summary": s,
            })

    # Country
    if c := _guess_country(text):
        result["personal_info"]["country"] = c

    return result


def profile_from_resume(path: str | Path) -> Dict[str, Any]:
    """
    Higher-level helper: take a resume file and return a profile.yaml-shaped
    dict ready to merge into a persona's profile.
    """
    parsed = parse_resume(path)
    return {
        "personal_info": parsed["personal_info"],
        "resume_path": parsed.get("resume_path", str(path)),
        "skills": parsed["skills"],
        "experience": parsed["experience"],
        "education": parsed["education"],
    }
