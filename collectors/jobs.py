"""Collect City of Calgary job postings.

Reads the public careers page, records every posting by its PeopleSoft
JobOpeningId, and keeps a running table in data/jobs/postings.csv.

The careers page shows no posting date, so the date we first see an ID is
used as its posting date. Counts therefore start on the first day this runs.

Usage:
    python collectors/jobs.py            # list page + details for new postings
    python collectors/jobs.py --no-details
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "jobs"
POSTINGS_CSV = DATA / "postings.csv"
SNAPSHOTS = DATA / "snapshots"

CAREERS_URL = "https://www.calgary.ca/careers.html"
USER_AGENT = (
    "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; "
    "+https://github.com/TrackingOurCash/YYC)"
)

FIELDS = [
    "job_id",
    "title",
    "category",
    "closing_date",
    "first_seen",
    "last_seen",
    "url",
    "department",
    "salary_min",
    "salary_max",
    "pay_basis",  # hourly | annual | ""
    "union",
    "employment_type",
    "positions",
    "details_fetched",
]

CLOSING_RE = re.compile(r"Closing\s+date:?\s*(\d{4}[/-]\d{2}[/-]\d{2})", re.I)
MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def job_id_from_url(url: str) -> str | None:
    ids = parse_qs(urlparse(url).query).get("JobOpeningId")
    return ids[0] if ids else None


def nearest_category(a) -> str:
    """The careers page groups postings under a heading per job category."""
    for el in a.find_all_previous(["h2", "h3", "h4", "button", "summary"]):
        text = el.get_text(" ", strip=True)
        if text and "JobOpeningId" not in text and len(text) < 80:
            return re.sub(r"\s*\(\d+\)\s*$", "", text)
    return ""


def parse_listing(html: str, base_url: str = CAREERS_URL) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    postings: dict[str, dict] = {}
    for a in soup.find_all("a", href=re.compile(r"JobOpeningId=", re.I)):
        url = urljoin(base_url, a["href"])
        job_id = job_id_from_url(url)
        if not job_id or job_id in postings:
            continue
        container = a.find_parent(["li", "tr", "article", "div", "p"]) or a
        text = container.get_text(" ", strip=True)
        closing = CLOSING_RE.search(text)
        postings[job_id] = {
            "job_id": job_id,
            "title": a.get_text(" ", strip=True),
            "category": nearest_category(a),
            "closing_date": closing.group(1).replace("/", "-") if closing else "",
            "url": url,
        }
    return list(postings.values())


def _label_value(text: str, *labels: str) -> str:
    for label in labels:
        m = re.search(rf"{label}\s*:?\s*(.+?)(?:\n|$)", text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def parse_detail(html: str) -> dict:
    """Best-effort extraction from a PeopleSoft posting page.

    PeopleSoft pages vary by posting, so every field is optional.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    if "cookies enabled" in text.lower() and "sign in" in text.lower():
        return {}

    out = {
        "department": _label_value(text, "Business Unit", "Department", "Service Line"),
        "union": _label_value(text, "Union", "Bargaining Unit"),
        "employment_type": _label_value(
            text, "Regular/Temporary", "Employment Type", "Job Type", "Position Type"
        ),
        "positions": _label_value(text, "Number of Positions", "Openings"),
    }

    pay_line = _label_value(text, "Salary", "Pay Range", "Compensation", "Wage", "Rate of Pay")
    amounts = [float(x.replace(",", "")) for x in MONEY_RE.findall(pay_line or text)]
    if amounts:
        lo, hi = min(amounts[:2]), max(amounts[:2])
        out["salary_min"], out["salary_max"] = f"{lo:.2f}", f"{hi:.2f}"
        context = (pay_line or text).lower()
        if "hour" in context or hi < 200:
            out["pay_basis"] = "hourly"
        elif "annual" in context or "year" in context or hi > 10000:
            out["pay_basis"] = "annual"
    return {k: v for k, v in out.items() if v}


def fetch_detail(s: requests.Session, url: str) -> dict:
    # PeopleSoft sets its session cookies on the first hit and shows a
    # "cookies required" page; the second request with cookies gets the posting.
    for _ in range(2):
        r = s.get(url, timeout=30)
        r.raise_for_status()
        fields = parse_detail(r.text)
        if fields:
            return fields
    return {}


def load_postings() -> dict[str, dict]:
    if not POSTINGS_CSV.exists():
        return {}
    with POSTINGS_CSV.open(newline="") as f:
        return {row["job_id"]: row for row in csv.DictReader(f)}


def save_postings(rows: dict[str, dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: (r["first_seen"], int(r["job_id"])))
    with POSTINGS_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in ordered:
            w.writerow({k: row.get(k, "") for k in FIELDS})


def run(details: bool = True, today: str | None = None) -> dict:
    today = today or dt.date.today().isoformat()
    s = session()
    r = s.get(CAREERS_URL, timeout=30)
    r.raise_for_status()
    listing = parse_listing(r.text)
    if not listing:
        raise SystemExit("No postings found on the careers page; the layout may have changed.")

    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    (SNAPSHOTS / f"{today}.json").write_text(json.dumps(listing, indent=1) + "\n")

    rows = load_postings()
    new_ids = []
    for p in listing:
        row = rows.get(p["job_id"])
        if row is None:
            row = {"first_seen": today, "details_fetched": ""}
            new_ids.append(p["job_id"])
        row.update(p)
        row["last_seen"] = today
        rows[p["job_id"]] = row

    if details:
        for job_id, row in rows.items():
            if row.get("details_fetched") or row["last_seen"] != today:
                continue
            try:
                row.update(fetch_detail(s, row["url"]))
                row["details_fetched"] = today
            except requests.RequestException as e:
                print(f"detail {job_id}: {e}", file=sys.stderr)
            time.sleep(1)

    save_postings(rows)
    return {"open": len(listing), "new": len(new_ids), "total_tracked": len(rows)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-details", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(details=not args.no_details)))
