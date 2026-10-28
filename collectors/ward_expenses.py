"""Collect each ward office's budget and expense disclosure from calgary.ca.

Every councillor's office publishes a "Ward Budget & Expenditure Disclosure"
PDF each year, updated through the year: the office budget, total spending
so far (salaries included), and every non-salary expense with its account,
month, amount, vendor and the councillor's stated reason.

Writes data/wards/ward_budgets.csv (one row per ward and year) and
data/wards/ward_expenses.csv (one row per listed expense). A year's rows are
replaced each time its PDF is read, since each PDF covers the year to date.
Years before last year are only fetched if they are missing.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "wards"
BUDGETS_CSV = DATA / "ward_budgets.csv"
EXPENSES_CSV = DATA / "ward_expenses.csv"

URL = "https://www.calgary.ca/content/dam/www/citycouncil/documents/expenses-{year}/ward-{ward:02d}-budget-and-expenditure-{year}.pdf"
FIRST_YEAR = 2022
WARDS = range(1, 15)
USER_AGENT = (
    "Mozilla/5.0 (compatible; TrackingOurCash-YYC/0.1; "
    "+https://github.com/TrackingOurCash/YYC)"
)

BUDGET_FIELDS = ["year", "ward", "councillor", "period_start", "period_end", "budget", "spent", "variance", "items", "url", "pdf_sha256"]
EXPENSE_FIELDS = ["year", "ward", "account_code", "account", "month", "amount", "vendor", "description"]

HEADERS = ("Account", "Date", "Amount", "Vendor", "Description/Rationale")
ACCOUNT_RE = re.compile(r"^\d{5}$")
MONTH_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*)?$")
AMOUNT_RE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")
MONTHS = {m: i for i, m in enumerate(["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
                                       "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"], 1)}


def lines_of(page) -> list[list[dict]]:
    """The page's words grouped into lines, left to right."""
    rows: dict[int, list] = defaultdict(list)
    for w in page.extract_words():
        rows[round(w["top"])].append(w)
    lines: list[list] = []
    last = None
    for top in sorted(rows):
        if last is not None and top - last <= 2:
            lines[-1].extend(rows[top])
        else:
            lines.append(list(rows[top]))
        last = top
    return [sorted(ws, key=lambda w: w["x0"]) for ws in lines]


def money(text: str) -> float | None:
    t = text.replace("$", "").replace(" ", "")
    if t in ("-", ""):
        return 0.0 if t == "-" else None
    if not AMOUNT_RE.match(t):
        return None
    neg = t.startswith("(") or t.startswith("-")
    return float(t.strip("()-").replace(",", "")) * (-1 if neg else 1)


def whole(v: float | None):
    return int(v) if v is not None and float(v).is_integer() else v


def iso_date(text: str) -> str:
    m = re.match(r"([A-Z]+)\s+(\d+),\s*(\d{4})", text.strip().upper())
    return dt.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))).isoformat() if m else ""


def parse_header(lines: list[list[dict]]) -> dict:
    """Budget, spending and variance sit on the left; the title, period and
    councillor on the right, sometimes on interleaved lines."""
    title_line = next((ws for ws in lines if any(w["text"] == "EXPENDITURE" for w in ws)), [])
    split = next((w["x0"] for w in title_line if w["text"] == "WARD"), 10**6) - 2
    left = " ".join(w["text"] for ws in lines for w in ws if w["x0"] < split)
    right = " ".join(w["text"] for ws in lines for w in ws if w["x0"] >= split)
    head = {}
    for key, label in (("budget", r"Budget"), ("spent", r"Expenditures(?:\s*\(1\))?"), ("variance", r"Variance")):
        m = re.search(label + r"\s*\$\s*(\(?[\d,]+\)?)", left)
        head[key] = money(m.group(1)) if m else None
    m = re.search(r"FOR THE PERIOD (.+?\d{4})\s*-\s*(.+?\d{4})", right)
    head["period_start"], head["period_end"] = (iso_date(m.group(1)), iso_date(m.group(2))) if m else ("", "")
    m = re.search(r"WARD\s+(\d+)(?:\s*-\s*(.+))?$", right)
    head["ward"] = int(m.group(1)) if m else None
    head["councillor"] = (m.group(2) or "").strip() if m else ""
    return head


def parse_pdf(data: bytes) -> tuple[dict, list[dict], list[str]]:
    """(header, expenses, lines that couldn't be read)."""
    head: dict = {}
    items: list[dict] = []
    skipped: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            lines = lines_of(page)
            at = next((i for i, ws in enumerate(lines) if {"Account", "Amount"} <= {w["text"] for w in ws}), None)
            if at is None:
                continue
            if not head:
                head = parse_header(lines[:at])
            cols = {w["text"]: w["x0"] for w in lines[at] if w["text"] in HEADERS}
            date_cut = (cols["Date"] + cols["Amount"]) / 2
            desc_x = cols.get("Description/Rationale", 10**6) - 3
            for ws in lines[at + 1:]:
                text = " ".join(w["text"] for w in ws)
                if text.startswith(("Note:", "(1)", "Total Expenditures")):
                    break
                if ACCOUNT_RE.match(ws[0]["text"]):
                    acct, month, vendor, desc, amount_parts = [], [], [], [], []
                    amount_end = None
                    for w in ws:
                        t = w["text"]
                        # Digits of one amount sometimes come out as two words.
                        if amount_end is not None and not vendor and re.match(r"^[\d,.)]+$", t) and w["x0"] - amount_end <= 4:
                            amount_parts.append(t)
                            amount_end = w["x1"]
                            continue
                        if w["x0"] < date_cut and not amount_parts and (month or (MONTH_RE.match(t) and w["x0"] > cols["Date"] - 20)):
                            month.append(t)
                        elif w["x0"] < date_cut and not amount_parts:
                            acct.append(t)
                        elif w["x0"] >= desc_x:
                            desc.append(t)
                        elif money("".join(amount_parts)) is None and (t == "$" or re.match(r"^[\d,()\-.]+\)?$", t)):
                            amount_parts.append(t)
                            amount_end = w["x1"]
                        else:
                            vendor.append(t)
                    amount = money("".join(amount_parts))
                    if amount is None:
                        skipped.append(text)
                        continue
                    code, _, name = " ".join(acct).partition(" - ")
                    items.append({"account_code": code, "account": name.strip(), "month": " ".join(month),
                                  "amount": amount, "vendor": " ".join(vendor), "description": " ".join(desc)})
                elif items:
                    # A wrapped vendor name or reason continues the last expense.
                    vend = [w["text"] for w in ws if cols["Amount"] < w["x0"] < desc_x]
                    desc = [w["text"] for w in ws if w["x0"] >= desc_x]
                    if vend:
                        items[-1]["vendor"] = f'{items[-1]["vendor"]} {" ".join(vend)}'.strip()
                    if desc:
                        items[-1]["description"] = f'{items[-1]["description"]} {" ".join(desc)}'.strip()
                    if not vend and not desc:
                        skipped.append(text)
    return head, items, skipped


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def run() -> dict:
    this_year = dt.date.today().year
    budgets = {(r["year"], r["ward"]): r for r in read_csv(BUDGETS_CSV)}
    expenses = defaultdict(list)
    for r in read_csv(EXPENSES_CSV):
        expenses[(r["year"], r["ward"])].append(r)

    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    report = {"read": 0, "missing": [], "skipped_lines": 0}
    for year in range(FIRST_YEAR, this_year + 1):
        for ward in WARDS:
            key = (str(year), str(ward))
            if year < this_year - 1 and key in budgets:
                continue
            url = URL.format(year=year, ward=ward)
            r = s.get(url, timeout=60)
            if r.status_code == 404:
                report["missing"].append(f"{year} ward {ward}")
                continue
            r.raise_for_status()
            sha = hashlib.sha256(r.content).hexdigest()
            if key in budgets and budgets[key].get("pdf_sha256") == sha:
                continue
            head, items, skipped = parse_pdf(r.content)
            if head.get("ward") != ward or head.get("budget") is None:
                print(f"Couldn't read the header of {url}", file=sys.stderr)
                continue
            for line in skipped:
                print(f"{year} ward {ward}: skipped line: {line}", file=sys.stderr)
            report["read"] += 1
            report["skipped_lines"] += len(skipped)
            budgets[key] = {
                "year": year, "ward": ward, "councillor": head["councillor"],
                "period_start": head["period_start"], "period_end": head["period_end"],
                "budget": whole(head["budget"]), "spent": whole(head["spent"]), "variance": whole(head["variance"]),
                "items": len(items), "url": url, "pdf_sha256": sha,
            }
            expenses[key] = [{"year": year, "ward": ward, **i, "amount": whole(i["amount"])} for i in items]

    order = sorted(budgets, key=lambda k: (int(k[0]), int(k[1])))
    write_csv(BUDGETS_CSV, [budgets[k] for k in order], BUDGET_FIELDS)
    write_csv(EXPENSES_CSV, [e for k in order for e in expenses.get(k, [])], EXPENSE_FIELDS)
    report["wards_years"] = len(budgets)
    return report


if __name__ == "__main__":
    print(json.dumps(run()))
