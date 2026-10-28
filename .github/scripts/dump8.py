import json, os, urllib.request
os.makedirs("dump8", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"}
B = "https://www.calgary.ca/content/dam/www/cfod/finance/documents/"
P = B + "plans-budgets-and-financial-reports/"
log = {}
def get(name, url, save=True):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180)
        body = r.read()
        log[name] = {"url": url, "status": r.status, "bytes": len(body), "type": r.headers.get("content-type"),
                     "final": r.geturl(), "etag": r.headers.get("etag"), "modified": r.headers.get("last-modified")}
        if save:
            open(f"dump8/{name}", "wb").write(body)
    except Exception as e:
        log[name] = {"url": url, "error": str(e)[:300]}
    print(name, log[name], flush=True)

get("budget-2026.pdf", P + "2023-2026-service-plans-budgets/2026-budget-as-approved-dec-3-2025.pdf")
get("afr-2025.pdf", B + "2025-Annual-Financial-Report.pdf")
get("afr-2019.pdf", P + "annual-reports/annual-report-2019.pdf")
get("afr-2018.pdf", P + "annual-reports/annual-report-2018.pdf")
for y in range(2010, 2018):
    get(f"afr-{y}-a.pdf", P + f"annual-reports/annual-report-{y}.pdf")
    if "error" in log[f"afr-{y}-a.pdf"]:
        get(f"afr-{y}-b.pdf", f"https://www.calgary.ca/cfod/finance/Documents/Plans-Budgets-and-Financial-Reports/Annual-Reports/Annual-Report-{y}.pdf")
for name, url in [("annual-reports.html", "https://www.calgary.ca/our-finances/annual-reports.html"),
                  ("budget-2027.html", "https://www.calgary.ca/our-finances/2027-budget.html"),
                  ("budget-2026.html", "https://www.calgary.ca/our-finances/2026-budget.html"),
                  ("spb.html", "https://www.calgary.ca/our-finances/2023-2026-service-plans-budgets.html"),
                  ("workforce.html", "https://www.calgary.ca/our-finances/workforce-management.html")]:
    get(name, url)
json.dump(log, open("dump8/log.json", "w"), indent=1)
