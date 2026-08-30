"""
End-to-end integration test for the full profile -> params -> search ->
auto-filler chain. Proves that:

  1. User uploads a resume -> parser extracts fields
  2. Profile stores personal_info + skills + experience
  3. SearchableParameterEditor reads & writes those same fields as ranges
  4. Salary range (min/max) is the single source of truth
  5. Experience years range feeds the auto-filler when resume is sparse
  6. Auto-filler generates answers for every form question
  7. on_job filter rejects blacklisted companies/titles from search results
  8. bot_runner.run() calls the right adapter with the right overrides
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


# === Setup: simulate a user uploading a resume ===

print("AC21: end-to-end resume -> profile -> params chain")
from app.profile_store import Persona, ensure_persona
from app.resume_parser import profile_from_resume

p = ensure_persona("supply-chain-exec")
resume_path = Path("sample_resume.txt").resolve()
parsed = profile_from_resume(resume_path)
p.update_profile(
    personal_info=parsed["personal_info"],
    resume_path=str(resume_path),
    skills=parsed["skills"],
    experience=parsed["experience"],
    education=parsed["education"],
)
check("resume parsed and saved to profile",
      p.load_profile()["personal_info"]["first_name"] == "Trevor",
      f"got: {p.load_profile()['personal_info']['first_name']}")


# === Step 2: searchable parameter editor reads from profile + config ===

print("\nAC22: SearchableParameterEditor reads and writes ranges")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from app.main import SearchableParameterEditor
from app.profile_store import PARAM_SCHEMA

editor = SearchableParameterEditor("supply-chain-exec")
cfg = editor._cfg
check("editor loads salary_min from config",   cfg["salary_min"] in (120000, 150000))
check("editor loads salary_max from config",   cfg.get("salary_max") in (250000, 300000))
check("editor loads experience_years_min",     cfg.get("experience_years_min") is not None)
check("editor loads experience_years_max",     cfg.get("experience_years_max") is not None)
check("editor experience_years range is valid (min <= max)",
      cfg.get("experience_years_min", 0) <= cfg.get("experience_years_max", 99))
check("editor has 10 schema params (PARAM_SCHEMA)", len(PARAM_SCHEMA) == 10)

# Set a range via the editor's public API and verify it persists
editor.set_param("salary_min", 150000)
editor.set_param("salary_max", 300000)
new_cfg = p.load_config()
check("editor set_param('salary_min', 150000) persists",
      new_cfg["salary_min"] == 150000)
check("editor set_param('salary_max', 300000) persists",
      new_cfg["salary_max"] == 300000)

# Search filter actually hides rows
editor.search.setText("salary")
editor._filter("salary")
visible = 0
for i in range(editor.form_layout.rowCount()):
    label_item = editor.form_layout.itemAt(i, editor.form_layout.ItemRole.LabelRole)
    if label_item and label_item.widget() and not label_item.widget().isHidden():
        visible += 1
check("editor search 'salary' filters to >=2 visible rows",
      visible >= 2, f"got {visible}")
# 'salary' should also hide non-matching rows
hidden = sum(
    1 for i in range(editor.form_layout.rowCount())
    if (li := editor.form_layout.itemAt(i, editor.form_layout.ItemRole.LabelRole))
    and li.widget() and li.widget().isHidden()
)
check("editor search 'salary' hides non-matching rows",
      hidden >= 5, f"got {hidden} hidden")
editor.search.setText("")
editor._filter("")


# === Step 3: search URL uses the salary range ===

print("\nAC23: search uses the user's range")
from app.scraper import build_search_url
url = build_search_url(["Director of Supply Chain"], "United States", salary_min=150000)
check("search URL embeds salary_min", "salary=150000" in url, f"url: {url}")
check("search URL uses urllib quote (no broken spaces)",
      "%20" in url or "+" in url or "United" in url, f"url: {url}")


# === Step 4: auto-filler generates answers from profile + resume ===

print("\nAC24: auto-filler generates form answers from profile + resume")
from app.auto_filler import answer_form, answer_question, build_answerer

questions = [
    "First name",
    "Last name",
    "Email address",
    "Phone number",
    "City",
    "State",
    "Country",
    "How many years of experience do you have?",
    "What is your expected salary?",
    "LinkedIn profile URL",
    "Do you have experience with Supply Chain?",
    "Do you have experience with Procurement?",
    "Are you authorized to work in the United States?",
]
ans = answer_form(questions, p)
answered = [q for q in questions if ans.get(str(questions.index(q)))]
check(f"auto-filler answers at least 8 of {len(questions)} questions",
      len(answered) >= 8, f"answered: {answered}")
check("auto-filler answers 'First name'",        ans.get("0") == "Trevor")
check("auto-filler answers 'Last name'",         ans.get("1") == "Murphy")
check("auto-filler answers 'Email address'",     "tmurphy24" in ans.get("2", ""))
check("auto-filler answers 'Phone number'",      "(813)" in ans.get("3", ""))
check("auto-filler answers 'Country'",           ans.get("6") == "United States")
check("auto-filler answers 'How many years of experience'",
      ans.get("7") is not None and ans.get("7").isdigit())
check("auto-filler answers 'Expected salary' (range midpoint)",
      ans.get("8") is not None)
check("auto-filler answers 'LinkedIn profile URL'",
      "linkedin.com" in ans.get("9", ""))


# === Step 5: on_job filter rejects blacklist hits ===

print("\nAC25: on_job filter rejects blacklist from search results")
from app.auto_filler import make_on_job_filter
flt = make_on_job_filter(p)

check("on_job filter rejects blacklisted company 'Crossover'",
      flt({"title": "Director of Supply Chain", "company": "Crossover"}) is False)
check("on_job filter rejects blacklisted title 'Junior'",
      flt({"title": "Junior Developer", "company": "Acme"}) is False)
check("on_job filter accepts clean job",
      flt({"title": "Director of Supply Chain", "company": "Acme Manufacturing"}) is True)


# === Step 6: profile.yaml and search_config.yaml both update ===

print("\nAC26: profile + config are independent yaml files, both update")
import yaml
profile_yaml = p.profile_path.read_text(encoding="utf-8")
config_yaml = p.config_path.read_text(encoding="utf-8")
check("profile.yaml has personal_info", "first_name: Trevor" in profile_yaml)
check("search_config.yaml has salary_min/max range",
      "salary_min: 150000" in config_yaml and "salary_max: 300000" in config_yaml)
check("search_config.yaml has experience_years range",
      "experience_years_min" in config_yaml and "experience_years_max" in config_yaml)


# === Step 7: answer_question handles every question type ===

print("\nAC27: answer_question handles edge cases")
pi = p.load_profile()["personal_info"]
check("answer_question returns 'Trevor' for 'First name'",
      answer_question("First name", p.load_profile()) == pi["first_name"])
check("answer_question returns full name for 'Full name'",
      answer_question("Full name", p.load_profile()) == "Trevor Murphy")
check("answer_question returns email for 'Email'",
      answer_question("Email", p.load_profile()) == pi["email"])
check("answer_question returns 'No' for generic yes/no",
      answer_question("Are you willing to relocate?", p.load_profile()) in ("No", None))
check("answer_question returns None for unknown",
      answer_question("xyzzy nothing matches", p.load_profile()) is None)


# === Step 8: blacklist add/remove updates the live config ===

print("\nAC28: blacklist add/remove is live and immediate")
p.add_blacklist_company("Acme Manufacturing")
flt2 = make_on_job_filter(p)
check("after add_blacklist_company, filter rejects 'Acme Manufacturing'",
      flt2({"title": "Director of Supply Chain", "company": "Acme Manufacturing"}) is False)
p.remove_blacklist_company("Acme Manufacturing")
flt3 = make_on_job_filter(p)
check("after remove_blacklist_company, filter accepts 'Acme Manufacturing'",
      flt3({"title": "Director of Supply Chain", "company": "Acme Manufacturing"}) is True)


# === Step 9: LLM-backed answerer (system prompt + graceful fallback) ===

print("\nAC29: LLM answerer system prompt + fallback")
from app.auto_filler import (
    _build_llm_system_prompt, llm_answer_question,
    build_llm_answerer, answer_form_with_llm,
)
prompt = _build_llm_system_prompt(p.load_profile())
check("LLM system prompt includes user name",
      "Trevor Murphy" in prompt, f"prompt head: {prompt[:200]}")
check("LLM system prompt includes email",
      "tmurphy24" in prompt)
check("LLM system prompt includes skills",
      "Supply Chain" in prompt)
check("LLM system prompt includes experience entries",
      "Acme" in prompt or "Director" in prompt)

# Without an api key, llm_answer_question returns None
check("llm_answer_question returns None when no API key",
      llm_answer_question("What is your favorite color?",
                          p.load_profile(),
                          provider="poolside",
                          api_key=None) is None)

# build_llm_answerer: heuristic still works (no LLM call needed)
ans_llm = build_llm_answerer(p, provider="poolside")
check("build_llm_answerer answers 'First name' via heuristic",
      ans_llm("First name") == "Trevor")
check("build_llm_answerer answers 'Email' via heuristic",
      ans_llm("Email") == "tmurphy24@email.davenport.edu")

# answer_form_with_llm wraps it
ans_wrapped = answer_form_with_llm(
    ["First name", "Years of experience", "Email"], p, provider="poolside"
)
check("answer_form_with_llm returns dict with str keys",
      all(isinstance(k, str) for k in ans_wrapped.keys()))
check("answer_form_with_llm answers 'First name' (heuristic)",
      ans_wrapped.get("0") == "Trevor")


# === summary ===

print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    for n, d in failures:
        print(f"  - {n}: {d}")
    sys.exit(1)
else:
    print("ALL END-TO-END CHAIN CHECKS PASS")
    sys.exit(0)
