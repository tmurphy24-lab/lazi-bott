# Auto_job_applier_linkedIn

## What this is
Fastest bulk auto-applier — 100+ applications/hour. AI writes a custom resume for EACH job
posting individually. LangChain/LangGraph pipeline answers application questions.

## Location
`C:\Users\trevo\Desktop\.agents\auto-job-applier` — standalone folder, no shared parent.

## Run
```
cd C:\Users\trevo\Desktop\.agents\auto-job-applier
python runAiBot.py
```
Dashboard (applied-jobs history UI):
```
python app.py      # then open http://localhost:5001
```

## Config files
| File | Purpose | Status |
|---|---|---|
| `config/personals.py` | name, phone, address, EEO answers | ⚠️ phone still placeholder |
| `config/search.py` | search terms, location, salary, filters | ✅ aligned to your prefs |
| `config/questions.py` | answer bank for app questions | ⚠️ defaults, worth filling |
| `config/resume.py` | resume details | ⚠️ defaults |
| `config/settings.py` | stealth, driver, run mode | ✅ tuned |

## Current search settings (matched to your EasyApplyJobsBot config.py)
- Search terms: Frontend, React, TypeScript, JavaScript, Vue, Python, Software Engineer,
  Junior Developer, Web Developer, Blockchain Developer
- Location: United States
- Salary: **$80,000+**
- Date posted: **Past week**
- Sort by: **Most recent**
- `switch_number = 30` — rotates to next search term every 30 applications

## Key settings already set in config/settings.py
- `run_in_background = False` — browser visible so you can watch it
- `safe_mode = True` — guest Chrome profile
- `keep_screen_awake = True`
- `alternate_sortby = True`, `cycle_date_posted = True`
- `auto_manage_driver = True` — auto-downloads matching ChromeDriver
- `click_gap = 1`

## Setup — 1 thing YOU must fill in
**`config/personals.py`** line 27 → replace `YOUR_PHONE_NUMBER` with your real 10-digit number.
Phone is required by most Easy Apply forms; the bot will stall without it.

## Status
- All dependencies installed and import OK (selenium, undetected-chromedriver, pyautogui,
  langchain, langgraph, fpdf2, python-docx, flask)
- Search prefs aligned ✅
- Blocked on phone number only.

## Output
- `all excels/all_applied_applications_history.csv` — applied jobs
- `all excels/all_failed_applications_history.csv` — failures
- `all resumes/` — per-job AI-generated resumes
- `logs/` — run logs
