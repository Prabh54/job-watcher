"""
probe_targets.py — one-off check of which careers feeds work for each target company.

Run by .github/workflows/probe.yml (manual only). Tries every candidate feed below, writes
probe_result.json, and the workflow pushes it to the `probe` branch. No pushes to the phone,
nothing written to data/, so the hourly watcher and the Mac sync never see it.
"""

import json
import re
import traceback
from concurrent.futures import ThreadPoolExecutor

import targets

WD = lambda tenant, n, site: ["workday", f"{tenant}.wd{n}.myworkdayjobs.com", tenant, site]

CANDIDATES = {
    "Amazon": [["amazon"]],
    "Databricks": [["greenhouse", "databricks"]],
    "Atlassian": [["atlassian"], ["lever", "atlassian"], WD("atlassian", 3, "Atlassian")],
    "Microsoft": [["microsoft"]],
    "RBC": [WD("rbc", 3, "RBCGLOBAL1"), WD("rbc", 3, "RBC_Careers"), ["rmk", "jobs.rbc.com"]],
    "SAP": [["rmk", "jobs.sap.com"]],
    "TELUS": [["rmk", "careers.telus.com"], WD("telus", 3, "TELUS_Careers"), WD("telus", 3, "External")],
    "Google": [["google"]],
    "Motorola Solutions": [WD("motorolasolutions", 5, "Careers")],
    "Electronic Arts": [["avature", "jobs.ea.com"], WD("ea", 1, "EA_External")],
    "DoorDash": [["greenhouse", "doordashusa"], ["greenhouse", "doordash"], ["greenhouse", "doordashcanada"]],
    "Demonware (Activision)": [WD("activision", 1, "External"), WD("activision", 1, "Activision_Careers"),
                               ["greenhouse", "demonware"]],
    "Fortinet": [WD("fortinet", 1, "FortinetCareers"), WD("fortinet", 5, "Fortinet"),
                 WD("fortinet", 1, "External")],
    "Intuit": [["radancy", "jobs.intuit.com"], WD("intuit", 1, "IntuitCareers")],
    "Capital One": [WD("capitalone", 12, "Capital_One"), WD("capitalone", 1, "Capital_One")],
    "Manulife": [WD("manulife", 3, "MFCJH_Jobs"), WD("manulife", 3, "External")],
    "Autodesk": [WD("autodesk", 1, "uni"), WD("autodesk", 1, "Ext")],
    "NetApp": [["rmk", "jobs.netapp.com"], WD("netapp", 1, "NetAppCareers")],
    "TD Bank": [WD("td", 3, "TD_Bank_Careers")],
    "BMO": [WD("bmo", 3, "External"), WD("bmo", 3, "BMO")],
    "Expedia Group": [WD("expedia", 108, "search")],
    "Scotiabank": [["rmk", "jobs.scotiabank.com"], WD("scotiabank", 3, "ScotiabankCareers")],
    "Global Relay": [["greenhouse", "globalrelay"], ["greenhouse", "globalrelaycommunications"]],
    "Clio": [["greenhouse", "clio"], ["lever", "clio"], ["ashby", "clio"], WD("clio", 3, "Clio"),
             WD("themis", 3, "Clio")],
    "Shopify": [["ashby", "shopify"], ["greenhouse", "shopify"], ["lever", "shopify"]],
    "Dialpad": [["greenhouse", "dialpad"]],
    "Cohere": [["ashby", "cohere"], ["lever", "cohere"], ["greenhouse", "cohere"]],
    "1Password": [["ashby", "1password"]],
    "Visier": [["lever", "visier"], ["greenhouse", "visier"], ["greenhouse", "visiercorporation"],
               ["ashby", "visier"]],
    "GeoComply": [["lever", "geocomply-2"], ["lever", "geocomply"]],
    "Hootsuite": [["greenhouse", "hootsuite"], ["lever", "hootsuite"], ["ashby", "hootsuite"],
                  WD("hootsuite", 3, "Hootsuite")],
    "Kinaxis": [["icims", "careers-kinaxis.icims.com"]],
    "Harvey": [["ashby", "harvey"], ["greenhouse", "harvey"], ["lever", "harvey"]],
    "Lyft": [["greenhouse", "lyft"]],
    "Wealthsimple": [["ashby", "wealthsimple"], ["greenhouse", "wealthsimple"], ["lever", "wealthsimple"]],
    "Snowflake": [["ashby", "snowflake"], ["greenhouse", "snowflake"], ["lever", "snowflake"]],
    "Stripe": [["greenhouse", "stripe"]],
    "MongoDB": [["greenhouse", "mongodb"]],
    "Sentry": [["ashby", "sentry"], ["greenhouse", "sentry"]],
    "BCI": [WD("bci", 10, "BCI"), WD("bcimc", 3, "BCI"), WD("bci", 3, "External"), ["greenhouse", "bci"]],
    "Nutanix": [["jobvite", "nutanix"]],
    "Waabi": [["lever", "waabi"], ["greenhouse", "waabi"], ["ashby", "waabi"]],
    "Presto Phoenix": [["ashby", "presto"], ["lever", "presto"], ["greenhouse", "presto"],
                       ["ashby", "prestophoenix"], ["lever", "prestophoenix"]],
    "F5": [WD("ffive", 5, "f5jobs")],
    "FluidAI Medical": [["rippling", "fluidai-medical-careers"]],
}

INTERN = re.compile(r"\b(intern|internship|co-?op|coop|student)\b", re.I)


def probe(company, feed):
    rec = {"company": company, "feed": feed}
    try:
        jobs = targets.read_feed(feed)
        interns = [j for j in jobs if INTERN.search(j.get("role", ""))]
        rec.update(ok=True, total=len(jobs), interns=len(interns),
                   sample=[f"{j['role']} | {j['location']} | {j['link']}" for j in (interns or jobs)[:4]])
    except Exception as e:
        rec.update(ok=False, error=f"{e.__class__.__name__}: {str(e)[:300]}",
                   trace=traceback.format_exc()[-400:])
    return rec


def main():
    missing = [t["name"] for t in targets.TARGETS if t["name"] not in CANDIDATES]
    work = [(c, f) for c, feeds in CANDIDATES.items() for f in feeds]
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda cf: probe(*cf), work))
    out = {"missing_from_candidates": missing, "results": results}
    with open("probe_result.json", "w") as f:
        json.dump(out, f, indent=1)
    for r in results:
        status = f"OK total={r['total']} interns={r['interns']}" if r["ok"] else f"FAIL {r['error'][:90]}"
        print(f"{r['company']:<26} {str(r['feed'])[:70]:<72} {status}")


if __name__ == "__main__":
    main()
