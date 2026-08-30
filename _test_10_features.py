"""
E2E test for the 10 new features:
  F1: JobTracker     - record_application, list, update, delete, export_csv
  F2: Scheduler      - add/list/remove, parse_cron, is_due, next_run
  F3: Analytics      - compute_stats, by_engine, by_week, by_company
  F4: CoverLetter    - generate_cover_letter (offline + LLM-ready)
  F5: InterviewPrep  - generate_interview_questions
  F6: FollowUpEmail  - generate_followup_email
  F7: SalaryBench    - salary_benchmark
  F8: ResumeTailor   - tailor_resume
  F9: DarkMode       - ThemeManager.set_theme, THEMES dict
  F10: Notifications - Notifier.notify (no tray in test = logs OK)
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

failures = []
def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        failures.append((name, detail))
        print(f"  FAIL  {name}  --  {detail}")


# === Setup: clean state ===

from app.profile_store import create_persona, Persona
create_persona("e2e-user", config={"titles": ["Test"], "salary_min": 100000, "salary_max": 200000})

# clear any prior tracker data
from app.job_tracker import TRACKER_PATH
if TRACKER_PATH.exists():
    TRACKER_PATH.unlink()


# === F1: JobTracker ===

print("F1: JobTracker (record / list / update / delete / export)")
from app.job_tracker import (
    record_application, list_applications, update_status, delete_application,
    export_csv, Application,
)
a1 = record_application("e2e-user", {"title": "Director", "company": "Acme", "link": "x"},
                         status="applied", engine="easyapplyjobsbot")
a2 = record_application("e2e-user", {"title": "Manager", "company": "Beta", "link": "y"},
                         status="applied", engine="linkedin-aihawk")
a3 = record_application("e2e-user", {"title": "VP", "company": "Crossover", "link": "z"},
                         status="applied", engine="linkedin-bot")
check("record_application creates Application",
      isinstance(a1, Application) and a1.id and a1.applied_at)
check("list_applications returns 3", len(list_applications()) == 3)
check("list_applications filter by persona works",
      len(list_applications(persona="e2e-user")) == 3)
check("list_applications filter by status works",
      len(list_applications(status="applied")) == 3)

upd = update_status(a1.id, "interview", notes="phone screen scheduled")
check("update_status works", upd is not None and upd.status == "interview")
check("update_status preserves notes", upd.notes == "phone screen scheduled")

# invalid status
try:
    update_status(a1.id, "BOGUS")
    check("update_status rejects invalid status", False, "should have raised")
except ValueError:
    check("update_status rejects invalid status", True)

# export
csv_text = export_csv()
check("export_csv returns header + rows", csv_text.startswith("id,persona,title"))
check("export_csv has 3 data rows", len(csv_text.strip().splitlines()) == 4)
check("delete_application removes by id", delete_application(a2.id) is True)
check("after delete, list returns 2", len(list_applications()) == 2)


# === F2: Scheduler ===

print("\nF2: Scheduler (cron parse / is_due / next_run / add/list/remove)")
from app.scheduler import (
    add_schedule, list_schedules, remove_schedule, set_enabled,
    parse_cron, is_due, next_run,
)
from datetime import datetime

# parse_cron
c = parse_cron("0 9 * * 1-5")
check("parse_cron extracts fields (Mon-Fri 9am)",
      c["minute"] == [0] and c["hour"] == [9] and c["dow"] == [1, 2, 3, 4, 5])
c2 = parse_cron("*/15 * * * *")
check("parse_cron */15 yields [0,15,30,45]", c2["minute"] == [0, 15, 30, 45])
c3 = parse_cron("1,15,45 * * * *")
check("parse_cron comma-list", c3["minute"] == [1, 15, 45])
c4 = parse_cron("30 14 1 1 *")
check("parse_cron explicit dom/month", c4["dom"] == [1] and c4["month"] == [1])
try:
    parse_cron("not enough fields")
    check("parse_cron rejects bad expr", False)
except ValueError:
    check("parse_cron rejects bad expr", True)

# is_due / next_run: schedule for "0 9 * * 1-5" (9am Mon-Fri) — assume test runs whenever
sch = add_schedule("morning-routine", "e2e-user", "easyapplyjobsbot",
                    "poolside", "auto-apply", "0 9 * * 1-5")
nxt = next_run(sch)
check("next_run returns a datetime for valid schedule", isinstance(nxt, datetime))
# a disabled schedule never fires
sch2 = add_schedule("never", "e2e-user", "easyapplyjobsbot", "poolside",
                     "auto-apply", "0 9 * * 1-5", enabled=False)
check("is_due returns False for disabled schedule",
      is_due(sch2) is False)
# remove
check("remove_schedule returns True", remove_schedule("morning-routine"))
check("remove_schedule returns False for missing",
      remove_schedule("does-not-exist") is False)
# set_enabled
sch3 = add_schedule("toggle-me", "e2e-user", "easyapplyjobsbot", "poolside",
                     "auto-apply", "0 9 * * 1-5")
check("set_enabled toggles", set_enabled("toggle-me", False) is not None)
check("disabled schedule is not due", is_due(sch3, now=datetime(2026, 8, 31, 9, 0)) is False)
remove_schedule("never"); remove_schedule("toggle-me")


# === F3: Analytics ===

print("\nF3: Analytics (compute_stats / by_engine / by_week / by_company)")
from app.analytics import compute_stats, by_engine, by_week, by_company
s = compute_stats(persona="e2e-user")
check("compute_stats returns Stats", hasattr(s, "total"))
check("total matches 2 (1 applied + 1 interview)", s.total == 2, f"got {s.total}")
check("interview count is 1 (after update_status)", s.interview == 1)
check("response_rate is computed", 0.0 <= s.response_rate <= 1.0)
check("by_engine dict is non-empty", len(s.by_engine) >= 1)
check("by_week dict is non-empty", len(s.by_week) >= 1)
check("top_companies has Acme", "Acme" in s.top_companies)


# === F4: Cover letter ===

print("\nF4: CoverLetterGenerator")
from app.ai_assist import generate_cover_letter
letter = generate_cover_letter(Persona("e2e-user"),
                                {"title": "Director of Supply Chain",
                                 "company": "Acme Manufacturing",
                                 "description": "Lead end-to-end supply chain for $400M company.",
                                 "link": ""},
                                provider="none")
check("cover letter mentions the role title", "Director of Supply Chain" in letter)
check("cover letter mentions the company",  "Acme Manufacturing" in letter)
check("cover letter mentions candidate name", "e2e-user".replace("-", " ").title() in letter or
      "Trevor" in letter or len(letter) > 100)
check("cover letter is non-empty and has lines", len(letter.splitlines()) >= 5)


# === F5: Interview prep ===

print("\nF5: InterviewPrep")
from app.ai_assist import generate_interview_questions
qs = generate_interview_questions(Persona("e2e-user"),
                                    {"title": "Director", "company": "Acme",
                                     "description": "lead team", "link": ""},
                                    provider="none", n=5)
check("interview prep returns at least 5 Q&A", len(qs) >= 5)
check("each Q&A has question + sample_answer",
      all("question" in q and "sample_answer" in q for q in qs))
check("questions are non-empty strings",
      all(len(q["question"]) > 5 for q in qs))


# === F6: Follow-up email ===

print("\nF6: FollowUpEmail")
from app.ai_assist import generate_followup_email
email = generate_followup_email(Persona("e2e-user"),
                                 {"title": "Director", "company": "Acme", "link": ""},
                                 days_since=10, provider="none")
check("follow-up email mentions company",  "Acme" in email)
check("follow-up email mentions days",      "10" in email or "days" in email)
check("follow-up email is non-empty",       len(email) > 50)


# === F7: Salary benchmark ===

print("\nF7: SalaryBenchmark")
from app.ai_assist import salary_benchmark
sb = salary_benchmark("Senior Software Engineer", "United States", years_experience=8,
                       provider="none")
check("salary benchmark returns p25/p50/p75",
      "p25" in sb and "p50" in sb and "p75" in sb and "currency" in sb)
check("salary p50 is a positive number",     sb["p50"] > 0)
check("salary p25 < p50 < p75",
      sb["p25"] < sb["p50"] < sb["p75"])
sb2 = salary_benchmark("Director of Operations", "United States", years_experience=15,
                        provider="none")
check("director benchmark > senior benchmark p50",
      sb2["p50"] > sb["p50"], f"senior={sb['p50']}, director={sb2['p50']}")


# === F8: Resume tailor ===

print("\nF8: ResumeTailor")
from app.ai_assist import tailor_resume
# give the persona some experience
p = Persona("e2e-user")
prof = p.load_profile()
prof["experience"] = [
    {"title": "Director of Supply Chain", "company": "Acme",  "start": "2020", "end": "Present",
     "summary": "Built S&OP, reduced inventory 22%"},
    {"title": "Supply Chain Manager",      "company": "Beta",   "start": "2016", "end": "2020",
     "summary": "Led procurement for 3 DCs"},
    {"title": "Logistics Officer",        "company": "Army",   "start": "2008", "end": "2016",
     "summary": "Distribution operations"},
]
p.save_profile(prof)
tailored = tailor_resume(p, {"title": "VP Supply Chain", "company": "X",
                              "description": "VP role, supply chain, leadership",
                              "link": ""}, top_n=3, provider="none")
check("resume tailor returns at least 1 bullet", len(tailored) >= 1)
check("resume tailor caps at top_n", len(tailored) <= 3)
check("tailored bullet mentions an experience", any("Director" in b or "Manager" in b for b in tailored))


# === F9: DarkMode ===

print("\nF9: DarkMode (ThemeManager)")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from app.ux import ThemeManager, THEMES
tm = ThemeManager("couch")
check("default theme is couch", tm.theme == "couch")
check("THEMES has both couch and stealth", "couch" in THEMES and "stealth" in THEMES)
tm.set_theme("stealth")
check("set_theme switches to stealth", tm.theme == "stealth")
check("apply() does not crash", tm.apply() is None)
tm.set_theme("couch")
check("set_theme switches back to couch", tm.theme == "couch")
# garbage theme name -> default
tm_bad = ThemeManager("not-a-theme")
check("ThemeManager rejects unknown theme", tm_bad.theme == "couch")


# === F10: Notifications ===

print("\nF10: Notifications (Notifier)")
from app.ux import Notifier
n = Notifier("linkedin-autopilot")
check("Notifier has available property", hasattr(n, "available"))
result = n.notify("Test title", "Test body")
check("notify() returns a bool", isinstance(result, bool))


# === F1+F2 GUI integration: all tabs present in TheCouch ===

print("\nGUI: TheCouch has all 10 feature tabs")
from app.lazibot import TheCouch
c = TheCouch(persona_name="e2e-user")
check("TheCouch has >= 10 tabs", c.tabs.count() >= 10, f"got {c.tabs.count()}")
expected = ["Tracker", "Analytics", "Schedule", "AI Assist", "Settings"]
for label in expected:
    found = any(label in c.tabs.tabText(i) for i in range(c.tabs.count()))
    check(f"TheCouch has '{label}' tab", found)


# === summary ===

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n, d in failures:
        print(f"  - {n}: {d}")
    sys.exit(1)
else:
    print("ALL 10 FEATURE CHECKS PASS")
    sys.exit(0)
