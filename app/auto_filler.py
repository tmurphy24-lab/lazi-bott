"""
Auto-filler for linkedin-autopilot.

Given a job's form questions and a persona profile (personal_info + resume data),
returns a dict of {question_index: answer}.

Heuristics covered:
  - Name (first/last/full)
  - Email
  - Phone
  - City / State / Country
  - Years of experience (range-aware)
  - Salary expectations
  - Sponsorship / visa / clearance (from profile flags)
  - LinkedIn URL
  - Generic yes/no (default: "No" unless profile says otherwise)
  - Skill matching

This is the "read from profile / read from resume" behavior the user asked for.
It runs in two places:
  1. As a bot_runner `on_job` plugin (filters/ranks jobs before apply)
  2. As a filler callable the engines can use to answer form questions

When the heuristic answer is None (the resume/profile doesn't have it), the
filler can fall back to the LLM (Poolside/OpenAI) with a system prompt that
includes the persona's full profile context.
"""

from __future__ import annotations
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Callable

from .profile_store import Persona

logger = logging.getLogger(__name__)


# -- question normalization ---

def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


# -- form-answer logic ---

def answer_question(question: str, profile: Dict[str, Any]) -> Optional[str]:
    """
    Try to answer a single form question from the profile.
    Returns None if we don't have a confident answer.
    """
    q = _normalize(question)
    pi = profile.get("personal_info", {}) or {}

    # name variants
    if any(t in q for t in ["first name", "given name", "firstname"]):
        return pi.get("first_name", "") or None
    if any(t in q for t in ["last name", "family name", "surname", "lastname"]):
        return pi.get("last_name", "") or None
    if "full name" in q or "your name" in q or "name" == q:
        full = f"{pi.get('first_name','')} {pi.get('last_name','')}".strip()
        return full or None

    # contact
    if "email" in q:
        return pi.get("email", "") or None
    if "phone" in q or "mobile" in q or "telephone" in q:
        return pi.get("phone", "") or None
    if "linkedin" in q and "url" in q:
        return pi.get("linkedin_url", "") or None

    # location
    if "city" in q:
        return pi.get("city", "") or None
    if "state" in q or "province" in q:
        return pi.get("state", "") or None
    if "country" in q:
        return pi.get("country", "") or None

    # experience
    if "years of experience" in q or "how many years" in q or "years experience" in q:
        yrs = _max_experience_years(profile)
        if yrs:
            return str(yrs)
        # fall back to search_config range
        yrs_max = profile.get("_search_config", {}).get("experience_years_max")
        if yrs_max:
            return str(yrs_max)
        return None

    # salary
    if "salary" in q or "compensation" in q or "expected pay" in q:
        # use a midpoint of salary range from search_config
        cfg_min = profile.get("_search_config", {}).get("salary_min")
        cfg_max = profile.get("_search_config", {}).get("salary_max")
        if cfg_min and cfg_max:
            return str((cfg_min + cfg_max) // 2)
        if cfg_min:
            return str(cfg_min)
        return None

    # sponsorship / visa
    if "sponsorship" in q or "visa" in q:
        return pi.get("sponsorship_required", "No")  # default: doesn't need sponsorship

    # clearance
    if "clearance" in q or "polygraph" in q:
        return pi.get("security_clearance", "No")

    # generic yes/no
    if q.startswith("are you") or q.startswith("do you") or q.startswith("have you"):
        if "authorized" in q or "eligible" in q or "legally" in q:
            return pi.get("work_authorized", "Yes")
        return pi.get("default_yes_no", "No")

    # skills — match by token in profile.skills
    for skill in profile.get("skills", []) or []:
        if skill.lower() in q:
            return "Yes"

    return None


def _max_experience_years(profile: Dict[str, Any]) -> Optional[int]:
    """Estimate max years of professional experience from resume experience list."""
    exp = profile.get("experience", []) or []
    if not exp:
        return None
    spans = []
    for e in exp:
        start = str(e.get("start", ""))
        end   = str(e.get("end", ""))
        ys = re.search(r"(19|20)\d{2}", start)
        ye = re.search(r"(19|20)\d{2}", end)
        if ys and ye:
            spans.append(int(ye.group(0)) - int(ys.group(0)))
    if not spans:
        return None
    return max(spans)


# -- public facade ---

def build_answerer(persona: Persona) -> Callable[[str], Optional[str]]:
    """
    Returns a closure that answers form questions using this persona's
    combined profile (profile.yaml + search_config.yaml for salary range).
    """
    profile = persona.load_profile()
    cfg = persona.load_config()
    profile["_search_config"] = cfg
    return lambda q: answer_question(q, profile)


def answer_form(questions: List[str], persona: Persona) -> Dict[str, str]:
    """
    Given a list of form questions and a persona, return a dict
    {index_str: answer} for everything we can confidently answer.
    """
    answerer = build_answerer(persona)
    out: Dict[str, str] = {}
    for i, q in enumerate(questions):
        a = answerer(q)
        if a:
            out[str(i)] = a
    return out


# -- bot_runner plugin hook ---

def make_on_job_filter(persona: Persona) -> Callable[[dict], bool]:
    """
    Plugin hook: returns False to skip a job if its title/company hits the
    persona's blacklist. This is the "on_job" callback bot_runner expects.
    """
    cfg = persona.load_config()
    bl_companies = {c.lower() for c in cfg.get("blacklist_companies", [])}
    bl_titles    = {t.lower() for t in cfg.get("blacklist_titles", [])}

    def _filter(job: dict) -> bool:
        title = (job.get("title") or "").lower()
        company = (job.get("company") or "").lower()
        if any(b in company for b in bl_companies):
            logger.info("on_job: skip blacklisted company '%s'", job.get("company"))
            return False
        if any(b in title for b in bl_titles):
            logger.info("on_job: skip blacklisted title '%s'", job.get("title"))
            return False
        return True
    return _filter


# -- LLM-backed answerer (used when heuristic is None) --

def _build_llm_system_prompt(profile: Dict[str, Any]) -> str:
    """Build a system prompt that includes the persona's profile so the LLM
    can answer form questions in-character."""
    pi = profile.get("personal_info", {}) or {}
    lines = [
        "You are filling out a job application form on behalf of the user.",
        "Use ONLY the information in the user profile below. If a field is",
        "missing, say 'unknown' rather than making something up. Reply with",
        "ONLY the answer text — no preamble, no explanation, no quotes.",
        "",
        "USER PROFILE:",
        f"Name: {pi.get('first_name','')} {pi.get('last_name','')}".strip(),
        f"Email: {pi.get('email','')}",
        f"Phone: {pi.get('phone','')}",
        f"Location: {pi.get('city','')}, {pi.get('state','')} {pi.get('country','')}".strip(),
        f"LinkedIn: {pi.get('linkedin_url','')}",
        f"Skills: {', '.join(profile.get('skills', []) or [])}",
    ]
    if profile.get("experience"):
        lines.append("Experience:")
        for e in profile["experience"][:5]:
            lines.append(f"  - {e.get('title','')} ({e.get('start','')} to {e.get('end','')})")
    if profile.get("education"):
        lines.append("Education:")
        for ed in profile["education"][:3]:
            lines.append(f"  - {ed.get('degree','')} {ed.get('school','')} ({ed.get('year','')})")
    return "\n".join(lines)


def llm_answer_question(question: str, profile: Dict[str, Any],
                         provider: str = "poolside",
                         api_key: Optional[str] = None) -> Optional[str]:
    """
    Ask the LLM to answer a single form question using the persona's profile.
    Returns None if the LLM call fails or no key is configured.
    """
    if not api_key:
        return None
    try:
        import openai
    except ImportError:
        return None
    base_urls = {
        "poolside": "https://inference.poolside.ai/v1",
        "openai":   "https://api.openai.com/v1",
    }
    base = base_urls.get(provider, "https://api.openai.com/v1")
    try:
        client = openai.OpenAI(api_key=api_key, base_url=base)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _build_llm_system_prompt(profile)},
                {"role": "user",   "content": question},
            ],
            max_tokens=120,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.lower() in ("unknown", "n/a", "not applicable", ""):
            return None
        return text
    except Exception as e:
        logger.warning("LLM answer failed for %r: %s", question[:40], e)
        return None


def build_llm_answerer(persona: Persona, provider: str = "poolside") -> Callable[[str], Optional[str]]:
    """
    Returns a closure that first tries the heuristic answer, then falls back
    to the LLM. Used as the engine's form-question filler.
    """
    from .profile_store import resolve_api_key
    profile = persona.load_profile()
    cfg = persona.load_config()
    profile["_search_config"] = cfg
    api_key = resolve_api_key(provider) if provider != "none" else None

    def _answer(question: str) -> Optional[str]:
        local = answer_question(question, profile)
        if local is not None:
            return local
        return llm_answer_question(question, profile, provider=provider, api_key=api_key)
    return _answer


def answer_form_with_llm(questions: List[str], persona: Persona,
                          provider: str = "poolside") -> Dict[str, str]:
    """
    Like answer_form, but for any question the heuristic can't answer,
    the LLM is consulted.
    """
    answerer = build_llm_answerer(persona, provider=provider)
    out: Dict[str, str] = {}
    for i, q in enumerate(questions):
        a = answerer(q)
        if a:
            out[str(i)] = a
    return out
