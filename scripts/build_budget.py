"""Turn data/budget/open_budget.csv into site/data/budget.json for the dashboard."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "budget" / "open_budget.csv"
OUT = ROOT / "site" / "data" / "budget.json"


def main() -> None:
    with SRC.open(newline="") as f:
        rows = list(csv.DictReader(f))
    records = [
        {
            "year": int(r["year"]),
            "status": r["budget_status"],
            "fund": "capital" if r["fund"].lower().startswith("capital") else "operating",
            "department": r["budget_department"],
            "unit": r["level_2"] or r["business_unit"],
            "amount": round(float(r["budget"]) * 1e6),
        }
        for r in rows
        if r.get("budget")
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} from {len(records)} rows")


if __name__ == "__main__":
    main()
