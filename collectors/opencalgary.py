"""Download a dataset from Open Calgary (data.calgary.ca, a Socrata portal)."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import requests

BASE = "https://data.calgary.ca/resource"
USER_AGENT = "TrackingOurCash-YYC/0.1 (+https://github.com/TrackingOurCash/YYC)"
PAGE = 50000


def fetch_all(dataset_id: str, **params) -> list[dict]:
    """Every row of a dataset, paging through the SODA API."""
    rows: list[dict] = []
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    while True:
        query = {"$limit": PAGE, "$offset": len(rows), "$order": ":id", **params}
        r = s.get(f"{BASE}/{dataset_id}.json", params=query, timeout=120)
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if len(page) < PAGE:
            return rows


def last_updated(dataset_id: str) -> str | None:
    """The date the City last refreshed a dataset's rows, or None if the
    portal doesn't say. Some datasets only update monthly."""
    try:
        r = requests.get(f"https://data.calgary.ca/api/views/{dataset_id}.json", headers={"User-Agent": USER_AGENT}, timeout=60)
        r.raise_for_status()
        ts = r.json().get("rowsUpdatedAt")
    except (requests.RequestException, ValueError):
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else None


def write_csv(path: Path, rows: list[dict], fields: list[str], sort_key=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sort_key:
        rows = sorted(rows, key=sort_key)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})
