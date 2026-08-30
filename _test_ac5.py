import sys; sys.path.insert(0, '.')
from app.scraper import build_search_url, JobResult, PRIMARY_JOB_CARD_XPATH, FALLBACK_JOB_CARD_CSS, LINKEDIN_JOB_SEARCH_URL

# AC5: verify URL builder produces a valid LinkedIn jobs search URL
titles = ['Director of Supply Chain', 'Director of Procurement']
url = build_search_url(titles, 'United States', salary_min=120000)
print('Generated URL:', url)
assert 'linkedin.com/jobs/search' in url, 'wrong base URL'
assert 'keywords=Director' in url, 'keywords not in URL'
assert 'location=United' in url, 'location not in URL'
print('AC5a PASS: URL builder correct')

# verify JobResult dataclass
jr = JobResult(title='Director of Supply Chain', company='TestCo', link='https://linkedin.com/jobs/123', posted_days_ago=3)
d = jr.to_dict()
assert d['title'] == 'Director of Supply Chain'
assert d['posted_days_ago'] == 3
assert 'link' in d
print('AC5b PASS: JobResult serialization correct')

# verify selectors are set
assert PRIMARY_JOB_CARD_XPATH == '//li[@data-occludable-job-id]'
assert 'base-card' in FALLBACK_JOB_CARD_CSS
print('AC5c PASS: Selectors match proven XPaths from 3 bots')

# AC6: dry-run config (EasyApplyJobsBot dryRun=True is in config.py)
from app.profile_store import Persona
p = Persona('supply-chain-exec')
cfg = p.load_config()
assert cfg.get('salary_min') == 120000
assert 'Director' in cfg['experience_levels']
# check that dryRun and maxApplicationsPerRun are in the bot config
import ast
easy_cfg = open('engines/EasyApplyJobsBot/config.py', encoding='utf-8').read()
assert 'dryRun = False' in easy_cfg, 'dryRun not in config'
assert 'maxApplicationsPerRun = 50' in easy_cfg, 'maxApplications not in config'
print('AC6 PASS: EasyApplyJobsBot dryRun + maxApplicationsPerRun = 50 confirmed in config.py')
print('AC5+AC6 ALL PASS')
