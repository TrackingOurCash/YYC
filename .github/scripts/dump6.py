import json, os, urllib.request, urllib.parse
os.makedirs("dump6", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; +https://github.com/TrackingOurCash/YYC)"}
log = {}
def get(name, url, limit=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90)
        body = r.read()
        log[name] = {"url": url, "status": r.status, "bytes": len(body), "type": r.headers.get("content-type"), "final": r.geturl()}
        if limit is None or len(body) < limit:
            open(f"dump6/{name}", "wb").write(body)
    except Exception as e:
        log[name] = {"url": url, "error": str(e)[:300]}
S = "https://data.calgary.ca/resource/"
get("wards.geojson", S + "tz8z-hyaz.geojson")
get("wards2021.json", S + "bxgr-t8xb.json?" + urllib.parse.urlencode({"$select": "ward_num,label,councillor,sum_res_cnt,sum_dwell_cnt,commassoc"}))
get("census_ward_2021.json", S + "k4pr-cznc.json?$limit=2")
get("civic_census_ward.json", S + "dvig-zn6d.json?$limit=200&$order=census_year DESC".replace(" ", "%20"))
get("comm_by_ward.json", S + "jd78-wxjp.json?$limit=1000")
get("capmap.html", "https://www.calgary.ca/capitalprojectsmap")
for year in (2026, 2025, 2024):
    for w in range(1, 15):
        get(f"ward-{w:02d}-{year}.pdf", f"https://www.calgary.ca/content/dam/www/citycouncil/documents/expenses-{year}/ward-{w:02d}-budget-and-expenditure-{year}.pdf")
    get(f"mayor-{year}.pdf", f"https://www.calgary.ca/content/dam/www/citycouncil/documents/expenses-{year}/mayor-budget-and-expenditure-{year}.pdf")
for name, url in [("council-expenses.html", "https://www.calgary.ca/council/expenses.html"),
                  ("council-budget.html", "https://www.calgary.ca/council/council-budget-and-expenses.html"),
                  ("ward10.html", "https://www.calgary.ca/ward-10.html"),
                  ("ward10b.html", "https://www.calgary.ca/council/ward-10.html")]:
    get(name, url)
json.dump(log, open("dump6/log.json", "w"), indent=1)
