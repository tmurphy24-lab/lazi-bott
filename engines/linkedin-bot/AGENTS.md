# LinkedinBOT

## What this is
Cleanest OpenAI-powered LinkedIn auto-applier. OpenAI answers custom application questions
using your resume text. Simple CLI prompts walk you through each run.

## Location
`C:\Users\trevo\Desktop\.agents\linkedin-bot` — standalone folder, no shared parent.

## Run
```
cd C:\Users\trevo\Desktop\.agents\linkedin-bot
python easy_apply.py
```

## Setup — 2 things YOU must fill in
1. **`.env`** → replace `YOUR_OPENAI_API_KEY_HERE` with a real key
   (get one at https://platform.openai.com/api-keys)
   ```
   OPENAI_API_KEY=sk-...
   SKIP_EDUCATION_FORM=false
   LINKEDIN_PREMIUM=false
   ```
2. **`resume.txt`** → paste your real resume text. The bot feeds this to OpenAI to answer
   application questions, so more detail = better answers. Include name, email, phone,
   location, education, work history, skills, certifications.

## Status
- Dependencies installed: selenium, webdriver-manager, openai — all import OK
- pygame NOT installed (sound effects only, not needed). Bot runs fine without it.
- `resume.txt` — DONE, filled with real Trevor Murphy data
- Blocked until OpenAI key is put in `.env` (only remaining blocker)

## Job search query — what to type at the prompt
This bot has **no persistent search config**. It pops up a box at runtime asking for your
job query (`easy_apply.py:650`), so there is nothing to pre-configure — you type it each run.

**This bot runs PERSONA 2 — Procurement & Supplier Fulfillment.**
Type ONE of these per run (LinkedIn search is title-weighted, so use exact titles,
not broad words like "sourcing" or "planning"):

```
Director of Procurement
Head of Procurement
Senior Procurement Manager
Strategic Sourcing Manager
Category Manager
Supplier Fulfillment Manager
Materials Manager
Supplier Performance Manager
Purchasing Manager
Head of Supplier Management
```

After the results load, the bot pauses so you can hand-apply filters in the browser.
Set those filters to: **Mid-Senior level + Director**, **$120,000+**, **Past week**.

## Notes
- Fewest config files of the five bots — no YAML, no separate search-config
- Prompts you interactively for the job title on each run
- Set `LINKEDIN_PREMIUM=true` in `.env` if you have LinkedIn Premium
- Hardcoded to the OpenAI SDK (`utils/ai.py` calls `openai.OpenAI(api_key=...)` with no
  `base_url`). Gemini/Poolside would need a code edit — see profile notes.
