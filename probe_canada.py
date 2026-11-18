"""One-off probe: why so few Canadian jobs, and which new Canadian sources are worth adding.

Run by hand from the Actions tab (workflow "probe-canada"). Sends no notifications, never
touches data/ on main. Writes probe_canada.json, which the workflow saves to the
`probe-canada` branch.

  A. LinkedIn (Apify), Canada only, last 24h, AI-search conversion ON vs OFF, so we can see
     the raw titles LinkedIn returns and how many pass the watcher's filter. ~300 results billed.
  B. Indeed Canada (JobSpy, free).
  C. Glassdoor Canada (JobSpy, free).
  D. Workday careers feeds that have been failing (TD, BMO, Manulife, RBC): raw HTTP status.
"""
import json
import os
import time
import traceback

import requests

import watcher as w

OUT = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
APIFY = "https://api.apify.com/v2"
TOKEN = os.environ.get("APIFY_TOKEN", "")

LI_KEYWORDS = ["software intern", "software co-op", "developer co-op",
               "developer intern", "data co-op", "machine learning intern"]
INDEED_TERMS = ["software co-op", "software intern", "developer co-op", "developer intern",
                "software engineering student", "data co-op", "machine learning intern",
                "full stack intern", "backend co-op"]


def tag(role, location):
    return {"relevant": w.is_relevant(role or "", location or ""), "canada": w.in_canada(location or "")}


def apify_run(ai_search):
    urls = [("https://www.linkedin.com/jobs/search/?"
             f"keywords={requests.utils.quote(k)}&location=Canada&geoId=101174742&f_TPR=r86400&sortBy=DD")
            for k in LI_KEYWORDS]
    body = {"urls": urls, "scrapeCompany": False, "limitPerSource": 25, "autoConvertToAiSearch": ai_search}
    auth = {"Authorization": f"Bearer {TOKEN}"}
    r = requests.post(f"{APIFY}/acts/{w.APIFY_ACTOR}/runs", headers=auth, json=body,
                      params={"maxItems": 150}, timeout=60)
    r.raise_for_status()
    run = r.json()["data"]
    deadline = time.time() + 600
    while run["status"] not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT") and time.time() < deadline:
        time.sleep(10)
        run = requests.get(f"{APIFY}/actor-runs/{run['id']}", headers=auth, timeout=30).json()["data"]
    items = requests.get(f"{APIFY}/datasets/{run['defaultDatasetId']}/items", headers=auth,
                         params={"clean": "true", "format": "json"}, timeout=60).json()
    rows = []
    for it in items:
        role, loc = it.get("title") or "", it.get("location") or ""
        rows.append({"role": role, "company": it.get("companyName") or "", "location": loc,
                     "posted": it.get("postedAt") or "", "input": it.get("inputUrl") or "",
                     "link": it.get("link") or "", **tag(role, loc)})
    return {"status": run["status"], "count": len(rows),
            "relevant": sum(x["relevant"] for x in rows), "rows": rows,
            "sample_keys": sorted(items[0].keys()) if items else []}


def jobspy_site(site, terms, hours=72, n=50):
    from jobspy import scrape_jobs
    res = {}
    for t in terms:
        try:
            df = scrape_jobs(site_name=[site], search_term=t, location="Canada", country_indeed="Canada",
                             results_wanted=n, hours_old=hours, description_format="markdown", verbose=0)
            rows = []
            for _, x in df.iterrows():
                role, loc = str(x.get("title") or ""), str(x.get("location") or "")
                rows.append({"role": role, "company": str(x.get("company") or ""), "location": loc,
                             "posted": str(x.get("date_posted") or ""), "link": str(x.get("job_url") or ""),
                             "direct": str(x.get("job_url_direct") or ""),
                             "jd_len": len(str(x.get("description") or "")), **tag(role, loc)})
            res[t] = {"count": len(rows), "relevant": sum(r["relevant"] for r in rows), "rows": rows}
        except Exception as e:
            res[t] = {"error": f"{e.__class__.__name__}: {str(e)[:300]}"}
        time.sleep(3)
    return res


def workday_check():
    out = {}
    feeds = {"TD": ("td.wd3.myworkdayjobs.com", "td", "TD_Bank_Careers"),
             "BMO": ("bmo.wd3.myworkdayjobs.com", "bmo", "External"),
             "Manulife": ("manulife.wd3.myworkdayjobs.com", "manulife", "MFCJH_Jobs"),
             "RBC": ("rbc.wd3.myworkdayjobs.com", "rbc", "RBCGLOBAL1")}
    for name, (host, tenant, site) in feeds.items():
        api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}
        for label, sess in (("watcher session", w.T.HTTP), ("plain browser UA", None)):
            try:
                hdr = {"Accept": "application/json", "Content-Type": "application/json"}
                if sess is None:
                    hdr["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                         "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
                    r = requests.post(api, json=body, headers=hdr, timeout=30)
                else:
                    r = sess.post(api, json=body, headers=hdr, timeout=30)
                out[f"{name} / {label}"] = {"status": r.status_code, "total": (r.json().get("total") if r.ok else None),
                                            "body": r.text[:300]}
            except Exception as e:
                out[f"{name} / {label}"] = {"error": f"{e.__class__.__name__}: {str(e)[:300]}"}
        try:
            out[f"{name} / watcher reader"] = {"jobs": len(w.T.f_workday(host, tenant, site))}
        except Exception as e:
            out[f"{name} / watcher reader"] = {"error": f"{e.__class__.__name__}: {str(e)[:300]}"}
    return out


def step(name, fn):
    t0 = time.time()
    try:
        OUT[name] = fn()
    except Exception:
        OUT[name] = {"error": traceback.format_exc()[-1500:]}
    print(f"{name}: done in {time.time() - t0:.0f}s")
    json.dump(OUT, open("probe_canada.json", "w"), indent=1)


step("workday", workday_check)
step("indeed", lambda: jobspy_site("indeed", INDEED_TERMS))
step("glassdoor", lambda: jobspy_site("glassdoor", ["software intern", "software co-op"], n=30))
if TOKEN:
    step("linkedin_ai_on", lambda: apify_run(True))
    step("linkedin_ai_off", lambda: apify_run(False))
print("probe finished")
