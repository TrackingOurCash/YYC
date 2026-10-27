"""Collect the City of Calgary compensation disclosure list from Open Calgary.

Dataset: Compensation Disclosure List (9bze-mzx6), the base salary range
Council approved for each position title, 2014 to now. The jobs summary
uses the latest year to estimate pay for postings whose own page wasn't
captured (see scripts/build_jobs_summary.py).
"""

from __future__ import annotations

import json
from pathlib import Path

from opencalgary import fetch_all, write_csv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "jobs" / "compensation.csv"
DATASET = "9bze-mzx6"
FIELDS = ["year", "position_title", "minimum_annual_base_rate", "maximum_annual_base_rate"]


def run() -> dict:
    rows = fetch_all(DATASET)
    if not rows:
        raise SystemExit("Open Calgary returned no compensation rows.")
    write_csv(OUT, rows, FIELDS, sort_key=lambda r: (r["year"], r["position_title"]))
    return {"rows": len(rows), "latest_year": max(r["year"] for r in rows)}


if __name__ == "__main__":
    print(json.dumps(run()))
