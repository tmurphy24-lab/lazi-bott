"""
F4, F5, F6: AI-assisted writing tools.

F4: CoverLetterGenerator — write a tailored cover letter for a job
F5: InterviewPrep     — generate likely interview Q&A from a JD
F6: FollowUpEmail     — draft a polite follow-up after N days no response

All three share the same LLM plumbing (OpenAI client with Poolside/OpenAI
base URL), but each has its own prompt template. They gracefully fall back
to a deterministic template when no API key is configured so the user can
preview the output offline.
"""

from __future__ import annotations
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from .profile_store import Persona, resolve_api_key

logger = logging.getLogger(__name__)


# ---------- shared LLM helper ----------

def _call_llm(system: str, user: str, provider: str = "poolside",
              api_key: Optional[str] = None, max_tokens: int = 500) -> Optional[str]:
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
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def _persona_summary(persona: Persona) -> Dict[str, Any]:
    return {
        "name": f"{persona.load_profile()['personal_info'].get('first_name','')} "
                f"{persona.load_profile()['personal_info'].get('last_name','')}".strip(),
        "skills": persona.load_profile().get("skills", []),
        "experience": persona.load_profile().get("experience", []),
    }


# ---------- F4: Cover letter ----------

def generate_cover_letter(persona: Persona, job: dict,
                            provider: str = "poolside") -> str:
    """Write a cover letter for `job` using persona + LLM (or offline template)."""
    summary = _persona_summary(persona)
    api_key = resolve_api_key(provider) if provider != "none" else None
    system = (
        "You are a career coach writing a tight, tailored cover letter "
        "(max 250 words). Use the candidate's real experience. No fluff, "
        "no clichés. Open with the candidate's name and the job title."
    )
    user = (
        f"Candidate: {summary['name']}\n"
        f"Skills: {', '.join(summary['skills'])}\n"
        f"Recent experience:\n" +
        "\n".join(f"  - {e.get('title','')} @ {e.get('company','')}"
                  for e in summary['experience'][:3]) +
        f"\n\nJob title: {job.get('title','')}\n"
        f"Company: {job.get('company','')}\n"
        f"Job description (truncated):\n{job.get('description','')[:2000]}"
    )
    text = _call_llm(system, user, provider=provider, api_key=api_key, max_tokens=600)
    if text:
        return text
    # offline template fallback
    return _offline_cover_letter(summary, job)


def _offline_cover_letter(summary: Dict[str, Any], job: dict) -> str:
    name = summary["name"] or "Your Name"
    title = job.get("title", "this role")
    company = job.get("company", "your company")
    skills = ", ".join(summary["skills"][:5]) if summary["skills"] else "my core skills"
    exp = summary["experience"][:1]
    exp_line = ""
    if exp:
        e = exp[0]
        exp_line = f"Most recently, I was {e.get('title','')} at {e.get('company','')}."
    return (
        f"Dear Hiring Manager,\n\n"
        f"I'm applying for the {title} role at {company}. {exp_line}\n\n"
        f"My background in {skills} aligns directly with what you're looking for. "
        f"I've shipped results, learned fast, and I'm ready to contribute from week one.\n\n"
        f"I'd love to discuss how my experience can help {company} hit its goals.\n\n"
        f"Thanks for your time,\n{name}\n"
    )


# ---------- F5: Interview prep ----------

def generate_interview_questions(persona: Persona, job: dict,
                                  provider: str = "poolside", n: int = 8) -> List[Dict[str, str]]:
    """Return a list of {question, sample_answer} dicts."""
    summary = _persona_summary(persona)
    api_key = resolve_api_key(provider) if provider != "none" else None
    system = (
        "You are an interview coach. Given a job description, generate the "
        f"{n} most likely interview questions and a short sample answer for each "
        "based on the candidate's resume. Format: each line 'Q: ...' then 'A: ...', "
        "blank line between Q&A blocks."
    )
    user = (
        f"Candidate skills: {', '.join(summary['skills'])}\n"
        f"Job title: {job.get('title','')}\n"
        f"Company: {job.get('company','')}\n"
        f"Job description:\n{job.get('description','')[:2000]}"
    )
    text = _call_llm(system, user, provider=provider, api_key=api_key, max_tokens=1200)
    if text:
        return _parse_qa(text)
    return _offline_interview_questions(job, n)


def _parse_qa(text: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for b in blocks:
        q_match = re.search(r"Q\s*[:\-]\s*(.+)", b, re.IGNORECASE)
        a_match = re.search(r"A\s*[:\-]\s*(.+)", b, re.IGNORECASE | re.DOTALL)
        if q_match and a_match:
            out.append({
                "question": q_match.group(1).strip(),
                "sample_answer": a_match.group(1).strip(),
            })
    return out


def _offline_interview_questions(job: dict, n: int) -> List[Dict[str, str]]:
    defaults = [
        ("Tell me about yourself.",
         "Open with a 90-second pitch: who you are, your biggest recent win, why this role."),
        ("Why do you want to work here?",
         "Mention 2-3 specific things about the company/team/role that match your goals."),
        ("What's your biggest weakness?",
         "Name a real one, plus the system you built to manage it."),
        ("Describe a time you disagreed with your manager.",
         "Use STAR (Situation, Task, Action, Result). End with what you learned."),
        ("How do you handle pressure?",
         "Give a concrete example of prioritizing under a deadline and the outcome."),
        ("Why are you leaving your current role?",
         "Stay positive. Frame it as growth, not escape."),
        ("Where do you see yourself in 3 years?",
         "Tie to the role's trajectory. Show commitment and ambition."),
        ("What's your expected salary?",
         "Anchor to a range based on your research and experience. Don't lowball."),
    ]
    out = []
    for q, a in defaults[:n]:
        out.append({"question": q, "sample_answer": a})
    return out


# ---------- F6: Follow-up email ----------

def generate_followup_email(persona: Persona, job: dict,
                              days_since: int = 7,
                              provider: str = "poolside") -> str:
    """Draft a polite follow-up email after `days_since` days no response."""
    summary = _persona_summary(persona)
    api_key = resolve_api_key(provider) if provider != "none" else None
    system = (
        "You are writing a brief, polite follow-up email about a job application. "
        "Keep it under 120 words. One paragraph. No attachments, no demands."
    )
    user = (
        f"Candidate: {summary['name']}\n"
        f"Job: {job.get('title','')} at {job.get('company','')}\n"
        f"Days since applying: {days_since}\n"
        f"Original link: {job.get('link','')}\n\n"
        f"Write the email body. No subject line needed."
    )
    text = _call_llm(system, user, provider=provider, api_key=api_key, max_tokens=250)
    if text:
        return text
    return _offline_followup(summary, job, days_since)


def _offline_followup(summary: Dict[str, Any], job: dict, days: int) -> str:
    name = summary["name"] or "Your Name"
    title = job.get("title", "the role")
    company = job.get("company", "your team")
    return (
        f"Hi,\n\n"
        f"I wanted to follow up on my application for the {title} role "
        f"from {days} days ago. I'm still very interested in {company} and would "
        f"welcome any update on the hiring timeline. Happy to provide any additional "
        f"info you need.\n\n"
        f"Thanks for your time,\n{name}\n"
    )


# ---------- F7: Salary benchmark ----------

def salary_benchmark(title: str, location: str = "United States",
                      years_experience: int = 5,
                      provider: str = "poolside") -> Dict[str, Any]:
    """Estimate a salary range for `title` in `location` with `years_experience` years.
    Falls back to a heuristic if the LLM is unavailable.
    """
    api_key = resolve_api_key(provider) if provider != "none" else None
    system = (
        "You are a compensation analyst. Given a job title, location, and years "
        "of experience, return ONLY a JSON object with keys: p25, p50, p75, currency, "
        "source_estimate. No prose, just JSON."
    )
    user = (
        f"Title: {title}\nLocation: {location}\nYears experience: {years_experience}\n"
        f"Return JSON like: {{\"p25\": 90000, \"p50\": 120000, \"p75\": 160000, "
        f"\"currency\": \"USD\", \"source_estimate\": \"heuristic\"}}"
    )
    text = _call_llm(system, user, provider=provider, api_key=api_key, max_tokens=120)
    if text:
        m = re.search(r"\{.*?\}", text, re.DOTALL)
        if m:
            try:
                import json
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                pass
    return _heuristic_salary(title, location, years_experience)


def _heuristic_salary(title: str, location: str, years: int) -> Dict[str, Any]:
    """Very rough heuristic when no LLM. Seniority + role-type matrix."""
    base_by_role = {
        "director": 130000, "vp": 150000, "head": 140000, "manager": 95000,
        "senior": 90000, "lead": 100000, "principal": 130000, "staff": 110000,
        "engineer": 80000, "analyst": 65000, "specialist": 70000, "architect": 130000,
    }
    title_l = title.lower()
    base = 80000
    for k, v in base_by_role.items():
        if k in title_l:
            base = v
            break
    # experience multiplier
    mult = 0.85 + 0.05 * min(20, max(0, years))
    p50 = int(base * mult / 5000) * 5000
    return {
        "p25": int(p50 * 0.8 / 5000) * 5000,
        "p50": p50,
        "p75": int(p50 * 1.25 / 5000) * 5000,
        "currency": "USD",
        "source_estimate": "heuristic (no LLM configured)",
    }


# ---------- F8: Resume tailor ----------

def tailor_resume(persona: Persona, job: dict, top_n: int = 8,
                   provider: str = "poolside") -> List[str]:
    """Pick the top `top_n` bullets from the persona's experience that best
    match the job description. Returns a list of bullet strings."""
    summary = _persona_summary(persona)
    bullets: List[str] = []
    for e in summary["experience"]:
        if e.get("title"):
            bullets.append(f"{e['title']} @ {e.get('company','')}")
    api_key = resolve_api_key(provider) if provider != "none" else None
    system = (
        "You are a resume writer. Given a job description and a list of candidate "
        f"experience bullets, return the top {top_n} that best match the job. "
        "Return one bullet per line, no numbering, no commentary."
    )
    user = (
        f"Job description:\n{job.get('description','')[:2000]}\n\n"
        f"Candidate bullets:\n" + "\n".join(f"- {b}" for b in bullets)
    )
    text = _call_llm(system, user, provider=provider, api_key=api_key, max_tokens=400)
    if text:
        return [b.strip("- ").strip() for b in text.splitlines() if b.strip()]
    return bullets[:top_n]
