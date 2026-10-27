"""Collect the City of Calgary budget from Open Calgary.

Dataset: Calgary Open Budget (fqax-i3nz), the 2023-2026 Service Plans and
Budgets by department, business unit, year and fund. Amounts are in millions
of dollars. Operating amounts are net of recoveries; capital runs to 2032.
"""

from __future__ import annotations

import json
from pathlib import Path

from opencalgary import fetch_all, write_csv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "budget" / "open_budget.csv"
DATASET = "fqax-i3nz"
FIELDS = [
    "year",
    "budget_status",
    "fund",
    "budget_department",
    "level_2",
    "business_unit",
    "actual_department",
    "budget",
]


def run() -> dict:
    rows = fetch_all(DATASET)
    if not rows:
        raise SystemExit("Open Calgary returned no budget rows.")
    write_csv(
        OUT,
        rows,
        FIELDS,
        sort_key=lambda r: (r["year"], r["budget_status"], r["fund"], r["budget_department"], r["level_2"], r["business_unit"]),
    )
    return {"rows": len(rows)}


if __name__ == "__main__":
    print(json.dumps(run()))
