"""Probe: what does the City's eScribe portal publish for recent meetings?"""
import json, re, time
from pathlib import Path
import requests

out = Path("dump11"); out.mkdir(exist_ok=True)
BASE = "https://pub-calgary.escribemeetings.com"
s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"
log = {}
try:
    r = s.get(BASE + "/", timeout=60); log["home"] = [r.status_code, len(r.text)]
    (out / "home.html").write_text(r.text)
except Exception as e:
    log["home"] = repr(e)
meetings = []
try:
    r = s.post(BASE + "/MeetingsCalendarView.aspx/GetCalendarMeetings",
               json={"calendarStartDate": "2026-09-01", "calendarEndDate": "2026-11-30"}, timeout=60)
    log["calendar"] = [r.status_code, len(r.text)]
    (out / "calendar.json").write_text(r.text)
    meetings = r.json().get("d", [])
except Exception as e:
    log["calendar"] = repr(e)
log["meetings"] = [(m.get("ID") or m.get("Id"), m.get("MeetingName"), m.get("StartDate"), [d.get("Type") for d in m.get("MeetingDocumentLink", [])]) for m in meetings]
n = 0
for m in meetings:
    name = m.get("MeetingName", "")
    if "Council" not in name:
        continue
    mid = m.get("ID") or m.get("Id")
    for kind in ("PostMinutes", "Minutes", "Agenda"):
        url = f"{BASE}/Meeting.aspx?Id={mid}&Agenda={kind}&lang=English"
        try:
            r = s.get(url, timeout=60)
            fn = f"{re.sub(r'[^0-9A-Za-z]+', '_', m.get('StartDate', ''))[:16]}_{re.sub(r'[^A-Za-z]+', '_', name)[:30]}_{kind}.html"
            (out / fn).write_text(r.text)
            log.setdefault("pages", []).append([fn, r.status_code, len(r.text), r.url[-80:]])
        except Exception as e:
            log.setdefault("pages", []).append([mid, kind, repr(e)])
        time.sleep(1)
    n += 1
    if n >= 8:
        break
(out / "log.json").write_text(json.dumps(log, indent=1))
