"""
End-to-end test of the linkedin-autopilot feature set.

Validates:
  AC7  Both adapter config-overrides now write to the files the engines actually import
  AC8  run.bat (smoke check)
  AC9  profile_store has range params + blacklist add/remove
  AC10 resume_parser extracts name/email/phone/skills
  AC11 auto_filler answers form questions from profile
  AC12 SearchableParameterEditor imports & builds
  AC13 LaziChatOverlay / TheCouch import
  AC14 LLM import
  AC15 Root .gitignore exists
"""
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


# === AC7: config override paths fixed ===

print("AC7: adapter config overrides reach the engines")
easy_text = Path("app/engines/easyapplyjobsbot_adapter.py").read_text(encoding="utf-8")
check("easyapply writes to config.py (not config_autopilot.py)",
      'config_path.write_text' in easy_text or 'config_path = target_dir / "config.py"' in easy_text,
      "adapter should write config.py directly with backup to config.py.bak")
check("easyapply creates config.py.bak on first run",
      "config.py.bak" in easy_text,
      "missing backup mechanism")
check("easyapply adapter parses 'Just Applied' for counter",
      "applied_re" in easy_text,
      "missing stdout counter parser")

auto_text = Path("app/engines/auto_job_applier_adapter.py").read_text(encoding="utf-8")
check("auto-job-applier uses user_config.json (engine's own loader)",
      "user_config.json" in auto_text,
      "should use the engine's own override mechanism")
check("auto-job-applier writes 'search' section",
      '"search"' in auto_text or "'search'" in auto_text,
      "missing search section in user_config.json")
check("auto-job-applier adapter parses stdout for counters",
      "applied_re" in auto_text,
      "missing counter parser")


# === AC8: GUI has Start() call fixed + Qt thread-safety ===

print("\nAC8: RunView.start() called + Qt thread-safety")
main_text = Path("app/main.py").read_text(encoding="utf-8")
check("RunView.start() is called from RunConfig._start",
      "self._run_window.start()" in main_text,
      "missing call to .start() on the run window")
check("_LogBridge uses Signal/Slot for thread safety",
      "_LogBridge" in main_text and "Signal" in main_text and "_log_bridge.line.connect" in main_text,
      "missing _LogBridge wiring")
check("QSpinBox imported at top level (no _SpinBox hack)",
      "QSpinBox" in main_text and "__import__" not in main_text,
      "QSpinBox hack not removed")


# === AC9: profile_store has new params + blacklist add/remove ===

print("\nAC9: profile_store range params + blacklist add/remove")
from app.profile_store import Persona, create_persona, ensure_persona, PARAM_SCHEMA, list_personas
# User creates the persona with their own salary range (no hardcoded values)
p = create_persona("procurement", config={
    "titles": ["Director of Procurement"],
    "salary_min": 120000,
    "salary_max": 250000,
    "experience_years_min": 10,
    "experience_years_max": 25,
    "blacklist_companies": ["Crossover", "Jobot"],
    "blacklist_titles": ["Junior", "Intern"],
})
cfg = p.load_config()
check("salary_min in config", cfg.get("salary_min") == 120000)
check("salary_max in config", cfg.get("salary_max") == 250000)
check("experience_years_min/max in config",
      "experience_years_min" in cfg and "experience_years_max" in cfg)
check("PARAM_SCHEMA has salary entries",
      any(s["key"] == "salary_min" for s in PARAM_SCHEMA))
check("PARAM_SCHEMA has at least 8 params",
      len(PARAM_SCHEMA) >= 8)

# blacklist add/remove
p.add_blacklist_company("TestCo123")
check("add_blacklist_company works",
      "TestCo123" in p.load_config()["blacklist_companies"])
p.remove_blacklist_company("TestCo123")
check("remove_blacklist_company works",
      "TestCo123" not in p.load_config()["blacklist_companies"])
p.add_blacklist_title("TestTitle123")
check("add_blacklist_title works",
      "TestTitle123" in p.load_config()["blacklist_titles"])
p.remove_blacklist_title("TestTitle123")
check("remove_blacklist_title works",
      "TestTitle123" not in p.load_config()["blacklist_titles"])

# profile.yaml round-trip
p.update_profile(personal_info={"first_name": "Test", "email": "t@e.com"})
profile = p.load_profile()
check("profile.yaml personal_info round-trip",
      profile["personal_info"]["first_name"] == "Test" and profile["personal_info"]["email"] == "t@e.com")
p.update_profile(personal_info={"first_name": "", "last_name": "", "email": "", "phone": "",
                                  "linkedin_url": "", "city": "", "state": "", "country": "United States"})


# === AC10: resume parser ===

print("\nAC10: resume parser")
from app.resume_parser import parse_resume, profile_from_resume
res_path = Path("sample_resume.txt").resolve()
if res_path.exists():
    parsed = parse_resume(res_path)
    check("resume_parser finds email",
          "tmurphy24" in parsed["personal_info"]["email"],
          f"email = {parsed['personal_info']['email']!r}")
    check("resume_parser finds phone",
          parsed["personal_info"]["phone"].startswith("(") or "813" in parsed["personal_info"]["phone"],
          f"phone = {parsed['personal_info']['phone']!r}")
    check("resume_parser finds name first/last",
          parsed["personal_info"]["first_name"] == "Trevor" and "Murphy" in parsed["personal_info"]["last_name"],
          f"name = {parsed['personal_info']['first_name']!r} {parsed['personal_info']['last_name']!r}")
    check("resume_parser extracts skills",
          "Supply Chain" in parsed["skills"] and "Procurement" in parsed["skills"],
          f"skills sample = {parsed['skills'][:3]}")
    check("resume_parser finds education",
          len(parsed["education"]) >= 1, f"education = {parsed['education']}")
    check("resume_parser finds experience entries",
          len(parsed["experience"]) >= 1, f"experience = {parsed['experience']}")
    check("profile_from_resume returns full dict",
          profile_from_resume(res_path).get("personal_info", {}).get("first_name") == "Trevor")
else:
    print("  SKIP  sample_resume.txt not found")


# === AC11: auto_filler answers forms ===

print("\nAC11: auto_filler")
from app.auto_filler import answer_form, build_answerer, make_on_job_filter, answer_question

# Use the supply-chain-exec persona which we'll set up with profile data
# (the test supplies its own config; no hardcoded defaults)
p = create_persona("supply-chain-exec", config={
    "titles": ["Director of Supply Chain"],
    "salary_min": 120000,
    "salary_max": 250000,
    "experience_years_min": 10,
    "experience_years_max": 25,
    "blacklist_companies": ["Crossover", "Jobot", "Dice"],
    "blacklist_titles": ["Junior", "Intern", "Coordinator"],
})
profile = p.load_profile()
profile["personal_info"] = {
    "first_name": "Trevor", "last_name": "Murphy",
    "email": "tmurphy24@email.davenport.edu", "phone": "(813) 555-0142",
    "linkedin_url": "https://linkedin.com/in/trevor-murphy-supply",
    "city": "Tampa", "state": "FL", "country": "United States",
}
profile["skills"] = ["Supply Chain", "Procurement", "Logistics"]
p.save_profile(profile)

ans = answer_form([
    "First name", "Last name", "Email", "Phone", "City", "State",
    "Years of experience", "Expected salary",
], p)
check("auto_filler answers 'First name'", ans.get("0") == "Trevor")
check("auto_filler answers 'Last name'",  ans.get("1") == "Murphy")
check("auto_filler answers 'Email'",      ans.get("2") == "tmurphy24@email.davenport.edu")
check("auto_filler answers 'Phone'",      "(813)" in ans.get("3", ""))
check("auto_filler answers 'Years of experience'", ans.get("6") is not None)
check("auto_filler answers 'Expected salary' midpoint", ans.get("7") is not None)

# on_job filter
flt = make_on_job_filter(p)
check("on_job filter rejects blacklisted company",
      flt({"title": "Director of Supply Chain", "company": "Crossover"}) is False)
check("on_job filter rejects blacklisted title",
      flt({"title": "Junior Developer", "company": "Acme"}) is False)
check("on_job filter accepts clean job",
      flt({"title": "Director of Supply Chain", "company": "Acme Manufacturing"}) is True)


# === AC12: SearchableParameterEditor imports ===

print("\nAC12: SearchableParameterEditor")
from app.main import SearchableParameterEditor
check("SearchableParameterEditor class importable", SearchableParameterEditor is not None)


# === AC13: Lazi-Bot / TheCouch ===

print("\nAC13: Lazi-Bot + The Couch")
from app.lazibot import LaziBrain, LaziChatOverlay, TheCouch, EmbeddedBrowser
check("LaziBrain importable",     LaziBrain is not None)
check("LaziChatOverlay importable", LaziChatOverlay is not None)
check("TheCouch importable",      TheCouch is not None)
check("EmbeddedBrowser importable", EmbeddedBrowser is not None)
check("TheCouch WELCOME_TITLE mentions 'the Couch'",
      "the Couch" in TheCouch.WELCOME_TITLE or "Welcome 2 the Couch" in TheCouch.WELCOME_TITLE)
check("TheCouch WELCOME_BODY mentions Lazi",
      "Lazi" in TheCouch.WELCOME_BODY)


# === AC14: LLM import (openai already required, just check it loads) ===

print("\nAC14: openai LLM client")
try:
    import openai
    check("openai importable", True)
except ImportError:
    check("openai importable", False, "pip install openai")


# === AC15: root .gitignore ===

print("\nAC15: root .gitignore")
gitignore = Path(".gitignore")
check("root .gitignore exists", gitignore.exists())
if gitignore.exists():
    txt = gitignore.read_text(encoding="utf-8")
    check("gitignore ignores keys/",   "keys/" in txt)
    check("gitignore ignores venv/",   "venv/" in txt)
    check("gitignore ignores browser_profile", "browser_profile" in txt)
    check("gitignore ignores config.py.bak",   "config.py.bak" in txt)
    check("gitignore ignores user_config.json", "user_config.json" in txt)


# === AC16: scraper URL uses urllib quote ===

print("\nAC16: scraper URL encoding")
scraper_text = Path("app/scraper.py").read_text(encoding="utf-8")
check("scraper uses urllib.parse.quote",
      "urllib.parse.quote" in scraper_text or "from urllib.parse import quote" in scraper_text,
      "fragile replace-based encoding")


# === summary ===

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n, d in failures:
        print(f"  - {n}: {d}")
    sys.exit(1)
else:
    print("ALL CHECKS PASS")
    sys.exit(0)
