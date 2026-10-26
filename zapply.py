"""
zapply.py — turn a Zapply redirect link into the real job posting link.

Zapply's /l/d/... links stopped redirecting for scripts in Oct 2026: every one bounces to the
generic zapply.jobs/jobs/ page, so the watcher could never fetch the posting or its JD (97 rows
in job_queue.xlsx sat at "Needs JD"). The slug itself names the original posting, though:

  ashby-{org}-{uuid}          → jobs.ashbyhq.com/{org}/{uuid}
  lever-{org}-{uuid}          → jobs.lever.co/{org}/{uuid}
  greenhouse-{org}-{id}       → job-boards.greenhouse.io/{org}/jobs/{id}
  sr-{company}-{id}           → jobs.smartrecruiters.com/{company}/{id}
  microsoft-{id}              → jobs.careers.microsoft.com/global/en/job/{id}
  bytedance-{id}              → jobs.bytedance.com/en/position/{id}/detail
  phenom-cisco-{id}           → jobs.cisco.com/jobs/ProjectDetail/{id}
  workday-{tenant}-{site}-{req} → looked up with Workday's search API (the wdN host isn't in the
                                  slug); the tenant's host is cached so it's found once.

Anything else (oracle-*, qualcomm-*) is returned unchanged.
"""

import re

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126 Safari/537.36")
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": UA})
TIMEOUT = 15
WD_HOSTS = [5, 1, 3, 12, 10, 103, 108, 501, 503, 104, 105, 2, 4, 6, 8, 9, 11, 100, 101, 102, 106, 107]
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Req IDs use uppercase prefixes (JR-, R_, REQ-, DT-) and site slugs are lowercase, so the prefix
# is uppercase-only: otherwise "...-search-2621721" would read "arch-2621721" as the req.
WD_REQ = r"((?:[A-Z]{1,4}[-_])?[A-Z]{0,4}\d+(?:-\d+)*)$"


def slug_of(url):
    m = re.search(r"zapply\.jobs/l/d/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def _workday(slug, cache):
    m = re.match(r"workday-([a-z0-9]+)-(.+)$", slug, re.I)
    if not m:
        return ""
    tenant, rest = m.group(1).lower(), m.group(2)
    r = re.search(WD_REQ, rest)
    if not r or r.start() == 0:
        return ""
    req, site_slug = r.group(1), rest[:r.start()].rstrip("-")
    sites = [site_slug.replace("-", "_"), site_slug]
    key = f"{tenant}/{site_slug}"
    known = cache.get(key)
    hosts = [known] if known else [f"{tenant}.wd{n}.myworkdayjobs.com" for n in WD_HOSTS]
    if known == "none":
        return ""
    want = re.sub(r"[-_]", "", req).lower()
    for host in hosts:
        for site in sites:
            try:
                resp = HTTP.post(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                                 json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": req},
                                 headers={"Accept": "application/json", "Content-Type": "application/json"},
                                 timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if resp.status_code != 200:
                continue
            cache[key] = host
            for p in resp.json().get("jobPostings", []):
                blob = (p.get("externalPath", "") + " " + " ".join(p.get("bulletFields") or [])).lower()
                if want in re.sub(r"[-_]", "", blob):
                    return f"https://{host}/{site}{p['externalPath']}"
            return ""      # right site, but the req is gone (closed posting)
    cache[key] = "none"
    return ""


def direct_link(url, cache=None):
    """Real posting link for a Zapply link, or the original URL when it can't be worked out.
    `cache` is a dict the caller keeps between runs (Workday tenant → host)."""
    cache = {} if cache is None else cache
    slug = slug_of(url)
    if not slug:
        return url
    m = re.match(rf"ashby-(.+)-({UUID})$", slug)
    if m:
        return f"https://jobs.ashbyhq.com/{m.group(1)}/{m.group(2)}"
    m = re.match(rf"lever-(.+)-({UUID})$", slug)
    if m:
        return f"https://jobs.lever.co/{m.group(1)}/{m.group(2)}"
    m = re.match(r"greenhouse-([\w.-]+?)-(\d{6,})$", slug)
    if m:
        return f"https://job-boards.greenhouse.io/{m.group(1)}/jobs/{m.group(2)}"
    m = re.match(r"sr-([\w.-]+?)-(\d{6,})$", slug)
    if m:
        return f"https://jobs.smartrecruiters.com/{m.group(1)}/{m.group(2)}"
    m = re.match(r"microsoft-(\d+)$", slug)
    if m:
        return f"https://jobs.careers.microsoft.com/global/en/job/{m.group(1)}"
    m = re.match(r"bytedance-(\d+)$", slug)
    if m:
        return f"https://jobs.bytedance.com/en/position/{m.group(1)}/detail"
    m = re.match(r"phenom-cisco-(\d+)$", slug)
    if m:
        return f"https://jobs.cisco.com/jobs/ProjectDetail/{m.group(1)}"
    if slug.startswith("workday-"):
        return _workday(slug, cache) or url
    return url
