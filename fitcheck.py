"""One-off check: re-score a sample of recent jobs with the current CANDIDATE_PROFILE secret
and print old score vs new score side by side. Runs from the fitcheck workflow; not part of
the hourly watcher. Delete this file and the workflow once the check is done."""
import glob
import json
import random
import re

import watcher as w

rows = []
for f in glob.glob("data/new/*.json"):
    for j in json.load(open(f)):
        if isinstance(j.get("fit"), int) and len(j.get("jd") or "") >= w.FIT_MIN_JD_CHARS:
            rows.append(j)

random.seed(7)
ai = [j for j in rows if re.search(r"\b(ai|ml|machine learning|llm|genai|gen ai|data scien|agent\w*)\b", j["role"].lower())]
web = [j for j in rows if j not in ai and re.search(r"full|back|front|web|software", j["role"].lower()) and j["fit"] <= 6]
high = [j for j in rows if j not in ai and j["fit"] >= 8]
groups = [("AI/ML", ai, 12), ("SWE<=6", web, 12), ("HIGH", high, 6)]

for name, pool, n in groups:
    print(f"\n===== {name} ({min(n, len(pool))} of {len(pool)})")
    for j in random.sample(pool, min(n, len(pool))):
        try:
            score, why = w.score_one_fit(j)
        except Exception as e:
            score, why = None, f"error {e}"
        delta = "" if score is None else f"{score - j['fit']:+d}"
        print(f"old {j['fit']:>2} -> new {score!s:>4} ({delta:>3}) | {j['company'][:20]} - {j['role'][:60]}")
        print(f"      old: {j.get('fit_why', '')[:95]}")
        print(f"      new: {why[:95]}")
