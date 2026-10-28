"""Turn the staff and payroll figures into site/data/workforce.json.

Annual reports restate earlier years, so each year's figure comes from the
newest report that has it. Departments come from the newest budget book;
departments without a management/union split (Police, Council, Civic
Partners, Corporate Programs) are the ones the City counts as outside City
administration.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "workforce"
OUT = ROOT / "site" / "data" / "workforce.json"


def read(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def history() -> list[dict]:
    latest: dict[tuple[int, str], tuple[int, float, str]] = {}
    for r in read(DATA / "annual_reports.csv"):
        key = (int(r["year"]), r["measure"])
        value = float(r["value"])
        if key not in latest or int(r["report_year"]) > latest[key][0]:
            latest[key] = (int(r["report_year"]), value, r["url"])
    years = sorted({y for y, _ in latest})
    out = []
    for y in years:
        get = lambda m: latest[(y, m)][1] if (y, m) in latest else None  # noqa: E731
        city, related = get("fte_city"), get("fte_related")
        combined = city + related if city is not None and related is not None else get("fte_all")
        per_city, per_related = get("per_1000_city"), get("per_1000_related")
        per_combined = round(per_city + per_related, 2) if per_city is not None and per_related is not None else get("per_1000_all")
        payroll = get("payroll")
        out.append({
            "year": y,
            "city": int(city) if city is not None else None,
            "related": int(related) if related is not None else None,
            "combined": int(combined) if combined is not None else None,
            "per_1000_city": per_city,
            "per_1000": per_combined,
            "payroll": int(payroll) if payroll is not None else None,
            "report": max((latest[(y, m)] for m in ("payroll", "fte_city", "fte_all") if (y, m) in latest))[2],
        })
    return out


def budget() -> dict | None:
    rows = read(DATA / "budget_fte.csv")
    if not rows:
        return None
    by_doc = defaultdict(list)
    for r in rows:
        by_doc[r["url"]].append(r)
    # The newest book: the one reaching furthest ahead, then the fullest.
    url = max(by_doc, key=lambda u: (max(int(r["year"]) for r in by_doc[u]), len(by_doc[u])))
    rows = by_doc[url]
    years = sorted({int(r["year"]) for r in rows})
    series = lambda pick: [next((int(r["fte"]) for r in pick if int(r["year"]) == y), 0) for y in years]  # noqa: E731

    departments = []
    names = list(dict.fromkeys(r["department"] for r in rows if r["kind"] == "department"))
    for name in names:
        mine = [r for r in rows if r["department"] == name]
        staff = {t: [r for r in mine if r["kind"] == "staff type" and r["line"] == t] for t in ("Management exempt", "Union and other")}
        units = list(dict.fromkeys(r["line"] for r in mine if r["kind"] == "business unit"))
        departments.append({
            "name": name,
            "fte": series([r for r in mine if r["kind"] == "department"]),
            "exempt": series(staff["Management exempt"]) if staff["Management exempt"] else None,
            "union": series(staff["Union and other"]) if staff["Union and other"] else None,
            "units": [{"name": u, "fte": series([r for r in mine if r["kind"] == "business unit" and r["line"] == u])} for u in units],
        })
    city = {r["line"]: r for r in rows if r["kind"] == "city"}
    city_series = lambda line: series([r for r in rows if r["kind"] == "city" and r["line"] == line])  # noqa: E731
    add_up = lambda key: [sum(d[key][i] for d in departments if d[key]) for i in range(len(years))]  # noqa: E731
    out = {
        "url": url,
        "years": years,
        "total": city_series("Total") if city else add_up("fte"),
        # From the departments, which add up to the total; the City's own
        # City administration rows don't always.
        "admin_exempt": add_up("exempt"),
        "admin_union": add_up("union"),
        "outside": [sum(d["fte"][i] for d in departments if d["exempt"] is None) for i in range(len(years))],
        "reported": {
            "admin_exempt": city_series("City administration, management exempt"),
            "admin_union": city_series("City administration, union & other"),
            "outside": city_series("Outside City Administration"),
        } if city else None,
        "departments": departments,
    }
    # Checks: departments add up to the total, and the ones without a
    # management/union split add up to "outside City administration". The
    # City rounds each line, so sums can be off by a position or two.
    def check(label: str, got: int, want: int) -> None:
        if abs(got - want) > max(3, want * 0.005):
            print(f"warning: {label} add to {got}, not {want}")

    for i, y in enumerate(years):
        if city:
            check(f"{y} departments", sum(d["fte"][i] for d in departments), out["total"][i])
            for key in ("admin_exempt", "admin_union", "outside"):
                check(f"{y} departments ({key})", out[key][i], out["reported"][key][i])
        for d in departments:
            if d["units"]:
                check(f"{y} {d['name']} business units", sum(u["fte"][i] for u in d["units"]), d["fte"][i])
    return out


def main() -> None:
    hist = history()
    bud = budget()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated": dt.date.today().isoformat(),
        "history": hist,
        "budget": bud,
    }, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(hist)} years, {hist[0]['year']}-{hist[-1]['year']}; "
          f"budget {bud['years'][0]}-{bud['years'][-1]}, {len(bud['departments'])} departments" if bud else "no budget")


if __name__ == "__main__":
    main()
