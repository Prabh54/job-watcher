"""
watcher.py — finds new SWE / data internship and co-op postings, pushes each one to your phone,
and saves them in data/new/ so sync.py on your Mac can add them to job_queue.xlsx.

Runs hourly on GitHub Actions (.github/workflows/watch.yml). Nothing here touches your laptop.

Sources
  LinkedIn  — Apify "curious_coder/linkedin-jobs-scraper" (no login, never touches your account).
              If Apify fails, JobSpy is used as a backup for that run.
              Searches: "software intern" + "software co-op" in Canada, California, Texas.
  Repos     — speedyapply USA internships, Zapply Internships-2027, Simplify off-season,
              Zapply Canada-Internships-2027, negarprh Canadian-Tech-Internships-2027.

Each run
  1. Pull every source.
  2. Keep intern / co-op roles in SWE, data, AI/ML located in Canada, the US or remote.
  3. Drop anything already seen (same link, or same company + role in the last 30 days).
  4. Fetch the job description where possible (LinkedIn, Greenhouse, Lever, Ashby, Workday,
     SmartRecruiters, Workable, and any page that publishes standard job-posting data).
  5. Push each new job to your phone (ntfy) and write them to data/new/<timestamp>.json.
  6. Push an alert if a source is failing, and a daily summary at 9pm Vancouver time.

First run: everything currently open is saved to data/backlog.csv and marked as seen, so you
don't get hundreds of pushes. Only postings that appear after that are sent.

Secrets (GitHub repo → Settings → Secrets and variables → Actions):
  APIFY_TOKEN   your Apify API token
  NTFY_TOPIC    your ntfy topic name
"""

import csv
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse
from zoneinfo import ZoneInfo

import requests

# =====================================================================================
# CONFIG
# =====================================================================================

TZ = ZoneInfo("America/Vancouver")

# --- LinkedIn ------------------------------------------------------------------------
LINKEDIN_KEYWORDS = ["software intern", "software co-op"]
LINKEDIN_LOCATIONS = [            # (name LinkedIn understands, LinkedIn geoId)
    ("Canada", "101174742"),
    ("California, United States", "102095887"),
    ("Texas, United States", "102748797"),
]
# Each run looks back over the time since the last successful LinkedIn check plus a 30-minute
# buffer (LinkedIn sometimes lists a job a few minutes after its "posted" time), never less than
# 90 minutes and never more than 24 hours. So a late or skipped run never leaves a gap.
LINKEDIN_MIN_LOOKBACK_MIN = 90
LINKEDIN_BUFFER_MIN = 30
LINKEDIN_LIMIT_PER_SEARCH = 30    # max jobs per search for a normal hourly run (~90 min window).
                                  # Longer windows (the 7am catch-up) scale this up, to at most 150.

# --- Night pause ---------------------------------------------------------------------
# Nothing runs from 11pm to 6:59am Vancouver time: no LinkedIn calls (saves Apify credit) and no
# pushes. The 7am run looks back over the whole night on LinkedIn, and the repos keep everything
# they added overnight, so nothing posted at night is missed; you just hear about it at 7am.
QUIET_HOURS = {23, 0, 1, 2, 3, 4, 5, 6}

APIFY_ACTOR = "curious_coder~linkedin-jobs-scraper"
APIFY_RUN_TIMEOUT_SEC = 600

# --- Repos ---------------------------------------------------------------------------
REPOS = {
    "speedyapply USA": ("md", "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md"),
    "Zapply 2027": ("md", "https://raw.githubusercontent.com/zapplyjobs/Internships-2027/main/README.md"),
    "Simplify off-season": ("html", "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README-Off-Season.md"),
    "Zapply Canada": ("md", "https://raw.githubusercontent.com/zapplyjobs/Canada-Internships-2027/main/README.md"),
    "negarprh Canada": ("md", "https://raw.githubusercontent.com/negarprh/Canadian-Tech-Internships-2027/main/README.md"),
}

# --- Filters -------------------------------------------------------------------------
INTERN_WORDS = r"\b(intern|interns|internship|internships|co-?op|coop|student|placement)\b"
# SWE first: software / full-stack / backend / frontend / mobile / cloud / devops, ML & AI
# engineering, data engineering and data science. Analyst, QA/test, IT support, research-only
# and architect/consultant titles are dropped.
ROLE_WORDS = (
    r"\b(software|developer|swe|sde|programmer|back[- ]?end|front[- ]?end|full[- ]?stack|web|"
    r"mobile|ios|android|cloud|devops|platform|site reliability|sre|infrastructure|"
    r"machine learning|ml|ai|artificial intelligence|computer science|"
    r"data engineer\w*|data science|data scientist|data platform|data infrastructure)\b"
)
EXCLUDE_WORDS = (
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|phd|ph\.d|doctoral|postdoc|mba|"
    r"master'?s|masters|graduate student|high school|new grad|new graduate|"
    r"hardware|firmware|embedded|asic|fpga|rtl|verification|electrical|mechanical|civil|"
    r"chemical|manufacturing|supplier|sales|marketing|recruit\w*|human resources|accounting|"
    r"legal|nurs\w*|clinical|french|bilingual|"
    r"analyst|business intelligence|qa|quality assurance|test|tester|testing|sdet|"
    r"it support|help ?desk|technical support|desktop support|support engineer|information technology|"
    r"architect|consultant|consulting|solutions engineer)\b"
)
# "research" drops a title unless it is clearly an engineering role ("Software Engineer Intern, Research Platform")
RESEARCH_OK = r"\b(software engineer\w*|software developer|developer|swe|sde)\b"
US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
             "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
CA_PROVINCES = "ON BC QC AB MB SK NS NB NL PE YT NT NU".split()
NA_CODES = r",\s*(" + "|".join(US_STATES + CA_PROVINCES) + r")\b"     # case-sensitive, after a comma
NA_WORDS = (
    r"\b(canada|united states|usa|u\.s\.?|us|"
    r"ontario|british columbia|quebec|alberta|manitoba|saskatchewan|nova scotia|"
    r"toronto|vancouver|montr[eé]al|ottawa|waterloo|kitchener|calgary|edmonton|burnaby|"
    r"mississauga|markham|halifax|winnipeg|victoria|"
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|"
    r"hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|"
    r"michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
    r"new mexico|new york|nyc|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|"
    r"rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|"
    r"west virginia|wisconsin|wyoming|seattle|san francisco|bay area|boston|chicago|austin|"
    r"atlanta|denver|redmond|santa clara|mountain view|sunnyvale|palo alto|menlo park|san jose|"
    r"los angeles|san diego|dallas|houston|bellevue|pittsburgh|philadelphia)\b"
)
NON_NA = (
    r"\b(uk|united kingdom|england|london|ireland|dublin|india|bangalore|bengaluru|hyderabad|pune|"
    r"germany|berlin|munich|france|paris|netherlands|amsterdam|spain|madrid|poland|warsaw|"
    r"singapore|japan|tokyo|china|shanghai|beijing|hong kong|taiwan|australia|sydney|melbourne,? australia|"
    r"israel|tel aviv|brazil|mexico|philippines|korea|seoul|switzerland|zurich|sweden|stockholm|"
    r"romania|portugal|lisbon|italy|milan|czech|prague|vietnam|indonesia|malaysia|uae|dubai|"
    r"egypt|nigeria|kenya|south africa|argentina|chile|colombia|costa rica|emea|apac|europe)\b"
)

# --- US work eligibility -------------------------------------------------------------
# You need sponsorship for the US, so US roles (not Canadian ones) are dropped when:
#   - the repo marks them: Simplify 🛂 (no sponsorship) / 🇺🇸 (US citizenship required), or
#   - the job description asks for US citizenship, a security clearance, ITAR "U.S. person"
#     status, or says it won't sponsor / needs work authorization without sponsorship.
# A US role with no description to check is kept and flagged "visa: check".
VISA_BLOCK_PATTERNS = [
    r"u\.?\s?s\.? citizen(ship)?\s+(is\s+|are\s+)?(required|only|mandatory)",
    r"(must|required to|need to|needs to) be (a |an )?(u\.?\s?s\.?|united states) citizen",
    r"(require[sd]?|requiring) (u\.?\s?s\.?|united states) citizenship",
    r"citizenship (is |are )?(required|mandatory)",
    r"(must|required to) be (a |an )?u\.?\s?s\.? person",
    r"\bitar\b",
    r"(security|secret|top secret|government|dod|ts/sci|public trust) clearance",
    r"(obtain|maintain|hold|possess|eligible (for|to obtain)) (an? |the )?(active |current )?(\w+ ){0,2}clearance",
    r"\bts/sci\b",
    r"(will not|won't|cannot|can't|can not|unable to|not able to|do not|does not|don't|doesn't|are not able to|is not able to) (offer |provide |support )?(visa |immigration |employment )?sponsor",
    r"(not|no longer) (be )?(eligible|available) for (visa |immigration )?sponsorship",
    r"\bno (visa |immigration )?sponsorship",
    r"sponsorship (is |will )?not (be )?(available|offered|provided|possible)",
    r"without (the )?(need for |requiring )?(current or future |future |current )?(visa |employer |immigration |company )?sponsorship",
    r"authorized to work in the (u\.?\s?s\.?|united states) (on a permanent basis|without)",
    r"(cpt|opt|f-?1|h-?1b|j-?1)[^.]{0,40}(not|ineligible|cannot|unable)",
]
VISA_BLOCK = re.compile("|".join(f"(?:{p})" for p in VISA_BLOCK_PATTERNS), re.I)
CANADA_LOC = (
    r"\b(canada|ontario|british columbia|quebec|qu[eé]bec|alberta|manitoba|saskatchewan|nova scotia|"
    r"new brunswick|newfoundland|toronto|vancouver|montr[eé]al|ottawa|waterloo|kitchener|calgary|"
    r"edmonton|burnaby|richmond hill|mississauga|markham|halifax|winnipeg|victoria, bc|saint john|"
    r"oakville|gatineau|regina|saskatoon|surrey, bc|guelph|london, on|hamilton, on)\b"
)
CANADA_CODES = r",\s*(ON|BC|QC|AB|MB|SK|NS|NB|NL|PE|YT|NT|NU)\b"

KEY_MEMORY_DAYS = 30              # same company + role is treated as a duplicate for 30 days
NEW_FILE_KEEP_DAYS = 21           # data/new files older than this are deleted (sync has had them)
MAX_INDIVIDUAL_PUSHES = 25        # more new jobs than this in one run → the rest in one summary push
JD_MIN_CHARS = 200
EXCEL_CELL_LIMIT = 32000

# Alerts
LINKEDIN_ZERO_STREAK_ALERT = 3    # daytime runs in a row with 0 LinkedIn results
REPO_FAIL_STREAK_ALERT = 3
DAYTIME_HOURS = range(7, 23)
HEARTBEAT_HOUR = 21               # daily summary at/after 9pm Vancouver
GAP_ALERT_HOURS = 3

# =====================================================================================

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
NEW_DIR = DATA / "new"
SEEN_FILE = DATA / "seen.json"
HEALTH_FILE = DATA / "health.json"
BACKLOG_FILE = DATA / "backlog.csv"

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DRY_RUN = os.environ.get("DRY_RUN") == "1"          # local testing: no pushes

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": UA})
TIMEOUT = 25

NOW = datetime.now(timezone.utc)
LOCAL = NOW.astimezone(TZ)


# ----------------------------------------------------------------------------- helpers

def log(msg):
    print(f"[{datetime.now(TZ):%H:%M:%S}] {msg}", flush=True)


def norm(text):
    text = html.unescape(str(text or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def job_key(company, role):
    return f"{norm(company)}|{norm(role)}"


def job_id(link):
    return hashlib.sha1(link.encode()).hexdigest()[:10]


def html_to_text(s):
    s = str(s or "")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def strip_cell(cell):
    cell = re.sub(r"(?i)<br\s*/?>", "; ", cell)
    cell = re.sub(r"(?is)<summary>.*?</summary>", " ", cell)
    cell = re.sub(r"<[^>]+>", " ", cell)
    cell = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", cell)
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    cell = cell.replace("**", "").replace("__", "")
    return " ".join(html.unescape(cell).split()).strip(" ;")


def links_in(cell):
    urls = re.findall(r'href="(https?://[^"]+)"', cell)
    urls += re.findall(r"\]\((https?://[^)\s]+)\)", cell)
    urls += re.findall(r"https?://[^\s)\"'<>\]]+", cell)
    out = []
    for u in urls:
        u = html.unescape(u)
        if re.search(r"img\.shields\.io|imgur\.com|/images?/|\.(png|svg|gif|jpe?g)(\?|$)", u, re.I):
            continue
        if u not in out:
            out.append(u)
    return out


def clean_link(url):
    """Drop tracking parameters so the same job always has the same link."""
    if not url:
        return ""
    url = url.strip()
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    p = urlparse(url)
    if "zapply.jobs" in p.netloc:
        return url  # redirect link; resolved to the real posting later
    q = [(k, v) for k, vs in parse_qs(p.query).items() for v in vs
         if not re.match(r"(utm_|ref$|source$|src$|s$|gh_src$|lever-source)", k, re.I)]
    return urlunparse(p._replace(query=urlencode(q), fragment=""))


def is_relevant(role, location):
    r = role.lower()
    if not re.search(INTERN_WORDS, r) or not re.search(ROLE_WORDS, r) or re.search(EXCLUDE_WORDS, r):
        return False
    if re.search(r"\bresearch", r) and not re.search(RESEARCH_OK, r):
        return False
    # The chosen repos are US/Canada lists and LinkedIn is searched by region, so a location is
    # kept unless it clearly names somewhere outside North America with no US/Canada mention.
    # (Repo locations are often shorthand like "SF", "MN" or "AZ-TUCSON", so requiring a known
    # US/Canada word would wrongly drop real roles.)
    low = (location or "").lower().replace("_", " ")
    if re.search(NON_NA, low) and not (re.search(NA_WORDS, low) or re.search(NA_CODES, location or "")):
        return False  # "Remote in UK" drops; "London, UK; Remote in USA" keeps
    return True


def in_canada(location):
    loc = location or ""
    return bool(re.search(CANADA_LOC, loc.lower()) or re.search(CANADA_CODES, loc))


def visa_label(job):
    """'' for Canadian roles; for US roles a short note shown in the push and in Excel."""
    if in_canada(job["location"]):
        return ""
    if job.get("visa") == "sponsors":
        return "sponsors ✅"
    if len(job.get("jd") or "") >= JD_MIN_CHARS:
        return "no restriction found"
    return "check sponsorship"


def us_role_blocked(job):
    """True when a US role clearly isn't open to someone who needs sponsorship."""
    if in_canada(job["location"]):
        return False
    if job.get("visa") == "no":
        return True
    return bool(VISA_BLOCK.search(job.get("jd") or ""))


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))


# ----------------------------------------------------------------------------- push (ntfy)

def push(title, message, click=None, priority=3, tags=None):
    if DRY_RUN or not NTFY_TOPIC:
        log(f"  [push] {title} | {message.splitlines()[0] if message else ''}")
        return
    body = {"topic": NTFY_TOPIC, "title": title[:250], "message": message[:3500], "priority": priority}
    if tags:
        body["tags"] = tags
    if click:
        body["click"] = click
        body["actions"] = [{"action": "view", "label": "Open posting", "url": click}]
    for attempt in range(3):
        try:
            r = requests.post("https://ntfy.sh/", json=body, timeout=15)
            if r.status_code == 429:
                time.sleep(6)
                continue
            r.raise_for_status()
            return
        except Exception as e:
            log(f"  push failed ({e}); retrying")
            time.sleep(3)


def alert(health, key, title, message, every_hours):
    """Push an alert, but at most once per `every_hours` for the same problem."""
    last = health.setdefault("alerts", {}).get(key)
    if last and NOW - datetime.fromisoformat(last) < timedelta(hours=every_hours):
        log(f"  (alert '{key}' suppressed, sent recently)")
        return
    push(title, message, priority=4, tags=["warning"])
    health["alerts"][key] = NOW.isoformat()
    health.setdefault("today", {}).setdefault("problems", []).append(title)


# ----------------------------------------------------------------------------- LinkedIn

def linkedin_urls(lookback_sec):
    urls = []
    for kw in LINKEDIN_KEYWORDS:
        for loc, geo in LINKEDIN_LOCATIONS:
            urls.append(
                "https://www.linkedin.com/jobs/search/?"
                f"keywords={quote(kw)}&location={quote(loc)}&geoId={geo}"
                f"&f_TPR=r{int(lookback_sec)}&sortBy=DD"
            )
    return urls


def linkedin_limits(lookback_sec):
    """Per-search limit and per-run billed cap, scaled to the length of the look-back window."""
    per_search = min(150, max(LINKEDIN_LIMIT_PER_SEARCH,
                              math.ceil(LINKEDIN_LIMIT_PER_SEARCH * lookback_sec / 5400)))
    return per_search, per_search * len(LINKEDIN_KEYWORDS) * len(LINKEDIN_LOCATIONS)


def from_apify(lookback_sec):
    if not APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN secret is not set")
    api = "https://api.apify.com/v2"
    auth = {"Authorization": f"Bearer {APIFY_TOKEN}"}
    run_input = {
        "urls": linkedin_urls(lookback_sec),
        "scrapeCompany": False,
        "limitPerSource": linkedin_limits(lookback_sec)[0],
        "autoConvertToAiSearch": True,
    }
    r = requests.post(f"{api}/acts/{APIFY_ACTOR}/runs", headers=auth, json=run_input,
                      params={"maxItems": linkedin_limits(lookback_sec)[1]}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Apify start failed: HTTP {r.status_code} {r.text[:300]}")
    run = r.json()["data"]
    run_id, dataset = run["id"], run["defaultDatasetId"]
    deadline = time.time() + APIFY_RUN_TIMEOUT_SEC
    status = run.get("status")
    while status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
        if time.time() > deadline:
            raise RuntimeError(f"Apify run {run_id} still {status} after {APIFY_RUN_TIMEOUT_SEC}s")
        time.sleep(10)
        status = requests.get(f"{api}/actor-runs/{run_id}", headers=auth, timeout=30).json()["data"]["status"]
    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify run {run_id} ended {status}")
    items = requests.get(f"{api}/datasets/{dataset}/items", headers=auth,
                         params={"clean": "true", "format": "json"}, timeout=60).json()
    jobs = []
    for it in items:
        link = it.get("link") or it.get("jobUrl") or it.get("url") or ""
        jd = it.get("descriptionText") or html_to_text(it.get("descriptionHtml") or it.get("description") or "")
        jobs.append({
            "company": it.get("companyName") or it.get("company") or "",
            "role": it.get("title") or "",
            "location": it.get("location") or "",
            "link": link,
            "source": "LinkedIn",
            "jd": jd,
            "posted": it.get("postedAt") or "",
        })
    return jobs


def from_jobspy(lookback_sec):
    from jobspy import scrape_jobs
    jobs, errors = [], 0
    hours = max(2, math.ceil(lookback_sec / 3600))
    for kw in LINKEDIN_KEYWORDS:
        for loc, _ in LINKEDIN_LOCATIONS:
            try:
                df = scrape_jobs(site_name=["linkedin"], search_term=kw, location=loc,
                                 results_wanted=LINKEDIN_LIMIT_PER_SEARCH, hours_old=hours,
                                 linkedin_fetch_description=True, description_format="markdown", verbose=0)
            except Exception as e:
                errors += 1
                log(f"  JobSpy '{kw}' / {loc} failed: {e}")
                continue
            for _, row in df.iterrows():
                d = str(row.get("description") or "")
                jobs.append({
                    "company": str(row.get("company") or ""),
                    "role": str(row.get("title") or ""),
                    "location": str(row.get("location") or loc),
                    "link": str(row.get("job_url") or ""),
                    "source": "LinkedIn",
                    "jd": "" if d == "nan" else d,
                    "posted": str(row.get("date_posted") or ""),
                })
            time.sleep(2)
    # JobSpy logs LinkedIn blocks instead of raising, so an empty result across all six searches
    # is treated as a failure rather than "no new jobs".
    if errors == len(LINKEDIN_KEYWORDS) * len(LINKEDIN_LOCATIONS) or not jobs:
        raise RuntimeError("JobSpy got nothing from LinkedIn (likely blocked)")
    return jobs


def linkedin_lookback(health):
    last = health.get("last_linkedin_ok")
    if not last:
        return 2 * 3600
    gap = (NOW - datetime.fromisoformat(last)).total_seconds()
    sec = max(LINKEDIN_MIN_LOOKBACK_MIN * 60, gap + LINKEDIN_BUFFER_MIN * 60)
    return min(sec, 24 * 3600)


# ----------------------------------------------------------------------------- repos

def parse_markdown_tables(text, name):
    jobs, header, last_company = [], None, ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if line:
                header = None
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        lowered = [strip_cell(c).lower() for c in cells]
        if "company" in lowered:
            header = {}
            for i, h in enumerate(lowered):
                if h == "company":
                    header["company"] = i
                elif h in ("role", "position", "title", "job title"):
                    header["role"] = i
                elif h == "location":
                    header["location"] = i
                elif h in ("apply", "posting", "link", "application", "apply link"):
                    header["link"] = i
                elif h in ("visa", "sponsorship"):
                    header["visa"] = i
            continue
        if header is None or set("".join(cells)) <= set("-: "):
            continue
        if len(cells) <= max(header.values()):
            continue
        if "🔒" in line:
            continue  # closed
        company = strip_cell(cells[header.get("company", 0)])
        if company in ("", "↳"):
            company = last_company
        last_company = company
        role = strip_cell(cells[header["role"]]) if "role" in header else ""
        location = strip_cell(cells[header["location"]]) if "location" in header else ""
        links = links_in(cells[header["link"]]) if "link" in header else links_in(line)
        if not links:
            continue
        visa = ""
        if "visa" in header:
            v = strip_cell(cells[header["visa"]]).lower()
            visa = "sponsors" if "sponsor" in v and not re.search(r"\bno\b|❌", v) else ("no" if re.search(r"\bno\b|❌", v) else "")
        jobs.append({"company": company, "role": role, "location": location, "link": links[0],
                     "source": name, "jd": "", "posted": "", "visa": visa})
    return jobs


def parse_html_tables(text, name):
    jobs, last_company = [], ""
    for body in re.findall(r"(?is)<tbody>(.*?)</tbody>", text):
        for tr in re.findall(r"(?is)<tr>(.*?)</tr>", body):
            tds = re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)
            if len(tds) < 5 or "🔒" in tr:
                continue
            company = strip_cell(tds[0]).replace("🔥", "").strip()
            if company in ("", "↳"):
                company = last_company
            last_company = company
            links = [u for u in links_in(tds[4]) if "simplify.jobs/p/" not in u] or links_in(tds[4])
            if not links:
                continue
            role_raw = strip_cell(tds[1])
            visa = "no" if ("🛂" in role_raw or "🇺🇸" in role_raw) else ""
            role = re.sub(r"[🎓🛂🇺🇸]", "", role_raw).strip()
            jobs.append({"company": company, "role": role, "location": strip_cell(tds[2]),
                         "link": links[0], "source": name, "jd": "", "posted": "", "visa": visa})
    return jobs


def from_repo(name, kind, url):
    r = HTTP.get(url, timeout=60)
    r.raise_for_status()
    jobs = parse_html_tables(r.text, name) if kind == "html" else parse_markdown_tables(r.text, name)
    if not jobs:
        raise RuntimeError("parsed 0 listings (repo format may have changed)")
    return jobs


# ----------------------------------------------------------------------------- links + JDs

def resolve_link(url):
    """Zapply links redirect to the real posting; follow them so you get the direct ATS link."""
    if "zapply.jobs/" not in url:
        return url
    try:
        r = HTTP.get(url, allow_redirects=True, timeout=TIMEOUT)
        if "zapply.jobs" not in urlparse(r.url).netloc:
            return r.url
        m = re.search(r'http-equiv="refresh"[^>]*url=([^"\']+)', r.text, re.I) or \
            re.search(r'window\.location(?:\.href)?\s*=\s*["\'](https?://[^"\']+)', r.text)
        if m:
            return html.unescape(m.group(1))
    except Exception:
        pass
    return url


def jd_workday(url):
    p = urlparse(url)
    if "myworkdayjobs.com" not in p.netloc:
        return ""
    parts = [x for x in p.path.split("/") if x]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]
    if "job" not in parts:
        return ""
    i = parts.index("job")
    site, rest = parts[0], "/".join(parts[i + 1:])
    tenant = p.netloc.split(".")[0]
    d = HTTP.get(f"https://{p.netloc}/wday/cxs/{tenant}/{site}/job/{rest}",
                 headers={"Accept": "application/json"}, timeout=TIMEOUT).json()
    return html_to_text(d.get("jobPostingInfo", {}).get("jobDescription", ""))


def jd_jsonld(url):
    """Most career pages embed schema.org JobPosting data with the full description."""
    page = HTTP.get(url, timeout=TIMEOUT).text
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                t = node.get("@type")
                if (t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)) and node.get("description"):
                    return html_to_text(node["description"])
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            elif isinstance(node, list):
                stack.extend(node)
    return ""


def fetch_jd(url):
    """Best-effort JD text. Returns '' when the site doesn't expose it."""
    try:
        m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url) or \
            re.search(r"greenhouse\.io/.*?for=([\w-]+).*?token=(\d+)", url)
        if m:
            d = HTTP.get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}",
                         timeout=TIMEOUT).json()
            return html_to_text(html.unescape(d.get("content", "")))
        m = re.search(r"jobs\.lever\.co/([\w.-]+)/([\w-]{36})", url)
        if m:
            d = HTTP.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", timeout=TIMEOUT).json()
            parts = [d.get("descriptionPlain", "")]
            for lst in d.get("lists", []):
                parts.append(lst.get("text", "") + ":\n" + html_to_text(lst.get("content", "")))
            parts.append(d.get("additionalPlain", ""))
            return "\n\n".join(p for p in parts if p)
        m = re.search(r"jobs\.ashbyhq\.com/([\w.%-]+)/([\w-]{36})", url)
        if m:
            d = HTTP.get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}", timeout=TIMEOUT).json()
            for j in d.get("jobs", []):
                if j.get("id") == m.group(2):
                    return j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))
            return ""
        if "myworkdayjobs.com" in url:
            return jd_workday(url)
        m = re.search(r"jobs\.smartrecruiters\.com/([\w.-]+)/(\d+)", url)
        if m:
            d = HTTP.get(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}",
                         timeout=TIMEOUT).json()
            sec = d.get("jobAd", {}).get("sections", {})
            return "\n\n".join(html_to_text(sec[k].get("text", "")) for k in
                               ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
                               if k in sec)
        m = re.search(r"apply\.workable\.com/([\w-]+)/j/(\w+)", url)
        if m:
            d = HTTP.get(f"https://apply.workable.com/api/v2/accounts/{m.group(1)}/jobs/{m.group(2)}",
                         timeout=TIMEOUT).json()
            return "\n\n".join(html_to_text(d.get(k, "")) for k in ("description", "requirements", "benefits") if d.get(k))
        if "linkedin.com" in url:
            return ""
        return jd_jsonld(url)
    except Exception as e:
        log(f"  JD fetch failed for {url[:80]}: {e.__class__.__name__}")
        return ""


# ----------------------------------------------------------------------------- main

def new_day(health):
    today = LOCAL.strftime("%Y-%m-%d")
    if health.get("today", {}).get("date") != today:
        health["today"] = {"date": today, "runs": 0, "new_jobs": 0, "linkedin_results": 0,
                           "linkedin_runs": 0, "visa_dropped": 0, "problems": []}


def run():
    DATA.mkdir(exist_ok=True)
    NEW_DIR.mkdir(exist_ok=True)
    seen = load_json(SEEN_FILE, None)
    first_run = seen is None
    seen = seen or {"links": {}, "keys": {}}
    health = load_json(HEALTH_FILE, {})
    new_day(health)

    # gap check (GitHub sometimes delays or skips scheduled runs)
    last_run = health.get("last_run")
    if (last_run and LOCAL.hour not in QUIET_HOURS
            and NOW - datetime.fromisoformat(last_run) > timedelta(hours=GAP_ALERT_HOURS)):
        gap_from = datetime.fromisoformat(last_run).astimezone(TZ)
        alert(health, "gap", "⚠️ Job watcher had a gap",
              f"No runs between {gap_from:%a %H:%M} and {LOCAL:%a %H:%M}. LinkedIn is caught up automatically "
              f"(this run looked back over the gap). Repos are caught up too.", 1)
    health["last_run"] = NOW.isoformat()

    if LOCAL.hour in QUIET_HOURS and not first_run:
        log("Night pause (11pm-7am): nothing checked. The 7am run catches up.")
        save_json(HEALTH_FILE, health)
        return
    health["today"]["runs"] += 1

    all_jobs = []

    # --- LinkedIn
    if True:
        lookback = linkedin_lookback(health)
        log(f"LinkedIn: looking back {lookback / 60:.0f} min")
        li_jobs, used = None, None
        try:
            li_jobs, used = from_apify(lookback), "Apify"
        except Exception as e:
            log(f"  Apify failed: {e}")
            apify_error = str(e)[:300]
            try:
                li_jobs, used = from_jobspy(lookback), "JobSpy backup"
                alert(health, "apify_failed", "⚠️ Apify failed, used JobSpy backup",
                      f"LinkedIn still checked this run via JobSpy. Apify error: {apify_error}", 6)
            except Exception as e2:
                log(f"  JobSpy backup failed: {e2}")
                alert(health, "linkedin_down", "🚨 LinkedIn check FAILED",
                      f"Both Apify and the JobSpy backup failed. Check LinkedIn manually until this clears.\n"
                      f"Apify: {apify_error}\nJobSpy: {str(e2)[:200]}", 3)
        if li_jobs is not None:
            log(f"LinkedIn ({used}): {len(li_jobs)} results")
            all_jobs += li_jobs
            health["last_linkedin_ok"] = NOW.isoformat()
            health["today"]["linkedin_runs"] += 1
            health["today"]["linkedin_results"] += len(li_jobs)
            cap = linkedin_limits(lookback)[1]
            if used == "Apify" and len(li_jobs) >= cap:
                alert(health, "li_cap", "⚠️ LinkedIn hit the per-run cap",
                      f"{len(li_jobs)} results in one run (cap {cap}). Some jobs may be cut off "
                      f"and Apify cost will run high. Ask Claude to adjust the LinkedIn limits.", 12)
            if len(li_jobs) == 0 and LOCAL.hour in DAYTIME_HOURS:
                health["linkedin_zero_streak"] = health.get("linkedin_zero_streak", 0) + 1
                if health["linkedin_zero_streak"] >= LINKEDIN_ZERO_STREAK_ALERT:
                    alert(health, "li_zero", "⚠️ LinkedIn returning 0 jobs",
                          f"{health['linkedin_zero_streak']} daytime runs in a row found nothing on LinkedIn. "
                          f"The scraper may be broken. Check LinkedIn manually today.", 6)
            elif li_jobs:
                health["linkedin_zero_streak"] = 0

    # --- Repos
    streaks = health.setdefault("repo_fail_streak", {})
    for name, (kind, url) in REPOS.items():
        try:
            got = from_repo(name, kind, url)
            log(f"{name}: {len(got)} listings")
            all_jobs += got
            streaks[name] = 0
        except Exception as e:
            log(f"{name}: FAILED ({e.__class__.__name__}: {e})")
            streaks[name] = streaks.get(name, 0) + 1
            if streaks[name] >= REPO_FAIL_STREAK_ALERT:
                alert(health, f"repo_{name}", f"⚠️ {name} failing",
                      f"{streaks[name]} runs in a row. Error: {str(e)[:250]}", 12)

    # --- Filter + dedupe
    cutoff = (NOW - timedelta(days=KEY_MEMORY_DAYS)).isoformat()
    seen["keys"] = {k: t for k, t in seen["keys"].items() if t >= cutoff}
    relevant, new, batch = 0, [], set()
    for j in all_jobs:
        j["link"] = clean_link(j["link"])
        if not j["role"] or not j["link"] or not is_relevant(j["role"], j["location"]):
            continue
        if j.get("visa") == "no" and not in_canada(j["location"]):
            continue  # repo says no sponsorship / US citizens only
        relevant += 1
        k = job_key(j["company"], j["role"])
        if j["link"] in seen["links"] or k in seen["keys"] or k in batch or j["link"] in batch:
            continue
        batch.update((k, j["link"]))
        new.append(j)
    log(f"{relevant} relevant of {len(all_jobs)} total → {len(new)} new")

    for j in new:
        seen["links"][j["link"]] = NOW.isoformat()[:10]
        seen["keys"][job_key(j["company"], j["role"])] = NOW.isoformat()

    if first_run:
        with BACKLOG_FILE.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Company", "Role", "Location", "Source", "Link"])
            for j in new:
                w.writerow([j["company"], j["role"], j["location"], j["source"], j["link"]])
        push("✅ Job watcher is live",
             f"{len(new)} currently-open roles saved to data/backlog.csv in your repo. "
             f"From now on you get a push for every new posting.", tags=["tada"])
        log("First run: baseline saved, no per-job pushes.")
    elif new:
        for j in new:
            j["link"] = clean_link(resolve_link(j["link"]))
            if len(j["jd"]) < JD_MIN_CHARS:
                j["jd"] = fetch_jd(j["link"])
            j["jd"] = j["jd"][:EXCEL_CELL_LIMIT]
            j["id"] = job_id(j["link"])
            j["found_at"] = LOCAL.isoformat(timespec="minutes")
            seen["links"][j["link"]] = NOW.isoformat()[:10]
        blocked = [j for j in new if us_role_blocked(j)]
        if blocked:
            log(f"Dropped {len(blocked)} US role(s) that need citizenship / clearance / no sponsorship:")
            for j in blocked:
                log(f"   x {j['company']} — {j['role']}")
            health["today"]["visa_dropped"] = health["today"].get("visa_dropped", 0) + len(blocked)
        new = [j for j in new if not us_role_blocked(j)]
        for j in new:
            j["visa"] = visa_label(j)
    if not first_run and new:
        out = NEW_DIR / f"{NOW:%Y-%m-%dT%H-%M-%SZ}.json"
        out.write_text(json.dumps(new, indent=1, ensure_ascii=False))
        health["today"]["new_jobs"] += len(new)

        # LinkedIn first (freshest), then repos
        new.sort(key=lambda j: j["source"] != "LinkedIn")
        for j in new[:MAX_INDIVIDUAL_PUSHES]:
            jd_note = "JD ✓" if len(j["jd"]) >= JD_MIN_CHARS else "needs JD"
            visa_note = f" · visa: {j['visa']}" if j["visa"] else ""
            push(f"{j['company']}", f"{j['role']}\n{j['location'] or '—'} · {j['source']} · {jd_note}{visa_note}",
                 click=j["link"], priority=4 if j["source"] == "LinkedIn" else 3, tags=["briefcase"])
        if len(new) > MAX_INDIVIDUAL_PUSHES:
            rest = new[MAX_INDIVIDUAL_PUSHES:]
            push(f"+{len(rest)} more new jobs",
                 "\n".join(f"• {j['company']} — {j['role']}" for j in rest[:40]), tags=["briefcase"])

    # prune old new-job files
    for f in NEW_DIR.glob("*.json"):
        try:
            stamp = datetime.strptime(f.stem, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)
            if NOW - stamp > timedelta(days=NEW_FILE_KEEP_DAYS):
                f.unlink()
        except ValueError:
            pass

    # daily heartbeat
    t = health["today"]
    if LOCAL.hour >= HEARTBEAT_HOUR and health.get("heartbeat_sent") != t["date"]:
        problems = sorted(set(t["problems"]))
        push("📋 Job watcher daily check",
             f"{t['runs']} runs today · {t['new_jobs']} new jobs"
             f" ({t.get('visa_dropped', 0)} US roles skipped for citizenship/no sponsorship)\n"
             f"LinkedIn: {t['linkedin_runs']} checks, {t['linkedin_results']} results billed\n"
             + ("Problems today: " + "; ".join(problems) if problems else "All sources OK"),
             tags=["white_check_mark"] if not problems else ["warning"])
        health["heartbeat_sent"] = t["date"]

    save_json(SEEN_FILE, seen)
    save_json(HEALTH_FILE, health)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        traceback.print_exc()
        push("🚨 Job watcher crashed", traceback.format_exc()[-1500:], priority=5, tags=["rotating_light"])
        sys.exit(1)
