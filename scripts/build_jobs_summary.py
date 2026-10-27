"""Turn data/jobs/postings.csv into site/data/jobs_summary.json for the dashboard.

Totals are by month first seen, by job category, by department (when the
posting page gave one), and overall. Cost estimates use the midpoint of each
posted pay range; hourly rates are annualised at 2,080 hours.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTINGS_CSV = ROOT / "data" / "jobs" / "postings.csv"
OUT = ROOT / "site" / "data" / "jobs_summary.json"

HOURS_PER_YEAR = 2080


def annual_midpoint(row: dict) -> float | None:
    try:
        lo, hi = float(row["salary_min"]), float(row["salary_max"])
    except (KeyError, ValueError):
        return None
    mid = (lo + hi) / 2
    if row.get("pay_basis") == "hourly":
        mid *= HOURS_PER_YEAR
    return mid


def positions(row: dict) -> int:
    try:
        return max(1, int(row.get("positions") or 1))
    except ValueError:
        return 1


def summarise(rows: list[dict]) -> dict:
    def bucket():
        return {"postings": 0, "positions": 0, "est_annual_cost": 0.0, "with_pay": 0}

    by_month = defaultdict(bucket)
    by_category = defaultdict(bucket)
    by_department = defaultdict(bucket)
    total = bucket()

    for row in rows:
        n = positions(row)
        cost = annual_midpoint(row)
        keys = [
            by_month[row["first_seen"][:7]],
            by_category[row.get("category") or "Uncategorised"],
            by_department[row.get("department") or "Not stated"],
            total,
        ]
        for b in keys:
            b["postings"] += 1
            b["positions"] += n
            if cost is not None:
                b["with_pay"] += 1
                b["est_annual_cost"] += cost * n

    def rounded(d):
        return {k: {**v, "est_annual_cost": round(v["est_annual_cost"])} for k, v in d.items()}

    return {
        "generated": dt.date.today().isoformat(),
        "tracking_since": min((r["first_seen"] for r in rows), default=None),
        "total": rounded({"all": total})["all"],
        "by_month": dict(sorted(rounded(by_month).items())),
        "by_category": dict(sorted(rounded(by_category).items(), key=lambda kv: -kv[1]["postings"])),
        "by_department": dict(sorted(rounded(by_department).items(), key=lambda kv: -kv[1]["postings"])),
    }


def main() -> None:
    rows = []
    if POSTINGS_CSV.exists():
        with POSTINGS_CSV.open(newline="") as f:
            rows = list(csv.DictReader(f))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summarise(rows), indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} from {len(rows)} postings")


if __name__ == "__main__":
    main()
