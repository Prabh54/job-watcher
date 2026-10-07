# job-watcher

Hourly cloud check for new SWE / data **intern and co-op** postings in Canada and the US. Each new posting is pushed to my phone and synced into `job_queue.xlsx` on my Mac, where it feeds my resume-tailoring script.

## Sources
- **LinkedIn**: Apify `curious_coder/linkedin-jobs-scraper`, with JobSpy as a backup. Searches "software intern" and "software co-op" in Canada, California and Texas.
- **Repos**: speedyapply USA internships, Zapply Internships-2027, Simplify off-season, Zapply Canada-Internships-2027, negarprh Canadian-Tech-Internships-2027.

## How it runs
- `.github/workflows/watch.yml` runs `watcher.py` every hour.
- LinkedIn is skipped from 1:00 to 5:59 Vancouver time. The 6am run looks back over the night, so nothing is missed.
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
- `LINKEDIN_LIMIT_PER_SEARCH` and `LINKEDIN_MAX_ITEMS_PER_RUN`: Apify cost guards
- `ROLE_WORDS` and `EXCLUDE_WORDS`: which titles count
- `LINKEDIN_QUIET_HOURS`: when LinkedIn is skipped overnight
