"""Backfill earlier job postings from the Internet Archive.

The City's careers page only lists open postings, and closed postings vanish
from its job site. The Internet Archive has captured calgary.ca/careers a
few times a month and some individual posting pages, so this rebuilds what
it can:

- every posting listed in an archived copy of the careers page since
  --since (default Jan 1 of this year), dated by the first capture that
  shows it ("seen by" rather than the true posting date), and
- department, pay and position counts from any archived copy of that
  posting's own page.

Rows are merged into data/jobs/postings.csv with source=archive. Rows the
daily collector already has are left alone. Safe to re-run.

Usage: python scripts/backfill_jobs_from_archive.py [--since 2026-01-01]
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collectors"))
import jobs  # noqa: E402

CDX = "http://web.archive.org/cdx/search/cdx"
RAW = "http://web.archive.org/web/{ts}id_/{url}"


def cdx(s: requests.Session, url: str, since: str) -> list[list[str]]:
    params = {"url": url, "from": since.replace("-", ""), "output": "json", "fl": "timestamp,original", "filter": "statuscode:200"}
    for attempt in range(4):
        r = s.get(CDX, params=params, timeout=120)
        if r.status_code == 200 and r.text.strip():
            rows = r.json()
            return rows[1:] if rows else []
        time.sleep(5 * (attempt + 1))
    r.raise_for_status()
    return []


def fetch(s: requests.Session, ts: str, url: str) -> str | None:
    for attempt in range(3):
        try:
            r = s.get(RAW.format(ts=ts, url=url), timeout=60)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=f"{dt.date.today().year}-01-01")
    args = ap.parse_args()

    s = requests.Session()
    s.headers["User-Agent"] = jobs.USER_AGENT
    rows = jobs.load_postings()
    found: dict[str, dict] = {}

    # 1. Archived copies of the careers page.
    captures = sorted(
        {ts: url for ts, url in cdx(s, "calgary.ca/careers.html", args.since)
         if re.search(r"calgary\.ca/careers\.html(\?redirect=%2Fcareers|\?redirect=/careers)?$", url)}.items()
    )
    for ts, url in captures:
        html = fetch(s, ts, url)
        if not html:
            continue
        day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        for p in jobs.parse_listing(html, base_url="https://www.calgary.ca/careers.html"):
            row = found.setdefault(p["job_id"], {**p, "first_seen": day, "last_seen": day})
            row["first_seen"] = min(row["first_seen"], day)
            row["last_seen"] = max(row["last_seen"], day)
        time.sleep(1)
    print(f"{len(captures)} careers page captures, {len(found)} postings", file=sys.stderr)

    # 2. Archived copies of individual posting pages.
    detail_caps: dict[str, tuple[str, str]] = {}
    for ts, url in cdx(s, "recruiting.calgary.ca/psc/hcm/*", args.since):
        m = re.search(r"JobOpeningId=(\d+)", url)
        if m:
            detail_caps.setdefault(m.group(1), (ts, url))
    with_details = 0
    for job_id, (ts, url) in sorted(detail_caps.items()):
        if job_id in rows and rows[job_id].get("details_fetched"):
            continue
        html = fetch(s, ts, url)
        fields = jobs.parse_detail(html) if html else {}
        if not fields.get("department"):
            continue
        day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        row = found.setdefault(job_id, {"job_id": job_id, "title": "", "category": "", "closing_date": "", "url": "", "first_seen": day, "last_seen": day})
        row.update(fields)
        row["details_fetched"] = day
        row["details_version"] = jobs.DETAILS_VERSION
        with_details += 1
        time.sleep(1)
    print(f"{len(detail_caps)} archived posting pages, {with_details} with pay details", file=sys.stderr)

    added = moved = 0
    for job_id, row in found.items():
        if job_id in rows:
            # An earlier capture can push back the date of a posting that
            # was itself only found in the archive.
            old = rows[job_id]
            if old.get("source") == "archive" and row["first_seen"] < old["first_seen"]:
                old["first_seen"] = row["first_seen"]
                moved += 1
            continue
        if not row.get("title"):
            continue  # a posting page with no listing entry has no title to show
        row["source"] = "archive"
        row.setdefault("url", "")
        rows[job_id] = row
        added += 1
    jobs.save_postings(rows)
    print(f"added {added} postings from the archive, moved {moved} to an earlier first-seen date; {len(rows)} tracked in total")


if __name__ == "__main__":
    main()
