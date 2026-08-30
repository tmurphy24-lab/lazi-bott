# LinkedIn AIHawk

## What this is
AI-powered LinkedIn auto-applier. GPT fills application questions and generates a tailored
resume + cover letter per job. Most mature AI bot of the four. Hardest to detect (uses
`invisible_playwright` — real patched Firefox fingerprint).

## Location
`C:\Users\trevo\Desktop\.agents\linkedin-aihawk` — standalone folder, no shared parent.

## Run
```
cd C:\Users\trevo\Desktop\.agents\linkedin-aihawk
python main.py
```

## Config files
| File | Purpose | Status |
|---|---|---|
| `data_folder/secrets.yaml` | `llm_api_key` | ✅ key present |
| `data_folder/work_preferences.yaml` | locations, job types, experience, blacklists | ✅ aligned to your search prefs |
| `data_folder/plain_text_resume.yaml` | your resume details | ⚠️ still has `[Your Name]` placeholders |
| `config.py` | app limits + LLM model | ✅ tuned |

## Current search settings (matched to your EasyApplyJobsBot config.py)
- Positions: Frontend, React, TypeScript, JavaScript, Vue, Python, Software Engineer,
  Junior Developer, Web Developer, Blockchain Developer
- Location: United States
- Experience: **entry only**
- Date posted: **past week**
- Remote / hybrid / onsite: all on
- `JOB_MAX_APPLICATIONS = 50` per run
- `MINIMUM_WAIT_TIME_IN_SECONDS = 30`

## Setup — 1 thing YOU must fill in
**`data_folder/plain_text_resume.yaml`** — replace every `[Your ...]` placeholder with your
real name, education, work history, skills, projects. The AI uses this to build the
per-job resumes and cover letters, so it is required for the resume-generation feature.

## Status
- Dependencies: selenium + webdriver-manager installed, import OK
- Search prefs aligned ✅
- Blocked on resume YAML before AI resume/cover generation works correctly.

## Output
`job_applications/` folder — CSV history of everything it applied to.
