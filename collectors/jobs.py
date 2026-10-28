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

# Bump when parse_detail changes so existing rows are re-read.
DETAILS_VERSION = "2"

FIELDS = [
    "job_id",
    "title",
    "category",
    "closing_date",
    "first_seen",
    "last_seen",
    "url",
    "department",
    "union",
    "pay_grade",
    "salary_min",
    "salary_max",
    "pay_basis",  # hourly | annual
    "hours_per_week",
    "permanent_positions",
    "temporary_positions",
    "position_type",
    "full_part_time",
    "location",
    "audience",
    "details_fetched",
    "details_version",
    "source",  # "" from the daily collector, "archive" from the backfill
]

LISTING_FIELDS = {"job_id", "title", "category", "closing_date", "url"}
TRACKING_FIELDS = {"first_seen", "last_seen", "details_fetched", "details_version", "source"}
DETAIL_FIELDS = [f for f in FIELDS if f not in LISTING_FIELDS | TRACKING_FIELDS]

CLOSING_RE = re.compile(r"Closing\s+date:?\s*(\d{4}[/-]\d{2}[/-]\d{2})", re.I)
PAY_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*\$?\s?([\d,]+(?:\.\d+)?))?"
)
POSITIONS_RE = re.compile(r"(\d+)\s+(Permanent|Regular|Temporary|Casual|Seasonal|Term)", re.I)
HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)[\s-]*hours?", re.I)


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


def _labelled(lines: list[str]) -> dict[str, str]:
    """Pair "Label:" lines with the value line that follows them."""
    out = {}
    for i, line in enumerate(lines[:-1]):
        if line.endswith(":") and len(line) < 40:
            out.setdefault(line[:-1].strip().lower(), lines[i + 1].strip())
    return out


def parse_detail(html: str) -> dict:
    """Read the "Position and Pay Information" block of a PeopleSoft posting.

    The block is a run of "Label:" lines, each followed by its value:
    Business Unit, Union, Position Type, Compensation, Hours of work,
    Location, Audience. Every field is optional.
    """
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True).replace("\xa0", " ")
    if "cookies enabled" in text.lower() and "sign in" in text.lower():
        return {}
    # A stray tag sometimes splits the first letter of a label onto its own line.
    text = re.sub(r"(?m)^(\w)\n", r"\1", text)
    lines = text.split("\n")

    # The header above the description has unlabelled pairs, e.g.
    # "Full/Part Time" then "Full-Time".
    lowered = [l.lower() for l in lines]
    head = {
        label: lines[lowered.index(label) + 1]
        for label in ("full/part time", "regular/temporary")
        if label in lowered[:-1]
    }

    marker = "Position and Pay Information"
    if marker not in text:
        return {"full_part_time": head.get("full/part time", "")} if head else {}
    info = _labelled(text.split(marker, 1)[1].split("\n"))

    out = {
        "department": info.get("business unit", ""),
        "union": info.get("union", ""),
        "position_type": info.get("position type", "") or head.get("regular/temporary", ""),
        "full_part_time": head.get("full/part time", ""),
        "location": info.get("location", ""),
        "audience": info.get("audience", ""),
    }

    counts = {"permanent": 0, "temporary": 0}
    for n, kind in POSITIONS_RE.findall(out["position_type"]):
        key = "permanent" if kind.lower() in ("permanent", "regular") else "temporary"
        counts[key] += int(n)
    if not any(counts.values()):
        key = "temporary" if "temp" in out["position_type"].lower() else "permanent"
        counts[key] = 1
    out["permanent_positions"] = str(counts["permanent"])
    out["temporary_positions"] = str(counts["temporary"])

    comp = info.get("compensation", "")
    m = PAY_RE.search(comp)
    if m:
        lo = float(m.group(1).replace(",", ""))
        hi = float((m.group(2) or m.group(1)).replace(",", ""))
        out["salary_min"], out["salary_max"] = f"{lo:.2f}", f"{hi:.2f}"
        out["pay_grade"] = comp[: m.start()].strip()
        lower = comp.lower()
        out["pay_basis"] = "hourly" if "hour" in lower or hi < 500 else "annual"

    h = HOURS_RE.search(info.get("hours of work", ""))
    if h:
        out["hours_per_week"] = h.group(1)

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
            if row["last_seen"] != today:
                continue
            if row.get("details_fetched") and row.get("details_version") == DETAILS_VERSION:
                continue
            try:
                fields = fetch_detail(s, row["url"])
                if not fields:
                    # Likely a sign-in or maintenance page; try again tomorrow
                    # while the posting is still open.
                    print(f"detail {job_id}: nothing readable on the page", file=sys.stderr)
                    continue
                for key in DETAIL_FIELDS:
                    row[key] = fields.get(key, "")
                row["details_fetched"] = today
                row["details_version"] = DETAILS_VERSION
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
