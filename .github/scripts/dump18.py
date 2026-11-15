import json, os, re, requests
os.makedirs("dump18", exist_ok=True)
P = "https://pub-calgary.escribemeetings.com"
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"
ms = s.post(f"{P}/MeetingsCalendarView.aspx/GetCalendarMeetings", json={"calendarStartDate": "2025-10-20", "calendarEndDate": "2026-11-16"}, timeout=60).json().get("d", [])
out = []
for m in ms:
    for d in m.get("MeetingDocumentLink") or []:
        t = d.get("Title") or ""
        if re.search(r"summary of proceedings|proceedings|votes|decision", t, re.I):
            out.append({"date": m["StartDate"], "meeting": m["MeetingName"], "title": t, "url": d.get("Url"),
                        "has_minutes": any(x.get("Type") == "PostMinutes" for x in m["MeetingDocumentLink"])})
json.dump(out, open("dump18/list.json", "w"), indent=1)
for i, o in enumerate([o for o in out if not o["has_minutes"]][:12]):
    r = s.get(P + o["url"].lstrip("."), timeout=120)
    open(f"dump18/{i}.pdf", "wb").write(r.content)
    o["file"] = f"{i}.pdf"
json.dump(out, open("dump18/list.json", "w"), indent=1)
