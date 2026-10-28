"""Probe: can we still read closed postings, and what has the archive kept?"""
import csv, json, re, sys, time
from collections import Counter
from pathlib import Path
import requests
sys.path.insert(0, "collectors")
import jobs

out = Path("dump9"); out.mkdir(exist_ok=True)
rows = list(csv.DictReader(open("data/jobs/postings.csv")))
unk = [r for r in rows if not r["permanent_positions"] and not r["temporary_positions"] and r["url"]]
sample = []
for year in ("2024", "2025", "2026"):
    ys = [r for r in unk if r["first_seen"].startswith(year)]
    sample += ys[:: max(1, len(ys) // 6)][:6]

# 1. Live posting pages for closed postings.
s = jobs.session()
live = []
for r in sample:
    try:
        resp = s.get(r["url"], timeout=60)
        html = resp.text
        fields = jobs.parse_detail(html)
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        live.append({"job_id": r["job_id"], "first_seen": r["first_seen"], "status": resp.status_code, "len": len(html),
                     "title": title.group(1).strip()[:120] if title else "", "fields": {k: v for k, v in fields.items() if v},
                     "text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:600]})
    except Exception as e:
        live.append({"job_id": r["job_id"], "error": repr(e)})
    time.sleep(1)
(out / "live.json").write_text(json.dumps(live, indent=1))

# 2. Everything the archive has under recruiting.calgary.ca.
CDX = "http://web.archive.org/cdx/search/cdx"
caps = []
for attempt in range(4):
    try:
        r = requests.get(CDX, params={"url": "recruiting.calgary.ca", "matchType": "domain", "output": "json",
                                      "fl": "timestamp,original,statuscode", "collapse": "urlkey", "limit": "100000"}, timeout=300)
        if r.status_code == 200 and r.text.strip():
            caps = r.json()[1:]
            break
    except Exception as e:
        print(e)
    time.sleep(10)
paths = Counter(re.sub(r"\?.*", "", c[1]) for c in caps)
ids = Counter(c[0][:4] for c in caps if re.search(r"JobOpeningId=\d+", c[1], re.I))
ok_ids = Counter(c[0][:4] for c in caps if re.search(r"JobOpeningId=\d+", c[1], re.I) and c[2] == "200")
our_ids = {r["job_id"] for r in unk}
archived_ids = {m.group(1) for c in caps for m in [re.search(r"JobOpeningId=(\d+)", c[1], re.I)] if m}
(out / "cdx.json").write_text(json.dumps({
    "captures": len(caps), "paths": paths.most_common(40), "jobopening_by_year": ids, "jobopening_200_by_year": ok_ids,
    "archived_ids": len(archived_ids), "archived_ids_we_lack_type": len(archived_ids & our_ids),
    "sample": caps[:40],
}, indent=1))
# 3. Other hosts the City has used for postings.
other = {}
for host in ("careers.calgary.ca", "jobs.calgary.ca", "calgary.ca/careers/*"):
    try:
        r = requests.get(CDX, params={"url": host, "matchType": "prefix" if "*" in host else "domain", "output": "json", "fl": "timestamp,original", "collapse": "urlkey", "limit": "2000"}, timeout=300)
        rows_ = r.json()[1:] if r.status_code == 200 and r.text.strip() else []
        other[host] = {"n": len(rows_), "sample": rows_[:15]}
    except Exception as e:
        other[host] = repr(e)
    time.sleep(3)
(out / "other.json").write_text(json.dumps(other, indent=1))
