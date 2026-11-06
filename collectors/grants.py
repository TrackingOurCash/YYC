"""Collect the grants the City of Calgary lists by recipient.

Two calgary.ca pages, each a set of tables with one row per organization:

  Civic Partners funding   operating, capital, community safety and
                           innovation grants to arm's-length partners
                           (the Library, Calgary Arts Development, the Zoo...)
  FCSS funding allocations Family & Community Support Services grants to
                           social agencies, by funded program, 2021 onwards

The pages only show the current funding cycle, so data/grants/grants.csv
keeps every row ever seen and marks when it was first and last on the page.
A year can appear twice for one grant, once as the approved budget and later
as the actual; scripts/build_grants.py keeps the actual.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "grants" / "grants.csv"

PAGES = {
    "Civic Partners": "https://www.calgary.ca/our-finances/civic-partners-funding.html",
    "FCSS": "https://www.calgary.ca/social-services/funding/organization-allocations.html",
}
USER_AGENT = (
    "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; "
    "+https://github.com/TrackingOurCash/YYC)"
)

FIELDS = [
    "source",
    "program",
    "organization",
    "funded_program",
    "year",
    "period",
    "status",
    "amount",
    "first_seen",
    "last_seen",
    "page_url",
]
KEY = ("source", "program", "organization", "funded_program", "year", "period", "status")

# Civic Partners section headings -> program name.
CIVIC_PROGRAMS = [
    ("operating", "Operating grant"),
    ("capital", "Capital grant"),
    ("safety", "Community safety grant"),
    ("innovation", "Innovation grant"),
]

# A page listing fewer rows than this share of its last good read is
# treated as broken (see check_count).
MIN_SHARE = 0.8
YEAR_RE = re.compile(r"\b(20\d\d)\b")
AMOUNT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")


def clean(text: str) -> str:
    return " ".join(text.replace("​", "").replace("\xa0", " ").split())


def cell_text(cell) -> str:
    """A cell's text without the "Organization:"-style label the page adds
    for phone screens."""
    for label in cell.select(".table-label"):
        label.decompose()
    for br in cell.find_all("br"):
        br.replace_with(" ")
    # No separator: the page sometimes splits a word across inline tags.
    return clean(cell.get_text())


def program_name(source: str, table) -> str:
    if source == "FCSS":
        return "FCSS"
    heading = table.find_previous("h2")
    text = heading.get_text(" ").lower() if heading else ""
    for word, name in CIVIC_PROGRAMS:
        if word in text:
            return name
    return clean(heading.get_text(" ")) if heading else "Other"


def column_kind(header: str) -> dict:
    h = header.lower()
    if "organization" in h or "organisation" in h:
        return {"kind": "organization"}
    # Checked before the year: some headers read "2022 Funded Program".
    if "program" in h:
        return {"kind": "funded_program"}
    year = YEAR_RE.search(h)
    if year:
        status = "actual" if "actual" in h else "budget" if "budget" in h else "allocated"
        return {"kind": "amount", "year": year.group(1), "period": "Q1" if "q1" in h else "", "status": status}
    return {"kind": "other"}


def heading_year(table) -> str | None:
    """The year in the heading above a table, e.g. "Family & Community
    Support Services 2026 - funding allocations"."""
    heading = table.find_previous(["h2", "h3", "h4"])
    m = YEAR_RE.search(heading.get_text(" ")) if heading else None
    return m.group(1) if m else None


def program_title(text: str) -> str:
    """ "Honouring the Bonds: To support long-term healing..." -> the name.
    The description nearly always starts "To ...", and some names have a
    colon of their own ("Calgary AfterSchool: Bridge Club")."""
    m = re.match(r"(.{3,150}?)\s*:\s+(?=To\b)", text) or re.match(r"(.{3,150}?)\s*:\s", text)
    return m.group(1) if m else text


def parse_page(html: str, source: str, url: str) -> list[dict]:
    """Rows from every table with an Organization column. Amounts come from
    columns headed by a year ("2025 Actual"), or, since November 2026 on the
    FCSS page, from a single "Funding amount" column in a table per year
    with the year in the heading above it."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        headers = [clean(c.get_text(" ")) for c in trs[0].find_all(["th", "td"])]
        kinds = [column_kind(h) for h in headers]
        if not any(k["kind"] == "organization" for k in kinds):
            continue
        year = heading_year(table)
        if year and not any(k["kind"] == "amount" for k in kinds):
            kinds = [{"kind": "amount", "year": year, "period": "", "status": "allocated"}
                     if k["kind"] == "other" and re.search(r"amount|funding", h, re.I) else k
                     for h, k in zip(headers, kinds)]
        program = program_name(source, table)
        for tr in trs[1:]:
            cells = [cell_text(c) for c in tr.find_all(["th", "td"])]
            if len(cells) != len(kinds):
                continue
            base = {"source": source, "program": program, "organization": "", "funded_program": "", "page_url": url}
            for k, v in zip(kinds, cells):
                if k["kind"] in ("organization", "funded_program"):
                    base[k["kind"]] = v
            full = base["funded_program"]
            base["funded_program"] = program_title(full)
            if not base["organization"] or base["organization"].lower().startswith("total"):
                continue
            for k, v in zip(kinds, cells):
                m = AMOUNT_RE.search(v) if k["kind"] == "amount" else None
                if m:
                    rows.append({**base, "year": k["year"], "period": k["period"], "status": k["status"],
                                 "amount": m.group(1).replace(",", ""), "_full": full})
    # Two programs of one organization can share a name ("Calgary AfterSchool"
    # twice); give those their whole name and description so both are kept.
    seen = defaultdict(int)
    for r in rows:
        seen[tuple(r[k] for k in KEY)] += 1
    for r in rows:
        if seen[tuple(r[k] for k in KEY)] > 1:
            r["funded_program"] = r["_full"]
        del r["_full"]
    return rows


def load() -> dict[tuple, dict]:
    if not OUT.exists():
        return {}
    with OUT.open(newline="") as f:
        return {tuple(r[k] for k in KEY): r for r in csv.DictReader(f)}


def save(rows: dict[tuple, dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for key in sorted(rows):
            w.writerow({k: rows[key].get(k, "") for k in FIELDS})


def check_count(source: str, found: list[dict], known: dict[tuple, dict]) -> None:
    """Stop if a page lists far fewer rows than at its last good read, which
    means it came back cut short or half changed rather than really
    shrinking."""
    seen = [r["last_seen"] for r in known.values() if r["source"] == source]
    before = sum(1 for r in known.values() if r["source"] == source and r["last_seen"] == max(seen)) if seen else 0
    if len(found) < before * MIN_SHARE:
        raise SystemExit(f"{source}: found {len(found)} grant rows, {before} last time; keeping the earlier data.")


def run(only: list[str] | None = None) -> dict:
    today = dt.date.today().isoformat()
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    known = load()
    counts = {}
    for source, url in PAGES.items():
        if only and source not in only:
            continue
        r = s.get(url, timeout=60)
        r.raise_for_status()
        found = parse_page(r.text, source, url)
        if not found:
            raise SystemExit(f"No grant rows found on {url}; the page layout may have changed.")
        check_count(source, found, known)
        counts[source] = len(found)
        for row in found:
            key = tuple(row[k] for k in KEY)
            old = known.get(key)
            known[key] = {**row, "first_seen": old["first_seen"] if old else today, "last_seen": today}
    save(known)
    return {"rows_on_pages": counts, "rows_kept": len(known)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", choices=list(PAGES), help="read just these pages")
    print(json.dumps(run(ap.parse_args().only)))
