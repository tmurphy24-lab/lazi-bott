# Job-apply-AI-agent

## What this is
Job **scraper + CV/cover-letter tailor**, NOT an auto-applier. It scrapes LinkedIn job listings,
analyses each description, then generates a CV and cover letter tailored to that specific job.
Web UI (Flask) plus a CLI. Complements the other bots rather than competing with them —
use it to produce the tailored CVs, then apply with one of the applier bots.

## Location
`C:\Users\trevo\Desktop\.agents\Job-apply-AI-agent` — standalone folder, no shared parent.

## Run — web UI (easiest)
```
cd C:\Users\trevo\Desktop\.agents\Job-apply-AI-agent
venv\Scripts\activate
job-apply-ai web
```
Then open http://localhost:5000

## Run — command line
```
job-apply-ai scrape --keyword "Frontend Developer" --location "United States" --max-jobs 10
job-apply-ai tailor --cv path/to/cv_template.docx --job path/to/job_description.txt
job-apply-ai batch --cv path/to/cv_template.docx --jobs-file path/to/jobs.xlsx
```

## Setup status
| Item | Status |
|---|---|
| Own venv | ✅ exists (`venv\Scripts\python.exe`, Python 3.13.15) |
| All 11 dependencies | ✅ installed and import OK (selenium, undetected-chromedriver, pandas, python-docx, spacy, bs4, openai, requests, openpyxl, flask, dotenv) |
| spaCy model `en_core_web_sm` | ✅ downloaded and loads |
| CLI entry point | ✅ verified working (`web` / `scrape` / `tailor` / `batch`) |
| OpenAI API key | ➖ **not required** — analysis uses local spaCy NLP, no key read anywhere in the code |

## Setup — 1 thing YOU must supply
**A base CV template as `.docx`.** You upload it in the web UI (or pass `--cv` on the CLI) and
the tool rewrites it per job. Without a CV template it has nothing to tailor.

## Notes
- Only bot here that does NOT auto-apply. It prepares application materials.
- Output: `job_apply_ai/outputs/jobs/` (Excel listings) and `job_apply_ai/outputs/cvs/`
- This folder's name uses a different convention from the others (`Job-apply-AI-agent` vs
  lowercase-hyphen). Left as-is to avoid breaking the venv's absolute paths — the venv was
  created inside this folder and hardcodes it.
- Has a `scraping.ipynb` notebook and `TESTING_GUIDE.md` for manual exploration.
