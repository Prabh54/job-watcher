"""
targets.py — Prabhraj's core target companies (core_companies.csv, Oct 2026).

Two jobs:
  1. is_target(company)  tags a job from ANY source (LinkedIn, repos, career pages) whose company
                         is on the list, so the phone push can show a ⭐.
  2. fetch_target(t)     polls that company's own careers feed directly (Greenhouse, Lever, Ashby,
                         Workday, SuccessFactors, Amazon, Microsoft, ...). All free public JSON or
                         HTML endpoints: no Apify, no API keys, no cost.

A company with feeds=[] is still tagged when it shows up on LinkedIn or a repo; it just isn't
polled directly (its careers site has no usable public feed).
"""

import html
import json
import re
from urllib.parse import quote, urljoin

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126 Safari/537.36")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
TIMEOUT = 20
SEARCH_TERMS = ["intern", "co-op"]   # for feeds that need a search instead of listing everything

# -------------------------------------------------------------------------------- company list
# aliases: normalized names that mean this company. A company name counts when, after dropping
#          suffixes like "inc" / "canada" / "corporation", it equals an alias, or (for aliases
#          in `prefix`) starts with one. Ambiguous names (Sentry, Cohere, Harvey, RBC, TD, EA,
#          BCI, Clio) are exact-only, so Sentry Insurance, Cohere Health, RBC Bearings and
#          TD SYNNEX are not tagged.
# feeds:   filled from the Oct 26 probe run (probe_targets.py). Only verified feeds are listed.

TARGETS = [
    # ---- Big tech
    dict(name="Amazon", band="Big tech", aliases=["amazon"], prefix=["amazon"], feeds=[["amazon"]]),
    dict(name="Databricks", band="Big tech", aliases=["databricks"], prefix=["databricks"], feeds=[["greenhouse", "databricks"]]),
    dict(name="Atlassian", band="Big tech", aliases=["atlassian"], prefix=["atlassian"], feeds=[["atlassian"]]),
    dict(name="Microsoft", band="Big tech", aliases=["microsoft", "the coalition"], prefix=["microsoft"], feeds=[["microsoft"]]),
    dict(name="RBC", band="Big tech", aliases=["rbc", "royal bank of canada", "rbc royal bank"],
         prefix=["royal bank of canada", "rbc capital markets", "rbc wealth management", "rbc royal bank"], feeds=[["workday", "rbc.wd3.myworkdayjobs.com", "rbc", "RBCGLOBAL1"],
                ["workday", "rbc.wd3.myworkdayjobs.com", "rbc", "ExternalPrivatePostingStudents"]]),
    dict(name="SAP", band="Big tech", aliases=["sap"], prefix=["sap"], feeds=[]),
    dict(name="TELUS", band="Big tech", aliases=["telus"], prefix=["telus"], feeds=[["rmk", "careers.telus.com"]]),
    dict(name="Google", band="Big tech", aliases=["google", "alphabet"], prefix=["google"], feeds=[["google"]]),
    dict(name="Motorola Solutions", band="Big tech", aliases=["motorola solutions", "avigilon"],
         prefix=["motorola solutions", "avigilon"], feeds=[["workday", "motorolasolutions.wd5.myworkdayjobs.com", "motorolasolutions", "Careers"]]),
    dict(name="Electronic Arts", band="Big tech", aliases=["electronic arts", "ea", "ea sports"],
         prefix=["electronic arts"], feeds=[["avature", "jobs.ea.com"]]),
    dict(name="DoorDash", band="Big tech", aliases=["doordash"], prefix=["doordash"], feeds=[["greenhouse", "doordashusa"], ["greenhouse", "doordashcanada"]]),
    dict(name="Demonware (Activision)", band="Big tech", aliases=["demonware", "activision", "activision blizzard"],
         prefix=["demonware", "activision"], feeds=[]),
    dict(name="Fortinet", band="Big tech", aliases=["fortinet"], prefix=["fortinet"], feeds=[]),
    dict(name="Intuit", band="Big tech", aliases=["intuit"], prefix=["intuit"], feeds=[["radancy", "jobs.intuit.com"]]),
    dict(name="Capital One", band="Big tech", aliases=["capital one"], prefix=["capital one"], feeds=[["workday", "capitalone.wd12.myworkdayjobs.com", "capitalone", "Capital_One"]]),
    dict(name="Manulife", band="Big tech", aliases=["manulife"], prefix=["manulife"], feeds=[["workday", "manulife.wd3.myworkdayjobs.com", "manulife", "MFCJH_Jobs"]]),
    dict(name="Autodesk", band="Big tech", aliases=["autodesk"], prefix=["autodesk"], feeds=[["workday", "autodesk.wd1.myworkdayjobs.com", "autodesk", "uni"], ["workday", "autodesk.wd1.myworkdayjobs.com", "autodesk", "Ext"]]),
    dict(name="NetApp", band="Big tech", aliases=["netapp"], prefix=["netapp"], feeds=[["rmk", "jobs.netapp.com"]]),
    dict(name="TD Bank", band="Big tech", aliases=["td", "td bank", "td securities", "toronto dominion bank"],
         prefix=["td bank", "td securities", "toronto dominion"], feeds=[["workday", "td.wd3.myworkdayjobs.com", "td", "TD_Bank_Careers"]]),
    dict(name="BMO", band="Big tech", aliases=["bmo", "bank of montreal", "bmo financial group"],
         prefix=["bmo", "bank of montreal"], feeds=[["workday", "bmo.wd3.myworkdayjobs.com", "bmo", "External"]]),
    dict(name="Expedia Group", band="Big tech", aliases=["expedia", "expedia group"], prefix=["expedia"], feeds=[["workday", "expedia.wd108.myworkdayjobs.com", "expedia", "search"]]),
    dict(name="Scotiabank", band="Big tech", aliases=["scotiabank", "bank of nova scotia"],
         prefix=["scotiabank", "bank of nova scotia"], feeds=[["rmk", "jobs.scotiabank.com"]]),
    # ---- Mid-size
    dict(name="Global Relay", band="Mid-size", aliases=["global relay", "global relay communications"],
         prefix=["global relay"], feeds=[["greenhouse", "globalrelay"]]),
    dict(name="Clio", band="Mid-size", aliases=["clio", "themis solutions"], prefix=[], feeds=[]),
    dict(name="Shopify", band="Mid-size", aliases=["shopify"], prefix=["shopify"], feeds=[]),
    dict(name="Dialpad", band="Mid-size", aliases=["dialpad"], prefix=["dialpad"], feeds=[["greenhouse", "dialpad"]]),
    dict(name="Cohere", band="Mid-size", aliases=["cohere", "cohere ai"], prefix=[], feeds=[["ashby", "cohere"]]),
    dict(name="1Password", band="Mid-size", aliases=["1password", "agilebits"], prefix=["1password"], feeds=[["ashby", "1password"]]),
    dict(name="Visier", band="Mid-size", aliases=["visier"], prefix=["visier"], feeds=[["ashby", "visier"]]),
    dict(name="GeoComply", band="Mid-size", aliases=["geocomply"], prefix=["geocomply"], feeds=[["lever", "geocomply-2"]]),
    dict(name="Hootsuite", band="Mid-size", aliases=["hootsuite"], prefix=["hootsuite"], feeds=[["greenhouse", "hootsuite"]]),
    dict(name="Kinaxis", band="Mid-size", aliases=["kinaxis"], prefix=["kinaxis"], feeds=[["icims", "careers-kinaxis.icims.com"]]),
    dict(name="Harvey", band="Mid-size", aliases=["harvey", "harvey ai", "counsel ai"], prefix=[], feeds=[["ashby", "harvey"]]),
    dict(name="Lyft", band="Mid-size", aliases=["lyft"], prefix=["lyft"], feeds=[["greenhouse", "lyft"]]),
    dict(name="Wealthsimple", band="Mid-size", aliases=["wealthsimple"], prefix=["wealthsimple"], feeds=[["ashby", "wealthsimple"]]),
    dict(name="Snowflake", band="Mid-size", aliases=["snowflake"], prefix=["snowflake"], feeds=[["ashby", "snowflake"]]),
    dict(name="Stripe", band="Mid-size", aliases=["stripe"], prefix=["stripe"], feeds=[["greenhouse", "stripe"]]),
    dict(name="MongoDB", band="Mid-size", aliases=["mongodb"], prefix=["mongodb"], feeds=[["greenhouse", "mongodb"]]),
    dict(name="Sentry", band="Mid-size", aliases=["sentry", "sentry io", "functional software"], prefix=[], feeds=[["ashby", "sentry"]]),
    dict(name="BCI", band="Mid-size", aliases=["bci", "british columbia investment management",
                                               "bc investment management", "bci investment management"],
         prefix=["british columbia investment management"], feeds=[]),
    dict(name="Nutanix", band="Mid-size", aliases=["nutanix"], prefix=["nutanix"], feeds=[["jobvite", "nutanix"]]),
    dict(name="Waabi", band="Mid-size", aliases=["waabi", "waabi innovation"], prefix=["waabi"], feeds=[["lever", "waabi"]]),
    dict(name="Presto Phoenix", band="Mid-size", aliases=["presto phoenix", "presto automation"],
         prefix=["presto phoenix"], feeds=[]),
    dict(name="F5", band="Mid-size", aliases=["f5", "f5 networks"], prefix=["f5 networks"], feeds=[["workday", "ffive.wd5.myworkdayjobs.com", "ffive", "f5jobs"]]),
    # ---- Startup
    dict(name="FluidAI Medical", band="Startup", aliases=["fluidai", "fluidai medical", "fluid ai medical",
                                                         "fluid ai"], prefix=["fluidai"], feeds=[["rippling", "fluidai-medical-careers"]]),
]

SUFFIXES = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
            "canada", "usa", "us", "technologies", "technology", "group", "plc", "ulc", "lp", "the"}


def _norm(text):
    text = html.unescape(str(text or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _core(company):
    words = _norm(company).split()
    while words and words[-1] in SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


_INDEX = []
for _t in TARGETS:
    for a in _t["aliases"]:
        _INDEX.append((_norm(a), False, _t))
    for a in _t["prefix"]:
        _INDEX.append((_norm(a), True, _t))


def is_target(company):
    """The target dict for this company name, or None."""
    names = {n for n in (_norm(company), _core(company)) if n}   # "Royal Bank of Canada" needs the full form
    for alias, prefix, t in _INDEX:
        for n in names:
            if n == alias or (prefix and n.startswith(alias + " ")):
                return t
    return None


# -------------------------------------------------------------------------------- feed readers
# Each returns a list of {"company", "role", "location", "link", "jd"} for EVERY posting the
# feed shows (the watcher's normal intern/SWE/location filter runs afterwards).

def _get(url, **kw):
    r = HTTP.get(url, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def _text(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", str(s or ""))
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def f_greenhouse(slug):
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").json()
    # absolute_url is often the company's own site (databricks.com, stripe.com/jobs?gh_jid=),
    # which the JD fetcher can't read; jd_src points it at Greenhouse's own copy instead.
    return [dict(role=j.get("title", ""), location=(j.get("location") or {}).get("name", ""),
                 link=j.get("absolute_url", ""), jd="",
                 jd_src=f"https://job-boards.greenhouse.io/{slug}/jobs/{j.get('id')}") for j in d.get("jobs", [])]


def f_lever(slug):
    d = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json").json()
    out = []
    for j in d:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        out.append(dict(role=j.get("text", ""), location="; ".join(x for x in locs if x),
                        link=j.get("hostedUrl", ""), jd=j.get("descriptionPlain", "") or ""))
    return out


def f_ashby(slug):
    d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json()
    out = []
    for j in d.get("jobs", []):
        locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
        if j.get("isRemote") and "remote" not in " ".join(locs).lower():
            locs.append("Remote")
        out.append(dict(role=j.get("title", ""), location="; ".join(x for x in locs if x),
                        link=j.get("jobUrl", ""), jd=j.get("descriptionPlain", "") or ""))
    return out


def f_workday(host, tenant, site):
    """Workday's own JSON search API (what the careers page itself calls)."""
    out, seen = [], set()
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    for term in SEARCH_TERMS:
        for offset in (0, 20, 40):
            r = HTTP.post(api, json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term},
                          headers={"Accept": "application/json", "Content-Type": "application/json"},
                          timeout=TIMEOUT)
            r.raise_for_status()
            posts = r.json().get("jobPostings", [])
            for p in posts:
                path = p.get("externalPath", "")
                if not path or path in seen:
                    continue
                seen.add(path)
                out.append(dict(role=p.get("title", ""), location=p.get("locationsText", ""),
                                link=f"https://{host}/en-US/{site}{path}", jd=""))
            if len(posts) < 20:
                break
    return out


def f_rmk(host):
    """SAP SuccessFactors career sites (jobs.sap.com, jobs.scotiabank.com, ...) publish an RSS feed."""
    out, seen = [], set()
    for term in SEARCH_TERMS:
        xml = _get(f"https://{host}/services/rss/job/?locale=en_US&keywords={quote(term)}").text
        for item in re.findall(r"(?is)<item>(.*?)</item>", xml):
            title = _text((re.search(r"(?is)<title>(.*?)</title>", item) or [None, ""])[1]
                          .replace("<![CDATA[", "").replace("]]>", ""))
            link = _text((re.search(r"(?is)<link>(.*?)</link>", item) or [None, ""])[1])
            if not link or link in seen:
                continue
            seen.add(link)
            # titles look like "Software Developer Co-op (Vancouver, BC, CA, V6B 0A1)"
            m = re.match(r"(.*?)\s*\(([^()]*)\)\s*$", title)
            role, loc = (m.group(1), m.group(2)) if m else (title, "")
            desc = (re.search(r"(?is)<description>(.*?)</description>", item) or [None, ""])[1]
            out.append(dict(role=role, location=loc, link=link,
                            jd=_text(desc.replace("<![CDATA[", "").replace("]]>", ""))))
    return out


def f_amazon():
    out, seen = [], set()
    for country in ("CAN", "USA"):
        url = ("https://www.amazon.jobs/en/search.json?base_query=intern&result_limit=100&sort=recent"
               f"&normalized_country_code%5B%5D={country}")
        for j in _get(url, headers={"Accept": "application/json"}).json().get("jobs", []):
            path = j.get("job_path", "")
            if not path or path in seen:
                continue
            seen.add(path)
            out.append(dict(role=j.get("title", ""),
                            location=j.get("normalized_location") or j.get("location", ""),
                            link="https://www.amazon.jobs" + path,
                            jd=_text(j.get("description", "") + "\n" + j.get("basic_qualifications", ""))))
    return out


def f_microsoft():
    """Microsoft careers (Eightfold PCSX search API)."""
    out, seen = [], set()
    for term in ("intern", "internship"):
        for start in (0, 10, 20, 30):
            d = _get("https://apply.careers.microsoft.com/api/pcsx/search",
                     params={"domain": "microsoft.com", "query": term, "start": start,
                             "sort_by": "timestamp"},
                     headers={"Accept": "application/json"}).json()
            pos = (d.get("data") or {}).get("positions") or d.get("positions") or []
            for p in pos:
                pid = str(p.get("id") or p.get("displayJobId") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                locs = p.get("locations") or p.get("standardizedLocations") or []
                link = p.get("positionUrl") or f"/careers/job/{pid}"
                out.append(dict(role=p.get("name", ""), location="; ".join(map(str, locs)),
                                link=urljoin("https://apply.careers.microsoft.com", link), jd=""))
            if len(pos) < 10:
                break
    return out


def f_atlassian():
    d = _get("https://www.atlassian.com/endpoint/careers/listings",
             headers={"Accept": "application/json"}).json()
    out = []
    for j in d if isinstance(d, list) else d.get("listings", []):
        locs = j.get("locations") or []
        portal = (j.get("portalJobPost") or {}).get("portalUrl") or ""
        link = portal or f"https://www.atlassian.com/company/careers/details/{j.get('id', '')}"
        out.append(dict(role=j.get("title", ""), location="; ".join(map(str, locs)), link=link,
                        jd=_text(j.get("overview", "") + "\n" + j.get("responsibilities", "")
                                 + "\n" + j.get("qualifications", ""))))
    return out


def f_jobvite(company):
    out, seen = [], set()
    for term in SEARCH_TERMS:
        page = _get(f"https://jobs.jobvite.com/{company}/search?q={quote(term)}").text
        for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page):
            a = re.search(r'(?is)<a[^>]+href="([^"]*/job/[^"]+)"[^>]*>(.*?)</a>', row)
            if not a:
                continue
            link = urljoin("https://jobs.jobvite.com", html.unescape(a.group(1)))
            if link in seen:
                continue
            seen.add(link)
            loc = re.search(r'(?is)class="[^"]*jv-job-list-location[^"]*"[^>]*>(.*?)</td>', row)
            out.append(dict(role=_text(a.group(2)), location=_text(loc.group(1)) if loc else "",
                            link=link, jd=""))
    return out


def f_icims(host):
    out, seen = [], set()
    for term in SEARCH_TERMS:
        page = _get(f"https://{host}/jobs/search?ss=1&searchKeyword={quote(term)}&in_iframe=1").text
        for block in re.split(r'(?i)<div[^>]+class="[^"]*\brow\b', page):
            a = re.search(r'(?is)<a[^>]+href="(https?://[^"]+/jobs/\d+/[^"]+/job[^"]*)"[^>]*>(.*?)</a>', block)
            if not a:
                continue
            link = html.unescape(a.group(1)).split("?")[0]
            if link in seen:
                continue
            seen.add(link)
            title = re.sub(r"(?is)^.*?<h\d[^>]*>(.*?)</h\d>.*$", r"\1", a.group(2))
            loc = re.search(r'(?is)(?:Location|header left)[^<]*</[^>]+>\s*<[^>]+>\s*([^<]{3,80})<', block)
            out.append(dict(role=_text(title), location=_text(loc.group(1)) if loc else "", link=link, jd=""))
    return out


def f_rippling(slug):
    page = _get(f"https://ats.rippling.com/{slug}/jobs").text
    m = re.search(r'(?s)<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page)
    out = []
    if not m:
        return out
    stack = [json.loads(m.group(1))]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("name") and (node.get("url") or node.get("uuid")) and ("workLocation" in node
                                                                                 or "locations" in node):
                locs = node.get("locations") or [node.get("workLocation")]
                loc = "; ".join((x.get("name") if isinstance(x, dict) else str(x)) for x in locs if x)
                link = node.get("url") or f"https://ats.rippling.com/{slug}/jobs/{node['uuid']}"
                out.append(dict(role=node["name"], location=loc, link=link, jd=""))
            else:
                stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def f_radancy(host):
    """Radancy (TMP) career sites, e.g. jobs.intuit.com: a JSON endpoint that returns result HTML."""
    out, seen = [], set()
    for term in SEARCH_TERMS:
        d = _get(f"https://{host}/search-jobs/results",
                 params={"ActiveFacetID": 0, "CurrentPage": 1, "RecordsPerPage": 100, "Keywords": term,
                         "SearchResultsModuleName": "Search Results", "SearchFiltersModuleName": "Search Filters",
                         "SortCriteria": 0, "SortDirection": 0, "SearchType": 5, "ResultsType": 0},
                 headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}).json()
        for li in re.findall(r"(?is)<li[^>]*>(.*?)</li>", d.get("results", "")):
            a = re.search(r'(?is)<a[^>]+href="(/job/[^"]+)"', li)
            if not a or a.group(1) in seen:
                continue
            seen.add(a.group(1))
            t = re.search(r"(?is)<h2[^>]*>(.*?)</h2>", li)
            loc = re.search(r'(?is)class="[^"]*job-location[^"]*"[^>]*>(.*?)</span>', li)
            out.append(dict(role=_text(t.group(1)) if t else "", location=_text(loc.group(1)) if loc else "",
                            link=f"https://{host}{a.group(1)}", jd=""))
    return out


def f_avature(host):
    """Avature career sites (jobs.ea.com): server-rendered search results."""
    out, seen = [], set()
    for term in SEARCH_TERMS:
        page = _get(f"https://{host}/en_US/careers/SearchJobs/{quote(term)}?jobRecordsPerPage=50").text
        for m in re.finditer(r'(?is)<a[^>]+href="(https?://[^"]+/careers/JobDetail/[^"]+)"[^>]*>(.*?)</a>', page):
            link = html.unescape(m.group(1)).split("?")[0]
            title = _text(m.group(2))
            if link in seen or not title:
                continue
            seen.add(link)
            tail = page[m.end():m.end() + 1500]
            loc = re.search(r'(?is)class="[^"]*list-item-location[^"]*"[^>]*>(.*?)</', tail)
            out.append(dict(role=title, location=_text(loc.group(1)) if loc else "", link=link, jd=""))
    return out


def f_google():
    """Google careers results pages; titles come from the job-link slugs."""
    out, seen = [], set()
    for loc in ("Canada", "United States"):
        page = _get("https://www.google.com/about/careers/applications/jobs/results",
                    params={"q": "intern", "location": loc, "target_level": "INTERN_AND_APPRENTICE"}).text
        for m in re.finditer(r'href="(jobs/results/(\d+)-([a-z0-9-]+))', page):
            if m.group(2) in seen:
                continue
            seen.add(m.group(2))
            out.append(dict(role=m.group(3).replace("-", " ").title(), location=loc,
                            link="https://www.google.com/about/careers/applications/" + m.group(1), jd=""))
    return out


READERS = {
    "greenhouse": f_greenhouse, "lever": f_lever, "ashby": f_ashby, "workday": f_workday,
    "rmk": f_rmk, "amazon": f_amazon, "microsoft": f_microsoft, "atlassian": f_atlassian,
    "jobvite": f_jobvite, "icims": f_icims, "rippling": f_rippling, "radancy": f_radancy,
    "avature": f_avature, "google": f_google,
}


def read_feed(feed):
    """feed = ["greenhouse", "stripe"] or ["workday", host, tenant, site] etc."""
    kind, *args = feed
    return READERS[kind](*args)


def fetch_target(t):
    """Every posting on this company's own careers feed(s), tagged with the company's name."""
    jobs = []
    for feed in t["feeds"]:
        for j in read_feed(feed):
            if j.get("role") and j.get("link"):
                j["company"] = t["name"]
                jobs.append(j)
    return jobs
