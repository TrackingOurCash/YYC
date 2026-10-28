"""Probe: what do archived copies of postings we lack details for contain?"""
import csv, json, re, sys, time
from collections import Counter
from pathlib import Path
import requests
from bs4 import BeautifulSoup
sys.path.insert(0, "collectors")
import jobs

out = Path("dump10"); out.mkdir(exist_ok=True)
rows = {r["job_id"]: r for r in csv.DictReader(open("data/jobs/postings.csv"))}
need = {j for j, r in rows.items() if not r.get("details_fetched")}
CDX = "http://web.archive.org/cdx/search/cdx"
s = requests.Session(); s.headers["User-Agent"] = jobs.USER_AGENT
caps = []
for attempt in range(4):
    r = s.get(CDX, params={"url": "recruiting.calgary.ca", "matchType": "domain", "from": "2024", "output": "json",
                           "fl": "timestamp,original,statuscode,mimetype,length"}, timeout=300)
    if r.status_code == 200 and r.text.strip():
        caps = r.json()[1:]; break
    time.sleep(10)
by_id = {}
for ts, url, st, mime, ln in caps:
    m = re.search(r"JobOpeningId=(\d+)", url, re.I)
    if m:
        by_id.setdefault(m.group(1), []).append((ts, url, st, mime, ln))
over = sorted(set(by_id) & need)
summary = {"captures": len(caps), "ids": len(by_id), "ids_needing": len(over),
           "status": Counter(c[2] for v in by_id.values() for c in v),
           "status_needing": Counter(c[2] for j in over for c in by_id[j]),
           "lengths_200": Counter((int(c[4]) // 5000) * 5000 for j in over for c in by_id[j] if c[2] == "200" and c[4].isdigit()).most_common(15)}
samples = []
for j in over[:: max(1, len(over) // 30)][:30]:
    entry = {"job_id": j, "first_seen": rows[j]["first_seen"], "title": rows[j]["title"], "caps": []}
    for ts, url, st, mime, ln in by_id[j][:4]:
        c = {"ts": ts, "status": st, "len": ln, "url": url[-120:]}
        if st == "200":
            try:
                html = s.get(f"http://web.archive.org/web/{ts}id_/{url}", timeout=60).text
                text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                c["fields"] = {k: v for k, v in jobs.parse_detail(html).items() if v}
                c["has_position_type"] = "Position Type" in text
                c["has_job_id"] = j in text
                i = text.find("Position Type")
                c["text"] = (text[max(0, i - 400): i + 400] if i >= 0 else text[:500]).replace("\n", " | ")
            except Exception as e:
                c["error"] = repr(e)
            time.sleep(1)
        entry["caps"].append(c)
    samples.append(entry)
(out / "summary.json").write_text(json.dumps(summary, indent=1))
(out / "samples.json").write_text(json.dumps(samples, indent=1))
