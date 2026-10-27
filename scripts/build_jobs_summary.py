"""Turn data/jobs/postings.csv into the dashboard's job data.

Writes site/data/postings.json (one record per posting) and
site/data/jobs_summary.json (totals by month first seen, job category,
department and overall).

Cost is the midpoint of the pay range times the number of positions.
Hourly rates are annualised from the posting's weekly hours (the City
standard of 35 when a posting doesn't say). Temporary positions count at
the same annual rate, so the cost is a yearly run rate, not the total paid
over a fixed-length term.

Where pay comes from, in order:
  posting      the posting's own "Position and Pay Information" block
  salary list  the City's compensation disclosure list for the same title
  same title   another posting with the same title that did show pay
Postings matched by none of these have no cost.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTINGS_CSV = ROOT / "data" / "jobs" / "postings.csv"
COMPENSATION_CSV = ROOT / "data" / "jobs" / "compensation.csv"
OUT = ROOT / "site" / "data" / "jobs_summary.json"
POSTINGS_OUT = ROOT / "site" / "data" / "postings.json"

STANDARD_WEEKLY_HOURS = 35

# Postings spell some business units several ways; group them under one name.
DEPARTMENT_ALIASES = {
    "calgary police services": "Calgary Police Service",
    "chief administrator´s office": "Chief Administrative Office",
    "chief administrator's office": "Chief Administrative Office",
    "capital planning & business services": "Capital Planning and Business Services",
    "operational services": "Operational Services",
}


def department(row: dict) -> str:
    name = " ".join((row.get("department") or "").split())
    return DEPARTMENT_ALIASES.get(name.lower(), name) or "Not stated"


def title_key(title: str) -> str:
    """Normalise a posting title so it can match the salary list:
    drop "Calgary Police Service -" prefixes, "- AMENDMENT"-style suffixes,
    work-pattern suffixes, anything in brackets and the word "and"."""
    t = re.sub(r"(?i)^calgary police service\s*-\s*", "", title)
    t = re.sub(r"(?i)\s*-\s*(amendment|amendmnt|re-?post(ing)?|internal only|extended).*$", "", t)
    t = re.sub(r"(?i),?\s*(part-time|on-call|temporary|casual|seasonal)$", "", t)
    t = re.sub(r"\(.*?\)", "", t.lower())
    return " ".join(w for w in re.sub(r"[^a-z0-9 ]", " ", t).split() if w != "and")


def posted_annual_midpoint(row: dict) -> float | None:
    try:
        lo, hi = float(row["salary_min"]), float(row["salary_max"])
    except (KeyError, ValueError):
        return None
    mid = (lo + hi) / 2
    if row.get("pay_basis") == "hourly":
        try:
            hours = float(row.get("hours_per_week") or STANDARD_WEEKLY_HOURS)
        except ValueError:
            hours = STANDARD_WEEKLY_HOURS
        mid *= hours * 52
    return mid


def load_salary_list() -> dict[str, float]:
    """Title key -> annual midpoint, from the latest year of the list."""
    if not COMPENSATION_CSV.exists():
        return {}
    with COMPENSATION_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    latest = max(r["year"] for r in rows)
    out = {}
    for r in rows:
        if r["year"] != latest:
            continue
        try:
            mid = (float(r["minimum_annual_base_rate"]) + float(r["maximum_annual_base_rate"])) / 2
        except ValueError:
            continue
        key = title_key(r["position_title"])
        out[key] = mid
        # Some list titles carry a trailing " CH" code that postings don't.
        if key.endswith(" ch"):
            out.setdefault(key[:-3], mid)
    return out


class PayEstimator:
    def __init__(self, rows: list[dict]):
        self.salary_list = load_salary_list()
        self.by_title: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            mid = posted_annual_midpoint(r)
            if mid is not None:
                self.by_title[title_key(r["title"])].append(mid)

    def annual_midpoint(self, row: dict) -> tuple[float | None, str]:
        mid = posted_annual_midpoint(row)
        if mid is not None:
            return mid, "posting"
        key = title_key(row["title"])
        if key in self.salary_list:
            return self.salary_list[key], "salary list"
        if self.by_title.get(key):
            seen = self.by_title[key]
            return sum(seen) / len(seen), "same title"
        return None, ""


def positions(row: dict) -> tuple[int, int, int]:
    """(permanent, temporary, type not known). A posting whose own page
    wasn't read counts as one position of unknown type."""
    def num(key):
        try:
            return int(row.get(key) or 0)
        except ValueError:
            return 0

    perm, temp = num("permanent_positions"), num("temporary_positions")
    return (perm, temp, 0) if perm + temp else (0, 0, 1)


def posting_record(row: dict, pay: PayEstimator) -> dict:
    perm, temp, unknown = positions(row)
    mid, source = pay.annual_midpoint(row)
    return {
        "id": row["job_id"],
        "title": row["title"],
        "department": department(row),
        "category": row.get("category") or "Uncategorised",
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "closing": row.get("closing_date", ""),
        "pay_min": float(row["salary_min"]) if row.get("salary_min") else None,
        "pay_max": float(row["salary_max"]) if row.get("salary_max") else None,
        "pay_basis": row.get("pay_basis", ""),
        "union": row.get("union", ""),
        "permanent": perm,
        "temporary": temp,
        "unknown": unknown,
        "est_annual_cost": round(mid * (perm + temp + unknown)) if mid is not None else None,
        "pay_source": source,
        "archived": row.get("source") == "archive",
        "url": row.get("url", ""),
    }


def summarise(records: list[dict]) -> dict:
    def bucket():
        return {"postings": 0, "positions": 0, "permanent": 0, "temporary": 0, "unknown_type": 0, "est_annual_cost": 0, "with_pay": 0}

    by_month = defaultdict(bucket)
    by_category = defaultdict(bucket)
    by_department = defaultdict(bucket)
    total = bucket()
    for r in records:
        for b in (by_month[r["first_seen"][:7]], by_category[r["category"]], by_department[r["department"]], total):
            b["postings"] += 1
            b["positions"] += r["permanent"] + r["temporary"] + r["unknown"]
            b["permanent"] += r["permanent"]
            b["temporary"] += r["temporary"]
            b["unknown_type"] += r["unknown"]
            if r["est_annual_cost"] is not None:
                b["with_pay"] += 1
                b["est_annual_cost"] += r["est_annual_cost"]

    by_postings = lambda d: dict(sorted(d.items(), key=lambda kv: -kv[1]["postings"]))  # noqa: E731
    return {
        "generated": dt.date.today().isoformat(),
        "tracking_since": min((r["first_seen"] for r in records), default=None),
        "total": total,
        "by_month": dict(sorted(by_month.items())),
        "by_category": by_postings(by_category),
        "by_department": by_postings(by_department),
    }


def main() -> None:
    rows = []
    if POSTINGS_CSV.exists():
        with POSTINGS_CSV.open(newline="") as f:
            rows = list(csv.DictReader(f))
    pay = PayEstimator(rows)
    records = sorted((posting_record(r, pay) for r in rows), key=lambda r: (r["first_seen"], r["id"]), reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summarise(records), indent=1) + "\n")
    POSTINGS_OUT.write_text(json.dumps(records, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} and {POSTINGS_OUT.relative_to(ROOT)} from {len(rows)} postings")


if __name__ == "__main__":
    main()
