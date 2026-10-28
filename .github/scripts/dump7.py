import json, os, subprocess, urllib.request
os.makedirs("dump7", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"}
B = "https://www.calgary.ca/content/dam/www/cfod/finance/documents/"
P = B + "plans-budgets-and-financial-reports/"
DOCS = {
    "afr-2025": B + "2025-Annual-Financial-Report.pdf",
    "afr-2024": B + "Finance-2024-Annual-Report.pdf",
    "afr-2023": B + "Finance-2023-Annual-Report.pdf",
    "afr-2022": P + "annual-reports/annual-report-2022.pdf",
    "afr-2021": P + "annual-reports/annual-report-2021.pdf",
    "afr-2020": P + "annual-reports/annual-report-2020.pdf",
    "afr-2019": P + "annual-reports/annual-report-2019.pdf",
    "afr-2018": P + "annual-reports/annual-report-2018.pdf",
    "spb-2023-2026": P + "2023-2026-service-plans-budgets/2023-2026-service-plans-budgets.pdf",
    "spb-2023-2026-supp": P + "2023-2026-service-plans-budgets/2023-2026-service-plans-budgets-supplemental-information.pdf",
    "spb-2023-2026-highlights": P + "2023-2026-service-plans-budgets/service-plans-budgets-highlights.pdf",
    "adj-2024-summary": P + "2023-2026-service-plans-budgets/november-adjustments-summary-report.pdf",
    "adj-2024-investments": P + "2023-2026-service-plans-budgets/new-investment-recommendations.pdf",
    "adj-2024-continuity": P + "2023-2026-service-plans-budgets/operating-budget-continuity-schedule.pdf",
    "mca-2025-overview": P + "2025/MCA-to-2023-2026-service-plans-and-budgets.pdf",
    "mca-2025-summary": P + "2025/summary-of-revisions-and-council-direction.pdf",
    "mca-2025-investments": P + "2025/recommended-investments.pdf",
    "mca-2025-continuity": P + "2025/operating-budget-continuity-schedule.pdf",
    "budget-2026-approved": P + "2023-2026-service-plans-budgets/2026-budget-as-approved-dec-3-2025.pdf",
    "spb-2019-2022": P + "plans-and-budget-2019-2022/service-plans-and-budgets-2019-2022.pdf",
    "spb-2019-2022-supp": P + "plans-and-budget-2019-2022/service-plans-and-budgets-2019-2022-supplemental.pdf",
    "adj-2022": P + "plans-and-budget-2019-2022/2022-adjustments-capital-and-operating-schedules.pdf",
    "ap-2018-by-dept": B + "action-plan/action-plan-2015-2018-adjustments-by-department-2018-approved.pdf",
    "ap-2015-2018": B + "action-plan/approved/action-plan-2015-2018-complete-approved.pdf",
}
log = {}
for name, url in DOCS.items():
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180)
        body = r.read()
        log[name] = {"url": url, "status": r.status, "bytes": len(body), "type": r.headers.get("content-type")}
        open("/tmp/doc.pdf", "wb").write(body)
        subprocess.run(["pdftotext", "-layout", "/tmp/doc.pdf", f"dump7/{name}.txt"], check=True, timeout=600)
        pages = open(f"dump7/{name}.txt", errors="replace").read().split("\f")
        log[name]["pages"] = len(pages)
    except Exception as e:
        log[name] = {"url": url, "error": str(e)[:300]}
    print(name, log[name], flush=True)
json.dump(log, open("dump7/log.json", "w"), indent=1)
