import json, os, re, requests
os.makedirs("dump16", exist_ok=True)
P = "https://pub-calgary.escribemeetings.com"
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"
r = s.post(f"{P}/MeetingsCalendarView.aspx/GetCalendarMeetings", json={"calendarStartDate": "2026-10-20", "calendarEndDate": "2026-11-16"}, timeout=60)
ms = r.json().get("d", [])
json.dump(ms, open("dump16/meetings.json", "w"), indent=1)
out = []
for m in ms:
    name = m.get("MeetingName", "")
    row = {"id": m["ID"], "name": name, "date": m.get("StartDate"), "docs": [d.get("Type") for d in m.get("MeetingDocumentLink") or []]}
    if re.search(r"Council|Executive|Infrastructure|Community Development", name):
        for kind in ["PostMinutes", "PostAgenda", "Agenda", "Merged"]:
            try:
                h = s.get(f"{P}/Meeting.aspx?Id={m['ID']}&Agenda={kind}&lang=English", timeout=60).text
                row[kind] = {"len": len(h), "motions": h.count("AgendaItemMotion"), "voters": h.count("MotionVoters"), "results": h.count("MotionResult")}
                if row[kind]["voters"] and not os.path.exists(f"dump16/{kind}.html"):
                    open(f"dump16/{kind}.html", "w").write(h)
            except Exception as e:
                row[kind] = repr(e)
    out.append(row)
json.dump(out, open("dump16/summary.json", "w"), indent=1)
