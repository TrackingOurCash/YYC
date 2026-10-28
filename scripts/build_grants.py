"""Turn data/grants/grants.csv into site/data/grants.json for the dashboard.

Recipients are spelled differently from year to year ("Counseling" and
"Counselling", "(TIES)" or not), so each name is reduced to a key and every
row with that key is shown under the most recent spelling. Civic Partners
capital rows name the project after the organization ("Contemporary Calgary
Arts Society - Phase 3 ..."); the project moves to the funded program column.

When one grant, year and recipient has both an approved budget and an actual
amount, only the actual is kept.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRANTS_CSV = ROOT / "data" / "grants" / "grants.csv"
OUT = ROOT / "site" / "data" / "grants.json"

STATUS_RANK = {"actual": 0, "budget": 1, "allocated": 2}
SPELLINGS = {"center": "centre", "counseling": "counselling", "independant": "independent", "youths": "youth"}


def display_name(name: str) -> str:
    name = re.sub(r"\s*\*+$", "", name)
    name = re.sub(r"(?i)\s*\(formerly[^)]*\)", "", name)
    name = re.sub(r"^(.*), The$", r"The \1", name)
    return " ".join(name.split())


def name_key(name: str) -> str:
    n = unicodedata.normalize("NFKD", display_name(name)).encode("ascii", "ignore").decode()
    n = re.sub(r"\(.*?\)", " ", n.lower()).replace("&", " and ")
    words = [SPELLINGS.get(w, w) for w in re.sub(r"[^a-z0-9 ]", " ", n).split()]
    if words[:1] == ["the"]:
        words = words[1:]
    if words[-1:] == ["society"] and len(words) > 2:
        words = words[:-1]
    return " ".join(words)


def split_projects(rows: list[dict]) -> None:
    """Move "Organization - Project" suffixes into funded_program when the
    part before the dash is a recipient in its own right."""
    keys = {name_key(r["organization"]) for r in rows}
    for r in rows:
        if " - " not in r["organization"]:
            continue
        org, project = r["organization"].split(" - ", 1)
        if name_key(org) in keys:
            r["organization"] = org
            r["funded_program"] = r["funded_program"] or project


def main() -> None:
    with GRANTS_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))
    split_projects(rows)

    # Most recent spelling of each recipient.
    names: dict[str, tuple] = {}
    for r in rows:
        k = name_key(r["organization"])
        rank = (r["year"], r["last_seen"])
        if k not in names or rank > names[k][0]:
            names[k] = (rank, display_name(r["organization"]))

    # One amount per grant, year and recipient, preferring actuals.
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r["source"], r["program"], name_key(r["organization"]), r["funded_program"].lower(), r["year"], r["period"])
        if key not in best or STATUS_RANK[r["status"]] < STATUS_RANK[best[key]["status"]]:
            best[key] = r

    orgs = sorted({names[k[2]][1] for k in best})
    programs = sorted({(r["source"], r["program"]) for r in best.values()}, key=lambda p: (p[0] != "Civic Partners", p[1] != "Operating grant", p[1]))
    org_index = {o: i for i, o in enumerate(orgs)}
    program_index = {p: i for i, p in enumerate(programs)}
    out_rows = sorted(
        (
            [
                org_index[names[k[2]][1]],
                program_index[(r["source"], r["program"])],
                r["funded_program"],
                int(r["year"]),
                r["period"],
                r["status"],
                round(float(r["amount"])),
            ]
            for k, r in best.items()
        ),
        key=lambda x: (-x[3], -x[6]),
    )
    pages = {r["source"]: r["page_url"] for r in rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated": dt.date.today().isoformat(),
        "fields": ["org", "program", "funded_program", "year", "period", "status", "amount"],
        "orgs": orgs,
        "programs": [{"source": s, "name": p, "page": pages[s]} for s, p in programs],
        "rows": out_rows,
    }, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out_rows)} grants to {len(orgs)} recipients")


if __name__ == "__main__":
    main()
