import json, os, requests
os.makedirs("dump15", exist_ok=True)
s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"
out = {}
for name, url in {"fcss": "https://www.calgary.ca/social-services/funding/organization-allocations.html",
                  "civic": "https://www.calgary.ca/our-finances/civic-partners-funding.html",
                  "fcss_parent": "https://www.calgary.ca/social-services/funding.html"}.items():
    try:
        r = s.get(url, timeout=60)
        out[name] = {"status": r.status_code, "final": r.url, "history": [h.status_code for h in r.history], "len": len(r.text)}
        open(f"dump15/{name}.html", "w").write(r.text)
    except Exception as e:
        out[name] = {"error": repr(e)}
json.dump(out, open("dump15/summary.json", "w"), indent=1)
