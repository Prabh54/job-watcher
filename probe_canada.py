"""Probe for the Nov 18 2026 Canada changes, run by hand from the Actions tab (probe-canada).

Runs the watcher's real code with an empty health dict (no pushes: NTFY_TOPIC isn't passed in):
  - from_targets(): every careers feed, incl. the throttled Workday reader and CANADA_EMPLOYERS
  - from_indeed(): Indeed Canada over the last 3 hours
Saves probe_canada.json to the `probe-canada` branch. Never touches data/ on main.
"""
import json
import time
import traceback

import watcher as w

OUT = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def step(name, fn):
    t0 = time.time()
    try:
        OUT[name] = fn()
    except Exception:
        OUT[name] = {"error": traceback.format_exc()[-1500:]}
    OUT[name + "_sec"] = round(time.time() - t0)
    print(f"{name}: done in {time.time() - t0:.0f}s")
    json.dump(OUT, open("probe_canada.json", "w"), indent=1, ensure_ascii=False)


def targets():
    health = {}
    jobs, ok = w.from_targets(health)
    by = {}
    for j in jobs:
        b = by.setdefault(j["company"], {"postings": 0, "canada": 0, "canada_relevant": []})
        b["postings"] += 1
        if w.in_canada(j["location"]):
            b["canada"] += 1
            if w.is_relevant(j["role"], j["location"]):
                b["canada_relevant"].append(f"{j['role']} | {j['location']}")
    failed = {k: v for k, v in health.get("target_fail_streak", {}).items() if v}
    return {"ok": len(ok), "polled": len(w.T.polled()), "failed": failed,
            "workday_blocked": w.T.workday_blocked(), "health": health, "by_company": by}


def cooldown():
    """Second pass with the health from the first: Workday must be skipped without any request."""
    w.T._wd_state.update(blocked=None, last=0.0)
    health = {"workday_blocked_at": w.NOW.isoformat()}
    t0 = time.time()
    jobs, ok = w.from_targets(health)
    return {"ok": len(ok), "sec": round(time.time() - t0), "blocked": w.T.workday_blocked()}


def indeed():
    jobs = w.from_indeed(3 * 3600)
    return {"count": len(jobs),
            "relevant": [f"{j['company']} | {j['role']} | {j['location']} | {j['link'][:90]}"
                         for j in jobs if w.is_relevant(j["role"], j["location"])]}


step("targets", targets)
step("cooldown", cooldown)
step("indeed", indeed)
print("probe finished")
