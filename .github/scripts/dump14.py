import csv, json, re, sys, time
sys.path.insert(0, "collectors"); sys.path.insert(0, "scripts")
import jobs, backfill_jobs_from_archive as bf
rows = list(csv.DictReader(open("data/jobs/postings.csv")))
oc = [r for r in rows if re.search(r"on.?\s?call", r["position_type"] + r["full_part_time"], re.I)]
s = jobs.session() if hasattr(jobs, "session") else __import__("requests").Session()
out = []
open_ids = [r for r in oc if r["source"] == ""][:4]
for r in open_ids:
    try:
        f = jobs.fetch_detail(s, r["url"])
    except Exception as e:
        f = {"error": str(e)}
    out.append({"id": r["job_id"], "kind": "live", "parsed": f})
    time.sleep(1)
caps = {}
for ts, url in bf.cdx(s, "recruiting.calgary.ca", "2024-01-01", matchType="domain"):
    m = re.search(r"JobOpeningId=(\d+)", url, re.I)
    if m: caps.setdefault(m.group(1), []).append((ts, url))
for r in [r for r in oc if r["source"] == "archive"][:8]:
    for ts, url in sorted(caps.get(r["job_id"], []))[:3]:
        html = bf.fetch(s, ts, url)
        if not html: continue
        f = jobs.parse_detail(html)
        if f.get("position_type"):
            text = __import__("bs4").BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            i = text.lower().find("regular/temporary")
            out.append({"id": r["job_id"], "kind": "archive", "parsed": f, "context": text[max(0, i-120): i+120] if i >= 0 else "NOT FOUND"})
            break
        time.sleep(1)
import os; os.makedirs("dump14", exist_ok=True)
json.dump(out, open("dump14/out.json", "w"), indent=1)
