# EasyApplyJobsBot (original / baseline bot)

## What this is
The original Python + Selenium LinkedIn Easy Apply bot. Config-driven, no AI — it follows the
filters in `config.py` strictly and applies to matching Easy Apply jobs. This is the baseline
the other three bots were tuned to match.

Author site rebranded: the old `automated-bots.com` is now **apllie.com** (a Chrome extension).
This local Python copy is still fully functional and independent of that service.

## Location
`C:\Users\trevo\Desktop\.agents\EasyApplyJobsBot` — standalone folder, no shared parent.

## Run
```
cd C:\Users\trevo\Desktop\.agents\EasyApplyJobsBot
python linkedin.py
```

## Setup status
| Item | Status |
|---|---|
| Credentials in `config.py` | ✅ `tmurphy24@email.davenport.edu` |
| Dependencies | ✅ selenium, webdriver-manager, selenium-stealth, pyyaml — all import OK |
| `chrome-profile/` folder | ✅ exists (persistent login session) |
| `chromeProfilePath` | ✅ points at the chrome-profile folder |
| stale URLs | ✅ fixed to apllie.com |
| `maxApplicationsPerRun` | ✅ set to 50 (safety cap) |

## Current search settings (the reference the other bots were matched to)
- Keywords: frontend, react, typescript, javascript, vue, python, programming, blockchain
- Location: NorthAmerica
- Experience: Entry level
- Date posted: Past Week
- Job type: Full-time, Part-time, Contract
- Remote: On-site, Remote, Hybrid
- Salary: $80,000+
- Sort: Recent

## Safety switches in config.py
- `dryRun = False` — flip to `True` to rehearse a run WITHOUT submitting any applications.
  Do this first when testing.
- `maxApplicationsPerRun = 50` — stops after 50 applications in one run.
- `headless = False` — browser stays visible so you can watch it work.

## Notes
- Saves cookies to `cookies/` after first login, so later runs skip the login step
- Output: applied-jobs data file under `data/`
- No AI — it cannot handle unusual or unseen application questions, unlike the other three bots
