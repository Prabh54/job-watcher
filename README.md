# job-watcher

Hourly cloud check for new SWE / data **intern and co-op** postings in Canada and the US. Each new posting is pushed to my phone and synced into `job_queue.xlsx` on my Mac, where it feeds my resume-tailoring script.

## Sources
- **LinkedIn**: Apify `curious_coder/linkedin-jobs-scraper`, with JobSpy as a backup. Searches "software intern" and "software co-op" in Canada, California and Texas.
- **Repos**: speedyapply USA internships, Zapply Internships-2027, Simplify off-season, Zapply Canada-Internships-2027, negarprh Canadian-Tech-Internships-2027.

## Filters
- **Roles (SWE first):** intern or co-op titles in software, full-stack, backend, frontend, mobile, cloud/devops, ML/AI engineering, data engineering or data science. Analyst, QA/test, IT support, research-only, and architect/consultant titles are dropped, along with senior, PhD/master's, hardware/embedded, and French-required roles.
- **Locations:** all of Canada and all of the US from the repos. LinkedIn searches Canada, California and Texas.
- **US eligibility** (I need sponsorship for the US; Canadian roles are never filtered on this). A US role is dropped if:
  - Simplify marks it 🛂 or 🇺🇸, or
  - its job description asks for US citizenship, a security clearance or ITAR "U.S. person" status, or says it won't sponsor.
- **Visa labels on kept US roles** (shown in the push and the Excel Visa column):
  - `sponsors ✅`: Zapply says it sponsors.
  - `no restriction found`: the JD was checked and nothing blocking turned up.
  - `check sponsorship`: there was no JD to check.

## How it runs
- `.github/workflows/watch.yml` runs `watcher.py` every hour.
- Nothing runs from 11pm to 6:59am Vancouver time (no LinkedIn calls, no pushes). The 7am run looks back over the whole night, so nothing is missed.
- Each LinkedIn check looks back over the time since the last successful check plus a 30-minute buffer (minimum 90 minutes). A delayed or skipped run never leaves a gap.
- New jobs are written to `data/new/<timestamp>.json` and kept for 21 days. `sync.py` on the Mac pulls them into Excel.
- `data/seen.json` holds the duplicate memory: links, plus company + role for 30 days.
- `data/health.json` tracks alerts and daily counters.
- `data/backlog.csv` lists everything that was already open on the first run.

## Phone alerts (ntfy)
- One push per new job. Tap it to open the posting.
- 🚨 when LinkedIn fails on both Apify and JobSpy, or the run crashes.
- ⚠️ when Apify fails but JobSpy covered it, LinkedIn returns 0 for 3 daytime runs, a repo fails 3 runs in a row, LinkedIn hits the per-run cap, or GitHub skips runs.
- 📋 a daily summary at 9pm. **If it doesn't arrive, something is broken: check the Actions tab and LinkedIn manually.**

## Secrets
`APIFY_TOKEN` and `NTFY_TOPIC`, under Settings → Secrets and variables → Actions.

## Run it by hand
Go to Actions → job-watcher → Run workflow.

## Tuning
Edit the CONFIG block at the top of `watcher.py`:
- `LINKEDIN_KEYWORDS` and `LINKEDIN_LOCATIONS`: what LinkedIn searches
- `LINKEDIN_LIMIT_PER_SEARCH`: Apify cost guard (scales up for the 7am catch-up)
- `ROLE_WORDS` and `EXCLUDE_WORDS`: which titles count
- `VISA_BLOCK_PATTERNS`: which phrases in a description rule out a US role
- `QUIET_HOURS`: the night pause
